import asyncio
import gzip
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

import httpx
import pytest
from conftest import ENV
from redis.exceptions import ConnectionError as RedisConnectionError

from proxy.auth import Identity, authenticate, client_ip, digest
from proxy.config import DEFAULT_POLICIES, MAX_CONTEXT_TOKENS, RETENTION_SECONDS, Settings
from proxy.limiter import Limiter
from proxy.main import create_app, retry_seconds
from proxy.payload import inspect_response, usage_tokens, valid_response
from proxy.scheduler import BodyBudget, Rejected, Scheduler
from proxy.telemetry import Telemetry, new_event, sanitize


def scope(headers=(), peer="203.0.113.10"):
    return {
        "type": "http",
        "asgi": {"spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "http",
        "method": "POST",
        "path": "/v1/systemone",
        "raw_path": b"/v1/systemone",
        "query_string": b"",
        "headers": list(headers),
        "client": (peer, 123),
        "server": ("api.typesafe.pro", 80),
    }


@pytest.mark.parametrize("tier", ["free", "paid"])
async def test_database_token_hash_lookup_cache_expiry_and_revocation(tier, store, redis):
    settings = Settings.from_env(ENV)
    hashed = digest(settings.hash_secret, b"db-token")
    await store.pool.execute(
        "INSERT INTO api_client_tokens (token_hash,tier) VALUES ($1,$2)",
        hashed,
        tier,
    )
    request = scope([(b"authorization", b"Bearer db-token")])
    identity = await authenticate(request, settings, store, redis)
    assert identity.tier == tier and identity.client_hash == hashed
    assert await redis.ttl("ts:auth:" + hashed) in range(1, 31)
    await store.pool.execute("UPDATE api_client_tokens SET revoked_at=now()")
    await redis.delete("ts:auth:" + hashed)
    assert (await authenticate(request, settings, store, redis)).tier == "anonymous"
    await store.pool.execute(
        "UPDATE api_client_tokens SET revoked_at=NULL,expires_at=now()-interval '1 second'"
    )
    assert (await authenticate(request, settings, store, redis)).tier == "anonymous"
    assert await redis.get("ts:auth:" + hashed) is None


@pytest.mark.parametrize(
    "headers,peer,expected",
    [
        (
            [(b"cf-connecting-ip", b"1.1.1.1"), (b"x-real-ip", b"2.2.2.2")],
            "203.0.113.10",
            "203.0.113.10",
        ),
        ([(b"cf-connecting-ip", b"1.1.1.1")], "127.0.0.1", "127.0.0.1"),
        ([(b"x-real-ip", b"2001:db8::1")], "127.0.0.1", "2001:db8::1"),
        ([(b"x-forwarded-for", b"192.0.2.1")], "127.0.0.1", "192.0.2.1"),
        ([(b"x-forwarded-for", b"192.0.2.1, 192.0.2.2")], "127.0.0.1", "127.0.0.1"),
        ([(b"x-real-ip", b"bad")], "127.0.0.1", "127.0.0.1"),
        ([(b"x-real-ip", b"1.1.1.1"), (b"x-real-ip", b"2.2.2.2")], "127.0.0.1", "127.0.0.1"),
    ],
)
def test_only_trusted_proxy_normalized_ip(headers, peer, expected):
    assert client_ip(scope(headers, peer), (ip_network("127.0.0.1/32"),)) == expected


async def test_atomic_client_limits_refill_and_isolation(redis):
    limiter = Limiter(redis, Settings.from_env(ENV))
    policy = DEFAULT_POLICIES["anonymous"]
    identity = Identity("anonymous", "a", "a")
    results = await asyncio.gather(*[limiter.client_retry(identity, policy) for _ in range(20)])
    assert results.count(0) == policy.burst
    assert max(results) == 2
    assert await limiter.client_retry(Identity("anonymous", "b", "b"), policy) == 0
    await redis.hset("ts:client:anonymous:a", "updated", "0")
    assert await limiter.client_retry(identity, policy) == 0
    assert 0 < await redis.ttl("ts:client:anonymous:a") <= 70


async def test_atomic_multimaster_capacity_and_rolling_windows(redis):
    settings = Settings.from_env(ENV)
    limiter = Limiter(redis, settings)
    selected = await asyncio.gather(*[limiter.acquire(str(n)) for n in range(20)])
    # 3 * 64k per key in any second, including under concurrent reservation.
    assert sum(key is not None for key in selected) == 6
    assert sorted(key.key_id for key in selected if key) == ["1"] * 3 + ["2"] * 3
    for n, master in enumerate(selected):
        if master:
            await limiter.release(master, str(n))
    assert await limiter.acquire("still-no-tokens") is None
    seconds, micros = await redis.time()
    now = seconds + micros / 1e6
    for prefix in limiter.prefixes.values():
        # Fill the rolling minute without consuming the current second.
        await redis.delete(prefix + ":window", prefix + ":bucket")
        await redis.zadd(prefix + ":window", {f"r{n}": now - 2 for n in range(1200)})
    assert await limiter.acquire("rpm-exhausted") is None


async def test_least_loaded_inflight_release_and_cooldown(redis):
    settings = replace(Settings.from_env(ENV), master_max_inflight=1)
    limiter = Limiter(redis, settings)
    first = await limiter.acquire("one")
    second = await limiter.acquire("two")
    assert first.key_id != second.key_id
    assert await limiter.acquire("three") is None
    await limiter.release(first, "one")
    await limiter.cooldown(first, 10)
    assert await limiter.acquire("blocked") is None
    await limiter.release(second, "two")
    assert (await limiter.acquire("four")).key_id == second.key_id


async def test_strict_priority_queue_timeout_cancel_and_capacity(redis):
    settings = replace(Settings.from_env(ENV), max_inflight=1)
    scheduler = Scheduler(Limiter(redis, settings), settings)
    # Enqueue before starting the dispatcher to make priority order deterministic.
    anon = asyncio.create_task(scheduler.acquire(DEFAULT_POLICIES["anonymous"]))
    free = asyncio.create_task(scheduler.acquire(DEFAULT_POLICIES["free"]))
    paid = asyncio.create_task(scheduler.acquire(DEFAULT_POLICIES["paid"]))
    await asyncio.sleep(0)
    await scheduler.start()
    try:
        result = await asyncio.wait_for(paid, 1)
        assert not free.done() and not anon.done()
        await scheduler.release(*result)
        result = await asyncio.wait_for(free, 1)
        assert not anon.done()
        anon.cancel()
        with pytest.raises(asyncio.CancelledError):
            await anon
        assert not scheduler.queues["anonymous"]
        short = replace(DEFAULT_POLICIES["paid"], queue_wait=0.02)
        with pytest.raises(Rejected, match="queue_timeout"):
            await scheduler.acquire(short)
        assert not scheduler.queues["paid"]
        await scheduler.release(*result)
        assert scheduler.inflight == 0
    finally:
        await scheduler.close()


def test_body_budget_includes_uploads_and_copy_and_recovers():
    settings = replace(Settings.from_env(ENV), queue_memory_bytes=20, max_pending=2)
    budget = BodyBudget(settings)
    budget.enter()
    budget.grow(9)
    budget.enter()
    with pytest.raises(Rejected, match="queue_full"):
        budget.enter()
    with pytest.raises(Rejected, match="queue_full"):
        budget.grow(2)
    budget.leave(0)
    budget.leave(9)
    assert budget.requests == budget.bytes == 0


async def test_disconnect_removes_pending_and_releases_memory(store, redis, monkeypatch):
    settings = Settings.from_env(ENV)
    app = create_app(
        settings,
        httpx.MockTransport(lambda req: pytest.fail("Disconnected request sent")),
        store=store,
        redis=redis,
    )
    incoming = asyncio.Queue()
    await incoming.put({"type": "http.request", "body": b"{}", "more_body": False})
    sent = []

    async def send(message):
        sent.append(message)

    async with app.router.lifespan_context(app):
        for master in settings.masters:
            await app.state.limiter.cooldown(master, 10)
        queued = asyncio.Event()
        original = app.state.limiter.acquire

        async def observed_acquire(owner):
            queued.set()
            return await original(owner)

        monkeypatch.setattr(app.state.limiter, "acquire", observed_acquire)
        task = asyncio.create_task(app(scope(), incoming.get, send))
        await asyncio.wait_for(queued.wait(), 2)
        await incoming.put({"type": "http.disconnect"})
        await asyncio.wait_for(task, 1)
        assert not sent
        assert not app.state.scheduler.queues["anonymous"]
        assert app.state.budget.bytes == app.state.budget.requests == 0
        assert app.state.scheduler.inflight == 0
    assert (
        await store.pool.fetchval("SELECT error_code FROM proxy_error_events")
        == "client_disconnected"
    )


async def test_queue_timeout_response_and_redis_failure(client_for, monkeypatch, store):
    await store.pool.execute("UPDATE rate_limit_policies SET queue_wait_seconds=0.03")
    async with client_for(lambda req: pytest.fail("Must not reach upstream")) as client:
        for master in client.app.state.settings.masters:
            await client.app.state.limiter.cooldown(master, 10)
        result = await client.get("/test")
        assert result.status_code == 429 and result.json()["error"] == "queue_timeout"
        assert result.headers["retry-after"] == "1"

        async def unavailable(*args):
            raise RedisConnectionError("private backend detail")

        monkeypatch.setattr(client.app.state.limiter, "client_retry", unavailable)
        result = await client.get("/test")
        assert result.status_code == 503 and result.json()["error"] == "limiter_unavailable"
        assert result.headers["x-request-id"]


async def test_logs_raw_errors_redacts_secrets_and_counters(client_for, store, redis):
    raw = b'{"error":"Bearer client-one master-one hidden-value", "detail":"invalid state"}'
    async with client_for(lambda req: httpx.Response(422, stream=httpx.ByteStream(raw))) as client:
        result = await client.post(
            "/v1/systemone?api_key=hidden-value",
            content=b"{}",
            headers={"Authorization": "Bearer client-one", "X-Request-ID": "trace-1"},
        )
        assert result.content == raw and result.headers["x-request-id"] == "trace-1"
    event = await store.pool.fetchrow("SELECT * FROM proxy_error_events")
    assert event["request_id"] == "trace-1"
    assert event["client_tier"] == "free" and event["upstream_status"] == 422
    assert event["upstream_valid"] is False and event["duration_ms"] > 0
    assert event["path"] == "/v1/systemone" and "invalid state" in event["raw_response"]
    for secret in ("master-one", "client-one", "hidden-value"):
        assert secret not in str(dict(event))
    keys = await redis.keys("ts:metrics:*:all")
    assert len(keys) == 1
    counts = await redis.hgetall(keys[0])
    assert counts["requests"] == "1" and counts["status_4xx"] == "1"
    assert 0 < await redis.ttl(keys[0]) <= RETENTION_SECONDS


async def test_response_validation_and_compressed_usage(client_for, store, redis):
    data = {
        "model": "jev",
        "answers": {"x": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 40, "output_tokens": 10},
    }
    raw = json.dumps(data).encode()
    async with client_for(
        lambda req: httpx.Response(
            200, stream=httpx.ByteStream(gzip.compress(raw)), headers={"Content-Encoding": "gzip"}
        )
    ) as client:
        result = await client.post("/v1/systemone", json={"questions": {"x": {}}})
        assert result.json() == data
    assert await store.pool.fetchval("SELECT count(*) FROM proxy_error_events") == 0
    key = (await redis.keys("ts:metrics:*:all"))[0]
    assert await redis.hget(key, "usage_tokens") == "50"
    async with client_for(
        lambda req: httpx.Response(200, stream=httpx.ByteStream(b"not JSON"))
    ) as client:
        result = await client.post("/v1/systemone", content=b"{}")
        assert result.content == b"not JSON"
    assert (
        await store.pool.fetchval("SELECT error_code FROM proxy_error_events")
        == "invalid_upstream_response"
    )


async def test_policies_refresh_and_error_ttl_cleanup(store, redis):
    policies = await store.policies()
    assert policies == DEFAULT_POLICIES
    await store.pool.execute("UPDATE rate_limit_policies SET rpm=42 WHERE tier='anonymous'")
    assert (await store.policies())["anonymous"].rpm == 30
    store._policies_until = 0
    assert (await store.policies())["anonymous"].rpm == 42
    event = new_event(scope(), "old")
    event["created_at"] = datetime.now(UTC) - timedelta(days=8)
    current = new_event(scope(), "current")
    await store.write_errors([event, current])
    assert await store.cleanup() == "DELETE 1"
    assert await store.pool.fetchval("SELECT request_id FROM proxy_error_events") == "current"


def test_capture_is_bounded_and_sanitizes_before_truncating():
    data, raw, _ = inspect_response(gzip.compress(b"x" * 1_000_000), "gzip", False)
    assert data is None and raw is None
    assert "secret" not in sanitize("prefix secret-key", ("secret-key",), limit=10)
    assert "secret" not in sanitize("prefix secret-ke", ("secret-key",))
    assert usage_tokens({"usage": {"input_tokens": True, "output_tokens": -1}}) is None
    assert not valid_response({}, None)
    assert MAX_CONTEXT_TOKENS == 64_000


async def test_telemetry_failure_bounded_fallback(store, redis, monkeypatch, caplog):
    async def unavailable(events):
        raise RuntimeError("private storage detail")

    monkeypatch.setattr(store, "write_errors", unavailable)
    telemetry = Telemetry(store, redis)
    event = new_event(scope(), "fallback")
    event["raw_response"] = "master-one"
    telemetry.error(event, ("master-one",))
    await telemetry.flush()
    assert "error_log_unavailable" in caplog.text
    assert "master-one" not in caplog.text and "private storage detail" not in caplog.text


@pytest.mark.parametrize("value", ["valid-trace_12", "spaces invalid", "a" * 129])
async def test_request_id_validation(client_for, value):
    seen = []

    def handler(request):
        seen.append(request.headers["x-request-id"])
        return httpx.Response(
            200, stream=httpx.ByteStream(b"ok"), headers={"X-Request-ID": "upstream-id"}
        )

    async with client_for(handler) as client:
        response = await client.get("/test", headers={"X-Request-ID": value})
    assert response.headers["x-request-id"] == seen[0]
    assert (seen[0] == value) == (value == "valid-trace_12")


async def test_http_memory_limit_and_queue_size(client_for, redis):
    async with client_for(
        lambda req: pytest.fail("Over-budget request sent"), env={"QUEUE_MEMORY_BYTES": "4"}
    ) as client:
        result = await client.post("/test", content=b"123")
        assert result.status_code == 503 and result.json()["error"] == "queue_full"
        assert client.app.state.budget.bytes == client.app.state.budget.requests == 0
    settings = Settings.from_env(ENV)
    scheduler = Scheduler(Limiter(redis, settings), settings)
    policy = replace(DEFAULT_POLICIES["paid"], queue_size=1)
    pending = asyncio.create_task(scheduler.acquire(policy))
    await asyncio.sleep(0)
    with pytest.raises(Rejected, match="queue_full"):
        await scheduler.acquire(policy)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await scheduler.close()


async def test_interrupted_stream_is_logged_and_releases_lease(client_for, store, redis):
    class BrokenStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"partial response"
            raise httpx.ReadError("master-one private failure")

        async def aclose(self):
            self.closed = True

    stream = BrokenStream()
    async with client_for(lambda req: httpx.Response(200, stream=stream)) as client:
        with pytest.raises(RuntimeError, match="Proxy stream interrupted"):
            await client.get("/test")
        assert client.app.state.scheduler.inflight == 0
        assert client.app.state.budget.requests == 0
        for prefix in client.app.state.limiter.prefixes.values():
            assert await redis.zcard(prefix + ":inflight") == 0
    assert stream.closed
    event = await store.pool.fetchrow("SELECT * FROM proxy_error_events")
    assert event["exception_class"] == "ReadError"
    assert event["status"] == 502 and event["upstream_status"] == 200
    assert event["raw_response"] == "partial response"
    assert "master-one" not in event["error_detail"]


async def test_global_upstream_deadline_releases_slot(client_for):
    async def handler(request):
        await asyncio.Event().wait()

    async with client_for(handler, env={"REQUEST_TIMEOUT_SECONDS": "1"}) as client:
        response = await client.get("/test")
        assert response.status_code == 504
        assert client.app.state.scheduler.inflight == 0


def test_master_only_config_and_retry_after():
    settings = Settings.from_env(
        ENV | {"TYPESAFE_TEST_API_TOKEN_1": "", "TYPESAFE_TEST_API_TOKEN_2": ""}
    )
    assert not settings.legacy_tokens and len(settings.masters) == 2
    assert retry_seconds(httpx.Response(429, headers={"Retry-After": "12"})) == 12
    assert retry_seconds(httpx.Response(401)) == 120
    assert retry_seconds(httpx.Response(429, headers={"Retry-After": "invalid"})) == 1
