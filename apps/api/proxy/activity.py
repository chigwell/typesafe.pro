"""Minute buckets with hourly rollups; bounded admin reads without Redis SCAN."""

import asyncio
import json
import time
from collections import Counter, defaultdict

WINDOWS = {"5m": 300, "1h": 3600, "24h": 86400, "7d": 604800}
PREFIX = "ts:obs:"


def buckets(start, end):
    cursor = int(start // 60) * 60
    stop = int(end // 60) * 60
    while cursor <= stop:
        size = 3600 if cursor % 3600 == 0 and cursor + 3600 <= stop else 60
        yield f"{PREFIX}{size}:{cursor}"
        cursor += size


class Activity:
    def __init__(self, redis, retention_seconds):
        self.redis = redis
        self.retention_seconds = retention_seconds
        self.counts = Counter()
        self.ips = {}
        self.paths = set()
        self.dropped = 0
        self.last_flush_at = None
        self.memory_checked_at = 0
        self.memory_available = True
        self.lock = asyncio.Lock()

    def count(self, event, path):
        # Bound user-controlled cardinality in the in-process batch and path dimension.
        if len(self.counts) > 32768 or len(self.ips) >= 8192:
            self.dropped += 1
            return
        if path not in self.paths and len(self.paths) >= 100:
            path = "[other paths]"
        self.paths.add(path)
        now = event["created_at"].timestamp()
        fields = {
            "requests": 1,
            "errors": int(bool(event["error_code"])),
            "rate_limited": int(event["status"] == 429),
            "estimated_tokens": event["estimated_tokens"],
            "usage_tokens": event["usage_tokens"] or 0,
            "usage_reported_requests": int(event["usage_tokens"] is not None),
            "duration_ms": round(event["duration_ms"]),
            "upstream_requests": int(event["master_key_id"] is not None),
            "upstream_ms": round(event["upstream_ms"] or 0),
            "request_bytes": event["request_bytes"],
        }
        dimensions = [("totals", "all"), ("tiers", event["client_tier"]), ("paths", path)]
        if event["master_key_id"] is not None:
            dimensions.append(("masters", event["master_key_id"]))
        for size in (60, 3600):
            key = f"{PREFIX}{size}:{int(now // size) * size}"
            for dimension, label in dimensions:
                for field, value in fields.items():
                    if value:
                        self.counts[key, json.dumps([dimension, label, field])] += value
            for dimension, value in (
                ("status_codes", event["status"]),
                ("status_classes", f"{event['status'] // 100}xx"),
                ("upstream_statuses", event["upstream_status"]),
            ):
                if value is not None:
                    self.counts[key, json.dumps([dimension, str(value), "requests"])] += 1
            if ip := event.get("client_ip"):
                item = self.ips.setdefault((key, ip), [0, 0, 0])
                item[0] += 1
                item[1] += fields["errors"]
                item[2] = max(item[2], now)

    async def flush(self):
        counts, self.counts = self.counts, Counter()
        ips, self.ips = self.ips, {}
        if not counts:
            return
        event_count = (
            sum(
                value
                for (_, field), value in counts.items()
                if field == json.dumps(["totals", "all", "requests"])
            )
            // 2
        )
        try:
            # The limiter shares Redis. Leave headroom for admission and login counters.
            if time.monotonic() - self.memory_checked_at > 5:
                memory = await self.redis.info("memory")
                maximum = memory.get("maxmemory", 0)
                self.memory_available = not maximum or memory["used_memory"] < maximum * 0.7
                self.memory_checked_at = time.monotonic()
            if not self.memory_available:
                self.dropped += event_count
                return
            async with self.redis.pipeline(transaction=False) as pipe:
                for (key, field), value in counts.items():
                    pipe.hincrby(key + ":counts", field, value)
                for (key, ip), (requests, errors, seen) in ips.items():
                    pipe.zincrby(key + ":ips", requests, ip)
                    if errors:
                        pipe.zincrby(key + ":errors", errors, ip)
                    pipe.zadd(key + ":seen", {ip: seen}, gt=True)
                for key in {key for key, _ in counts}:
                    # Absolute expiry prevents ongoing writes from extending old buckets.
                    size, started = map(int, key.removeprefix(PREFIX).split(":"))
                    for suffix in (":counts", ":ips", ":errors", ":seen"):
                        pipe.expireat(key + suffix, started + self.retention_seconds)
                await pipe.execute()
            self.last_flush_at = time.time()
        except Exception:
            self.dropped += event_count
            raise

    async def snapshot(self, window):
        now = time.time()
        # Reuse a short-lived snapshot for summary and IP pagination in the same refresh.
        cache = f"{PREFIX}view:{window}"
        async with self.lock:
            if cached := await self.redis.get(cache):
                return json.loads(cached)
            duration = min(WINDOWS[window], self.retention_seconds)
            # Windows are aligned to one minute, including the current partial minute.
            start = int(now // 60) * 60 - duration + 60
            keys = list(buckets(start, now))
            async with self.redis.pipeline(transaction=False) as pipe:
                for key in keys:
                    pipe.hgetall(key + ":counts")
                    pipe.zcard(key + ":ips")
                results = await pipe.execute()
            rows, candidates = results[::2], sum(results[1::2])
            memory = await self.redis.info("memory")
            maximum = memory.get("maxmemory", 0)
            if maximum and memory["used_memory"] + candidates * 512 > maximum * 0.9:
                raise RuntimeError("Insufficient Redis headroom for an activity snapshot")
            groups = defaultdict(lambda: defaultdict(Counter))
            for row in rows:
                for field, value in row.items():
                    dimension, label, metric = json.loads(field)
                    groups[dimension][label][metric] += int(value)
            totals = groups["totals"]["all"]
            for name in (
                "requests",
                "errors",
                "rate_limited",
                "estimated_tokens",
                "usage_tokens",
                "usage_reported_requests",
                "upstream_requests",
                "request_bytes",
            ):
                totals.setdefault(name, 0)
            for dimension in ("totals", "tiers", "masters", "paths"):
                for values in groups[dimension].values():
                    values["avg_duration_ms"] = round(
                        values["duration_ms"] / max(1, values["requests"]), 2
                    )
                    values["avg_upstream_ms"] = round(
                        values["upstream_ms"] / max(1, values["upstream_requests"]), 2
                    )
            # Versioned keys keep an in-flight page consistent when the cached view expires.
            ip_key = f"{cache}:{int(now)}"
            async with self.redis.pipeline(transaction=True) as pipe:
                for suffix, aggregate in ((":ips", "SUM"), (":errors", "SUM"), (":seen", "MAX")):
                    pipe.zunionstore(
                        ip_key + suffix, [key + suffix for key in keys], aggregate=aggregate
                    )
                    pipe.expire(ip_key + suffix, 30)
                pipe.zcard(ip_key + ":ips")
                result = await pipe.execute()
            totals["unique_ips"] = result[-1]
            payload = {
                "window": window,
                "from": start,
                "to": now,
                "resolution_seconds": 60,
                "totals": dict(totals),
                "ip_key": ip_key,
                "telemetry": {"dropped": self.dropped, "last_flush_at": self.last_flush_at},
            }
            for dimension in ("tiers", "masters", "paths"):
                payload[dimension] = sorted(
                    [{"name": label, **values} for label, values in groups[dimension].items()],
                    key=lambda row: (-row["requests"], row["name"]),
                )[: 100 if dimension == "paths" else 1000]
            for dimension in ("status_codes", "status_classes", "upstream_statuses"):
                payload[dimension] = {
                    label: v["requests"] for label, v in groups[dimension].items()
                }
            await self.redis.set(cache, json.dumps(payload), ex=10)
            return payload

    async def ip_page(self, window, page, page_size):
        snapshot = await self.snapshot(window)
        key = snapshot["ip_key"]
        rows = await self.redis.zrevrange(
            key + ":ips", (page - 1) * page_size, page * page_size - 1, withscores=True
        )
        items = []
        if rows:
            addresses = [ip for ip, _ in rows]
            errors = await self.redis.zmscore(key + ":errors", addresses)
            seen = await self.redis.zmscore(key + ":seen", addresses)
            items = [
                {"ip": ip, "requests": int(count), "errors": int(error or 0), "last_seen": last}
                for (ip, count), error, last in zip(rows, errors, seen, strict=True)
            ]
        return {
            "items": items,
            "total": snapshot["totals"]["unique_ips"],
            "page": page,
            "page_size": page_size,
            "from": snapshot["from"],
            "to": snapshot["to"],
        }
