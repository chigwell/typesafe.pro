import asyncio
import json
import logging
import re
import time
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import quote, unquote

from .config import RETENTION_SECONDS

logger = logging.getLogger("proxy")
ERROR_BODY_BYTES = 8192


def sanitize(value, secrets=(), limit=ERROR_BODY_BYTES):
    text = str(value)
    for secret in secrets:
        if not secret:
            continue
        secret = secret.decode("ascii", "ignore") if isinstance(secret, bytes) else secret
        # Raw, JSON-escaped and URL-escaped credentials can all be echoed by upstream.
        for form in (secret, json.dumps(secret)[1:-1], quote(secret, safe="")):
            text = text.replace(form, "[redacted]")
            # Capture can end in the middle of a credential.
            for length in range(min(len(form) - 1, len(text)), 3, -1):
                if text.endswith(form[:length]):
                    text = text[:-length] + "[redacted]"
                    break
    text = re.sub(r"(?i)Bearer\s+[^\s\"'<>]+", "Bearer [redacted]", text)
    text = re.sub(r"([?&][^=\s]+)=([^&\s\"']*)", r"\1=[redacted]", text)
    text = text.replace("\x00", "")
    return text.encode("utf-8", "replace")[:limit].decode("utf-8", "ignore")


def new_event(scope, request_id):
    return dict(
        created_at=datetime.now(UTC),
        request_id=request_id,
        client_tier="unknown",
        client_hash=None,
        ip_hash=None,
        method=scope["method"][:32],
        path=scope["path"][:1024],
        status=500,
        error_code="internal_error",
        duration_ms=0.0,
        queue_ms=0.0,
        upstream_ms=None,
        master_key_id=None,
        upstream_status=None,
        upstream_valid=None,
        estimated_tokens=0,
        usage_tokens=None,
        request_bytes=0,
        exception_class=None,
        error_detail=None,
        raw_response=None,
        response_truncated=False,
    )


class Telemetry:
    def __init__(self, store, redis):
        self.store, self.redis = store, redis
        self.errors = asyncio.Queue(maxsize=512)
        self.metrics = Counter()
        self.stopped = asyncio.Event()
        self.task = None
        self.dropped = 0

    def start(self):
        self.task = asyncio.create_task(self.run())

    def count(self, event):
        minute = int(time.time() // 60)
        dimensions = ("all", f"tier:{event['client_tier']}")
        if event["master_key_id"]:
            dimensions += (f"master:{event['master_key_id']}",)
        for dim in dimensions:
            key = f"ts:metrics:{minute}:{dim}"
            self.metrics[key, "requests"] += 1
            self.metrics[key, f"status_{event['status'] // 100}xx"] += 1
            self.metrics[key, "estimated_tokens"] += event["estimated_tokens"]
            self.metrics[key, "usage_tokens"] += event["usage_tokens"] or 0
            if event["master_key_id"]:
                self.metrics[key, "upstream_requests"] += 1

    def error(self, event, secrets=()):
        event = event.copy()
        for key in ("request_id", "method", "path", "error_detail", "raw_response"):
            if event[key] is not None:
                event[key] = sanitize(
                    unquote(event[key]) if key == "path" else event[key],
                    secrets,
                    {"request_id": 128, "method": 32, "path": 1024}.get(key, ERROR_BODY_BYTES),
                )
        try:
            self.errors.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            # Bounded fallback includes the sanitized event, never an exception traceback.
            logger.error("error_log_overflow %s", json.dumps(event, default=str))

    async def flush(self):
        events = []
        while not self.errors.empty() and len(events) < 64:
            events.append(self.errors.get_nowait())
        if events:
            try:
                await self.store.write_errors(events)
            except Exception:
                for event in events:
                    logger.error("error_log_unavailable %s", json.dumps(event, default=str))
        metrics, self.metrics = self.metrics, Counter()
        if metrics:
            try:
                async with self.redis.pipeline(transaction=False) as pipe:
                    for (key, field), value in metrics.items():
                        pipe.hincrby(key, field, value)
                    for key in {key for key, _ in metrics}:
                        pipe.expire(key, RETENTION_SECONDS)
                    await pipe.execute()
            except Exception:
                logger.warning("metrics_unavailable")

    async def run(self):
        next_cleanup = 0
        while not self.stopped.is_set():
            await self.flush()
            if time.monotonic() >= next_cleanup:
                try:
                    deleted = await self.store.cleanup()
                    next_cleanup = time.monotonic() + (1 if deleted == "DELETE 2000" else 60)
                except Exception:
                    logger.warning("error_cleanup_unavailable")
                    next_cleanup = time.monotonic() + 60
            try:
                async with asyncio.timeout(0.5):
                    await self.stopped.wait()
            except TimeoutError:
                pass

    async def close(self):
        self.stopped.set()
        if self.task:
            await self.task
        while not self.errors.empty():
            await self.flush()
        await self.flush()
