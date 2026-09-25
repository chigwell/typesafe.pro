import hashlib
import math

from .config import MASTER_REQUESTS_PER_MINUTE, MASTER_TOKENS_PER_SECOND, MAX_CONTEXT_TOKENS

# Redis TIME avoids clock skew. Expiry bounds memory even for one-off anonymous IPs.
CLIENT_BUCKET = """
local tm = redis.call('TIME')
local now = tonumber(tm[1]) + tonumber(tm[2]) / 1000000
local rate, burst = tonumber(ARGV[1]) / 60, tonumber(ARGV[2])
local old = redis.call('HMGET', KEYS[1], 'remaining', 'updated')
local remaining = math.min(burst, (tonumber(old[1]) or burst) +
    math.max(0, now - (tonumber(old[2]) or now)) * rate)
local retry = 0
if remaining >= 1 then remaining = remaining - 1
else retry = math.ceil((1 - remaining) / rate) end
redis.call('HSET', KEYS[1], 'remaining', remaining, 'updated', now)
redis.call('EXPIRE', KEYS[1], math.ceil(burst / rate) + 60)
return retry
"""

# All masters are inspected and one reservation is committed in the same Lua call.
# Rolling ceilings supplement buckets: a full bucket must not permit >250k in one second.
# Each request reserves the full documented context while the tokenizer is unpublished.
MASTER_ACQUIRE = """
local tm = redis.call('TIME')
local now = tonumber(tm[1]) + tonumber(tm[2]) / 1000000
local rpm, tps, cost = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local maxflight, lease, owner = tonumber(ARGV[4]), tonumber(ARGV[5]), ARGV[6]
local best, bestscore = 0, math.huge
for i = 1, #KEYS, 3 do
    local window, inflight, bucket = KEYS[i], KEYS[i+1], KEYS[i+2]
    redis.call('ZREMRANGEBYSCORE', window, '-inf', now - 60)
    redis.call('ZREMRANGEBYSCORE', inflight, '-inf', now)
    local nr = redis.call('ZCARD', window)
    local nt = redis.call('ZCOUNT', window, '(' .. (now - 1), '+inf') * cost
    local nf = redis.call('ZCARD', inflight)
    local old = redis.call('HMGET', bucket, 'requests', 'tokens', 'updated', 'blocked')
    local elapsed = math.max(0, now - (tonumber(old[3]) or now))
    local requests = math.min(rpm, (tonumber(old[1]) or rpm) + elapsed * rpm / 60)
    local tokens = math.min(tps, (tonumber(old[2]) or tps) + elapsed * tps)
    local blocked = tonumber(old[4]) or 0
    if nr < rpm and nt + cost <= tps and nf < maxflight and
       requests >= 1 and tokens >= cost and blocked <= now then
        local score = nf / maxflight + nr / rpm + nt / tps
        if score < bestscore then best, bestscore = i, score end
    end
    redis.call('HSET', bucket, 'requests', requests, 'tokens', tokens, 'updated', now)
    redis.call('EXPIRE', bucket, 180)
end
if best == 0 then return 0 end
redis.call('ZADD', KEYS[best], now, owner)
redis.call('EXPIRE', KEYS[best], 61)
redis.call('ZADD', KEYS[best+1], now + lease, owner)
redis.call('EXPIRE', KEYS[best+1], math.ceil(lease) + 1)
redis.call('HINCRBYFLOAT', KEYS[best+2], 'requests', -1)
redis.call('HINCRBYFLOAT', KEYS[best+2], 'tokens', -cost)
return (best + 2) / 3
"""

COOLDOWN = """
local tm = redis.call('TIME')
local until_time = tonumber(tm[1]) + tonumber(tm[2]) / 1000000 + tonumber(ARGV[1])
local old = tonumber(redis.call('HGET', KEYS[1], 'blocked')) or 0
redis.call('HSET', KEYS[1], 'blocked', math.max(old, until_time))
redis.call('EXPIRE', KEYS[1], 180)
"""


class Limiter:
    def __init__(self, redis, settings):
        self.redis = redis
        self.settings = settings
        self._client = redis.register_script(CLIENT_BUCKET)
        self._master = redis.register_script(MASTER_ACQUIRE)
        self._cooldown = redis.register_script(COOLDOWN)
        # Stable across renumbering; duplicate secrets are rejected at configuration time.
        self.prefixes = {
            key.key_id: "ts:master:" + hashlib.sha256(key.secret).hexdigest()
            for key in settings.masters
        }

    async def client_retry(self, identity, policy):
        return int(
            await self._client(
                keys=[f"ts:client:{identity.tier}:{identity.client_hash}"],
                args=[policy.rpm, policy.burst],
            )
        )

    async def analytics_view_retry(self, ip_hash):
        return int(
            await self._client(
                keys=[f"ts:analytics:view:{ip_hash}"],
                args=[self.settings.analytics_view_rpm, self.settings.analytics_view_burst],
            )
        )

    async def acquire(self, owner):
        keys = []
        for master in self.settings.masters:
            prefix = self.prefixes[master.key_id]
            keys.extend(prefix + suffix for suffix in (":window", ":inflight", ":bucket"))
        selected = int(
            await self._master(
                keys=keys,
                args=[
                    MASTER_REQUESTS_PER_MINUTE,
                    MASTER_TOKENS_PER_SECOND,
                    MAX_CONTEXT_TOKENS,
                    self.settings.master_max_inflight,
                    self.settings.request_timeout + 10,
                    owner,
                ],
            )
        )
        return self.settings.masters[selected - 1] if selected else None

    async def release(self, master, owner):
        await self.redis.zrem(self.prefixes[master.key_id] + ":inflight", owner)

    async def cooldown(self, master, seconds):
        if not math.isfinite(seconds):
            seconds = 1
        await self._cooldown(
            keys=[self.prefixes[master.key_id] + ":bucket"],
            args=[max(1, min(120, math.ceil(seconds)))],
        )
