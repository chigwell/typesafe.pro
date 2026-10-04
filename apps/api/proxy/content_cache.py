"""Bounded, serialized public response caching, independent of SQL persistence."""

import json
import time


class ResponseCache:
    """Bounded TTL cache of serialized public responses; cleared on every content write."""

    def __init__(self, ttl=60, limit=2000):
        self.ttl = ttl
        self.limit = limit
        self.items: dict = {}
        self.version = 0

    def get(self, key):
        item = self.items.get(key)
        if item and item[0] > time.monotonic() and item[1] == self.version:
            return item[2]
        return None

    def put(self, key, value):
        if len(self.items) >= self.limit:
            self.items.clear()
        self.items[key] = (time.monotonic() + self.ttl, self.version, value)

    def invalidate(self):
        self.version += 1
        self.items.clear()


async def cached(state, key, producer):
    """Serve a cached serialized body, or build, serialize and cache it."""
    cache: ResponseCache = state.content_cache
    body = cache.get(key)
    if body is None:
        value = await producer()
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        cache.put(key, body)
    return body


def new_state(app_state):
    app_state.content_cache = ResponseCache()
