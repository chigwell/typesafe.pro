"""Characterizations captured before the gateway/cache extraction passes.

These exercise HTTP and resource ownership independently of the module layout.
The schema fixtures describe the supported contract, not implementation symbols.
"""

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from conftest import ENV, VALID_REQUEST
from starlette.datastructures import State
from starlette.requests import Request

from proxy import content_api, content_cache, content_store
from proxy.config import Settings
from proxy.content_store import ResponseCache, cached
from proxy.main import create_app
from proxy.scheduler import BodyBudget
from proxy.use_case_schema import Page

FIXTURES = Path(__file__).parent / "fixtures"


def test_page_schema_matches_pre_refactor_contract():
    assert Page.model_json_schema() == json.loads((FIXTURES / "page_schema.json").read_text())


def test_public_openapi_matches_pre_refactor_contract():
    assert create_app().openapi() == json.loads((FIXTURES / "public_openapi.json").read_text())


@pytest.mark.parametrize(
    "method,path,body,media,status,expected,allow",
    [
        (
            "GET",
            "/v1/systemone",
            b"",
            "application/json",
            405,
            b'{"error": "method_not_allowed"}',
            "POST, OPTIONS",
        ),
        (
            "POST",
            "/missing",
            b"{}",
            "application/json",
            404,
            b'{"error": "endpoint_not_found"}',
            None,
        ),
        (
            "POST",
            "/v1/systemone",
            b"{}",
            "text/plain",
            415,
            b'{"error": "unsupported_media_type"}',
            None,
        ),
        (
            "POST",
            "/v1/systemone",
            b"{",
            "application/json",
            400,
            b'{"error": "invalid_json"}',
            None,
        ),
        (
            "POST",
            "/v1/systemone",
            b"{}",
            "application/json",
            422,
            b'{"error": "invalid_request", "details": {"path": ["model"], '
            b'"reason": "Expected a string"}}',
            None,
        ),
    ],
)
async def test_gateway_rejection_bytes_headers_and_resource_cleanup(
    client_for, method, path, body, media, status, expected, allow
):
    async with client_for(lambda _: pytest.fail("Rejected request reached upstream")) as client:
        result = await client.request(
            method,
            path,
            content=body,
            headers={"Content-Type": media, "X-Request-ID": "parity-rejection"},
        )
        assert result.status_code == status
        assert result.content == expected
        assert result.headers["content-type"] == "application/json"
        assert result.headers["content-length"] == str(len(expected))
        assert result.headers["cache-control"] == "no-store"
        assert result.headers["x-request-id"] == "parity-rejection"
        assert result.headers["access-control-allow-origin"] == "*"
        assert result.headers["access-control-expose-headers"] == "X-Request-ID, Retry-After"
        assert result.headers.get("allow") == allow
        assert "retry-after" not in result.headers
        assert client.app.state.budget.requests == client.app.state.budget.bytes == 0
        assert client.app.state.scheduler.inflight == 0


