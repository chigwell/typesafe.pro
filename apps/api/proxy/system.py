import asyncio
import os
import time
from collections import deque
from pathlib import Path


class SystemSampler:
    def __init__(self, settings):
        self.proc = Path(settings.host_proc_path)
        self.disk = settings.host_disk_path
        self.samples = deque(maxlen=61)
        self.previous_cpu = None
        self.stopped = asyncio.Event()
        self.task = None

    def sample(self):
        sample = {
            "at": time.time(),
            "cpu_percent": None,
            "memory": None,
            "disk": None,
            "load": None,
        }
        try:
            values = [int(v) for v in (self.proc / "stat").read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(values), values[3] + values[4]
            if self.previous_cpu:
                delta = total - self.previous_cpu[0]
                if delta > 0:
                    sample["cpu_percent"] = round(
                        max(0, min(100, 100 * (1 - (idle - self.previous_cpu[1]) / delta))), 2
                    )
            self.previous_cpu = total, idle
        except (OSError, ValueError, IndexError):
            pass
        try:
            memory = {
                name: int(value.split()[0]) * 1024
                for name, value in (
                    line.split(":", 1) for line in (self.proc / "meminfo").read_text().splitlines()
                )
            }
            total, available = memory["MemTotal"], memory["MemAvailable"]
            sample["memory"] = {
                "total_bytes": total,
                "used_bytes": total - available,
                "percent": round(100 * (total - available) / total, 2),
            }
        except (OSError, ValueError, KeyError, ZeroDivisionError):
            pass
        try:
            sample["load"] = [float(v) for v in (self.proc / "loadavg").read_text().split()[:3]]
        except (OSError, ValueError):
            pass
        try:
            disk = os.statvfs(self.disk)
            total = disk.f_blocks * disk.f_frsize
            used = (disk.f_blocks - disk.f_bfree) * disk.f_frsize
            sample["disk"] = {
                "total_bytes": total,
                "used_bytes": used,
                "available_bytes": disk.f_bavail * disk.f_frsize,
                "percent": round(100 * used / total, 2),
            }
        except (OSError, ValueError, ZeroDivisionError):
            pass
        self.samples.append(sample)

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def run(self):
        while not self.stopped.is_set():
            await asyncio.to_thread(self.sample)
            try:
                async with asyncio.timeout(5):
                    await self.stopped.wait()
            except TimeoutError:
                pass

    async def close(self):
        self.stopped.set()
        if self.task:
            await self.task

    async def status(self, state):
        async def probe(operation):
            started = time.monotonic()
            try:
                async with asyncio.timeout(2):
                    await operation()
                return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000, 2)}
            except Exception:
                return {"ok": False, "latency_ms": None}

        redis, postgres = await asyncio.gather(
            probe(state.redis.ping), probe(lambda: state.store.pool.fetchval("SELECT 1"))
        )
        samples = [row for row in list(self.samples) if row["at"] >= time.time() - 300]
        current = samples[-1] if samples else None
        return {
            "status": "ok"
            if current
            and all(current[k] is not None for k in ("cpu_percent", "memory", "disk", "load"))
            and redis["ok"]
            and postgres["ok"]
            else "partial",
            "release": state.settings.release_sha,
            "current": current,
            "history": samples,
            "redis": redis,
            "postgres": postgres,
            "queue": {
                "inflight": state.scheduler.inflight,
                "max_inflight": state.settings.max_inflight,
                "pending": {tier: len(q) for tier, q in state.scheduler.queues.items()},
                "body_bytes": state.budget.bytes,
            },
            "telemetry": {
                "dropped_errors": state.telemetry.dropped,
                "dropped_activity": state.telemetry.activity.dropped,
                "last_flush_at": state.telemetry.activity.last_flush_at,
            },
        }
