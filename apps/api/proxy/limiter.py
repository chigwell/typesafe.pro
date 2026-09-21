import math
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Bucket:
    remaining: float
    updated: float


class TokenBucket:
    def __init__(self, rate: int, burst: int, clock: Callable[[], float] = time.monotonic):
        self.rate = rate / 60
        self.burst = burst
        self.clock = clock
        self.buckets: dict[str, Bucket] = {}

    def retry_after(self, key_id: str) -> int:
        # No await in this operation: refill and debit are atomic on the one ASGI event loop.
        now = self.clock()
        bucket = self.buckets.setdefault(key_id, Bucket(self.burst, now))
        bucket.remaining = min(self.burst, bucket.remaining + (now - bucket.updated) * self.rate)
        bucket.updated = now
        if bucket.remaining < 1:
            return max(1, math.ceil((1 - bucket.remaining) / self.rate))
        bucket.remaining -= 1
        return 0