def test_response_cache_deadline_capacity_and_invalidation(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(content_store.time, "monotonic", lambda: now[0])
    cache = ResponseCache(ttl=10, limit=2)
    cache.put("first", b"first bytes")
    assert cache.get("first") == b"first bytes"
    now[0] = 109.999
    assert cache.get("first") == b"first bytes"
    now[0] = 110
    assert cache.get("first") is None  # Exact expiry is a miss; stale items remain bounded.
    assert len(cache.items) == 1
    cache.put("second", b"second bytes")
    cache.put("third", b"third bytes")
    assert cache.get("first") is None and cache.get("second") is None
    assert cache.get("third") == b"third bytes" and len(cache.items) == 1
    cache.put("second", b"second bytes")
    cache.put("second", b"replacement")  # Capacity clears even when overwriting a key.
    assert cache.get("third") is None and cache.get("second") == b"replacement"
    cache.invalidate()
    assert cache.version == 1 and cache.items == {} and cache.get("second") is None


async def test_cached_serialization_preserves_unicode_and_producer_calls():
    state = SimpleNamespace(content_cache=ResponseCache())
    calls = []

    async def producer():
        calls.append("produce")
        return {"colour": "café", "nested": [True, None, 1]}

    expected = b'{"colour":"caf\xc3\xa9","nested":[true,null,1]}'
    assert await cached(state, "key", producer) == expected
    assert await cached(state, "key", producer) == expected
    assert calls == ["produce"]
    state.content_cache.invalidate()
    assert await cached(state, "key", producer) == expected
    assert calls == ["produce", "produce"]


async def test_cache_lookup_after_limiter_preserves_concurrent_fill(monkeypatch):
    state = SimpleNamespace(content_cache=ResponseCache())
    request = Request({"type": "http", "headers": [], "app": SimpleNamespace(state=state)})
    expected = b'{"items":[],"total":0,"page":1,"page_size":24}'
    calls = []

    async def limiter(_request):
        calls.append("limit")
        # Another request may fill the cache during the awaited limiter call.
        state.content_cache.put("listing", expected)

    async def producer():
        pytest.fail("The cache must be checked again after awaiting the limiter")

    monkeypatch.setattr(content_api, "read_limit", limiter)
    result = await content_api.serve(request, "listing", producer)
    assert result.body == expected and result.status_code == 200
    assert result.headers["etag"] == '"' + hashlib.sha256(expected).hexdigest()[:32] + '"'
    assert result.headers["cache-control"] == content_api.PUBLIC_CACHE
    assert result.headers["vary"] == "Accept-Encoding"
    assert calls == ["limit"]
    assert (await content_api.serve(request, "listing", producer)).body == expected
    assert calls == ["limit"]  # A cached hit never spends the read budget.


def request_scope():
    return {
        "type": "http",
        "asgi": {"spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "https",
        "method": "POST",
        "path": "/v1/systemone",
        "raw_path": b"/v1/systemone",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("203.0.113.10", 123),
        "server": ("api.typesafe.pro", 443),
    }


@pytest.mark.parametrize("cancel", [False, True])
async def test_upload_disconnect_or_cancellation_releases_body_budget(store, redis, cancel):
    app = create_app(
        Settings.from_env(ENV),
        httpx.MockTransport(lambda _: pytest.fail("Incomplete upload reached upstream")),
        store=store,
        redis=redis,
    )
    uploaded = asyncio.Event()
    incoming = asyncio.Queue()
    part = b'{"model": "jev-latest",'
    sent = []
    await incoming.put({"type": "http.request", "body": part, "more_body": True})

    async def receive():
        if incoming.empty():
            uploaded.set()
        return await incoming.get()

    async def send(message):
        sent.append(message)

    async with app.router.lifespan_context(app):
        task = asyncio.create_task(app(request_scope(), receive, send))
        await asyncio.wait_for(uploaded.wait(), 2)
        assert app.state.budget.requests == 1 and app.state.budget.bytes == 2 * len(part)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await incoming.put({"type": "http.disconnect"})
            await asyncio.wait_for(task, 1)
        assert sent == []
        assert app.state.budget.requests == app.state.budget.bytes == 0
        assert app.state.scheduler.inflight == 0
    event = await store.pool.fetchrow("SELECT * FROM proxy_error_events")
    assert event["error_code"] == "client_disconnected" and event["status"] == 499
    assert event["request_bytes"] == len(part)


async def test_disconnect_during_stream_releases_upstream_lease_and_body(store, redis):
    first_chunk = asyncio.Event()

    class WaitingStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"first bytes"
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    stream = WaitingStream()
    app = create_app(
        Settings.from_env(ENV),
        httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
        store=store,
        redis=redis,
    )
    incoming = asyncio.Queue()
    await incoming.put(
        {"type": "http.request", "body": json.dumps(VALID_REQUEST).encode(), "more_body": False}
    )
    sent = []

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body":
            first_chunk.set()

    async with app.router.lifespan_context(app):
        task = asyncio.create_task(app(request_scope(), incoming.get, send))
        await asyncio.wait_for(first_chunk.wait(), 2)
        assert app.state.scheduler.inflight == 1
        await incoming.put({"type": "http.disconnect"})
        await asyncio.wait_for(task, 1)
        assert [message["type"] for message in sent] == [
            "http.response.start",
            "http.response.body",
        ]
        assert sent[0]["status"] == 200 and sent[1]["body"] == b"first bytes"
        assert stream.closed
        assert app.state.budget.requests == app.state.budget.bytes == 0
        assert app.state.scheduler.inflight == 0
        for prefix in app.state.limiter.prefixes.values():
            assert await redis.zcard(prefix + ":inflight") == 0
    event = await store.pool.fetchrow("SELECT * FROM proxy_error_events")
    assert event["error_code"] == "client_disconnected" and event["status"] == 499
    assert event["raw_response"] == "first bytes"


async def test_gateway_reads_replaced_application_state_per_request(client_for, monkeypatch):
    async with client_for(lambda _: httpx.Response(200, stream=httpx.ByteStream(b"ok"))) as client:
        previous = client.app.state
        replacement = State(dict(previous._state))
        replacement.budget = BodyBudget(previous.settings)
        client.app.state = replacement

        def stale_budget():
            pytest.fail("The endpoint retained stale application state")

        monkeypatch.setattr(previous.budget, "enter", stale_budget)
        result = await client.post("/v1/systemone", json=VALID_REQUEST)
        assert result.status_code == 200 and result.content == b"ok"
        assert replacement.budget.requests == replacement.budget.bytes == 0


def test_content_cache_legacy_imports_remain_compatible():
    assert content_store.ResponseCache is content_cache.ResponseCache
    assert content_store.cached is content_cache.cached
    assert content_store.new_state is content_cache.new_state
    state = SimpleNamespace()
    content_store.new_state(state)
    assert isinstance(state.content_cache, ResponseCache)
    assert state.content_cache.ttl == 60 and state.content_cache.limit == 2000
