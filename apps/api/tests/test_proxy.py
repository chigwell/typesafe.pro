import asyncio
import gzip
from contextlib import asynccontextmanager

import httpx
import pytest
from starlette.requests import ClientDisconnect

from proxy.config import MAX_BODY_BYTES, Settings
from proxy.main import create_app
from proxy.transport import ProxyResponse, upstream_request

ENV = {
    "TYPESAFE_TEST_API_TOKEN_1": "client-one",
    "TYPESAFE_MASTER_API_TOKEN_1": "master-one",
    "TYPESAFE_TEST_API_TOKEN_2": "client-two",
    "TYPESAFE_MASTER_API_TOKEN_2": "master-two",
    "RELEASE_SHA": "test-release",
}
AUTH = {"Authorization": "Bearer client-one"}


def response(status=200, body=b"ok", headers=None):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers)


@asynccontextmanager
async def client_for(handler, *, env=None, clock=lambda: 0):
    app = create_app(Settings.from_env(ENV | (env or {})), httpx.MockTransport(handler), clock)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://api.typesafe.pro"
        ) as client:
            yield client


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Basic client-one"},
        {"Authorization": "Bearer master-one"},
        {"Authorization": "Bearer client-one,wrong"},
        [("Authorization", "Bearer client-one"), ("Authorization", "Bearer client-one")],
    ],
)
async def test_invalid_auth_never_calls_upstream(headers):
    def handler(request):
        pytest.fail("Unauthorized request reached upstream")

    async with client_for(handler) as client:
        result = await client.post("/v1/systemone", headers=headers, content=b"not json")
    assert result.status_code == 401
    assert result.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE", "OPTIONS", "CUSTOM"])
async def test_transparent_request_and_multiple_tokens(method):
    seen = []

    def handler(request):
        seen.append(request)
        return response(422, b'{ "upstream": "validation" }', [("X-Trace", "a"), ("X-Trace", "b")])

    body = b'  {"raw": "unchanged"}\n'
    async with client_for(handler) as client:
        for token in ("client-one", "client-two"):
            result = await client.request(
                method,
                "/v1/%73ystemone?x=one&x=two&encoded=%2F+%20",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                content=body,
            )
            assert result.status_code == 422
            assert result.content == b'{ "upstream": "validation" }'
            assert result.headers.get_list("x-trace") == ["a", "b"]
    for index, req in enumerate(seen):
        assert req.method == method
        assert req.url.host == "api.typesafe.ai"
        assert req.url.raw_path == b"/v1/%73ystemone?x=one&x=two&encoded=%2F+%20"
        assert req.headers["host"] == "api.typesafe.ai"
        assert req.headers["authorization"] == f"Bearer master-{'one' if index == 0 else 'two'}"
        assert req.content == body
        assert req.extensions["timeout"] == {"connect": 5, "read": 60, "write": 60, "pool": 5}


async def test_health_bypasses_auth_and_upstream_but_other_paths_do_not():
    def handler(request):
        pytest.fail("Health request reached upstream")

    async with client_for(handler) as client:
        result = await client.get("/health")
        assert result.json() == {"ok": True, "service": "typesafe-proxy", "release": "test-release"}
        assert result.headers["cache-control"] == "no-store"
        for path in ("/", "/docs", "/openapi.json", "/health/"):
            assert (await client.get(path)).status_code == 401
        assert (await client.post("/health")).status_code == 401


async def test_limiter_concurrency_refill_and_key_isolation():
    now = [0.0]
    calls = []

    async def handler(request):
        await asyncio.sleep(0)
        calls.append(request)
        return response()

    async with client_for(handler, clock=lambda: now[0]) as client:
        results = await asyncio.gather(
            *[client.get("/v1/systemone", headers=AUTH) for _ in range(11)]
        )
        assert sum(r.status_code == 200 for r in results) == 10
        denied = next(r for r in results if r.status_code == 429)
        assert denied.headers["retry-after"] == "1"
        assert len(calls) == 10
        assert (
            await client.get("/v1/systemone", headers={"Authorization": "Bearer client-two"})
        ).status_code == 200
        now[0] = 0.9
        assert (await client.get("/v1/systemone", headers=AUTH)).status_code == 429
        now[0] = 1.0
        assert (await client.get("/v1/systemone", headers=AUTH)).status_code == 200
        assert (await client.get("/v1/systemone", headers=AUTH)).status_code == 429
        now[0] = 100.0
        results = [await client.get("/v1/systemone", headers=AUTH) for _ in range(11)]
        assert [r.status_code for r in results] == [200] * 10 + [429]


async def test_strip_hop_headers_keep_duplicates_and_never_reuse_cookies():
    seen = []

    def handler(request):
        seen.append(request)
        return response(
            headers=[
                ("Connection", "X-Private"),
                ("X-Private", "hidden"),
                ("Set-Cookie", "session=first; Path=/"),
                ("Set-Cookie", "other=second; Path=/"),
                ("Keep-Alive", "timeout=5"),
                ("X-Trace", "safe"),
            ]
        )

    async with client_for(handler) as client:
        result = await client.get(
            "/test", headers=AUTH | {"Connection": "X-Private", "X-Private": "secret"}
        )
        assert len(result.headers.get_list("set-cookie")) == 2
        assert result.headers["x-trace"] == "safe"
        assert "connection" not in result.headers and "x-private" not in result.headers
        client.cookies.clear()
        await client.get("/test", headers={"Authorization": "Bearer client-two"})
    assert "x-private" not in seen[0].headers
    assert "connection" not in seen[0].headers
    assert "cookie" not in seen[1].headers


async def test_compressed_bytes_are_not_decoded_in_proxy():
    compressed = gzip.compress(b"unchanged bytes" * 100)
    async with client_for(
        lambda req: response(
            headers={"Content-Encoding": "gzip", "Content-Length": str(len(compressed))},
            body=compressed,
        )
    ) as client:
        async with client.stream("GET", "/test", headers=AUTH) as result:
            raw = b"".join([chunk async for chunk in result.aiter_raw()])
            assert raw == compressed
            assert result.headers["content-length"] == str(len(compressed))
            assert result.headers["content-encoding"] == "gzip"


@pytest.mark.parametrize(
    "error,status",
    [(httpx.ConnectError, 502), (httpx.ReadTimeout, 504), (httpx.ConnectTimeout, 504)],
)
async def test_network_failures_do_not_expose_details_or_retry(error, status, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        raise error("sensitive-upstream-detail", request=request)

    async with client_for(handler) as client:
        result = await client.post("/v1/systemone?secret=hidden", headers=AUTH)
    assert result.status_code == status
    assert len(calls) == 1
    assert "sensitive" not in result.text
    assert "hidden" not in caplog.text and "master-one" not in caplog.text


async def test_redirect_returned_without_following():
    seen = []

    def handler(request):
        seen.append(request)
        return response(307, headers={"Location": "https://other.example/"})

    async with client_for(handler) as client:
        result = await client.post("/test", headers=AUTH)
    assert result.status_code == 307 and result.headers["location"] == "https://other.example/"
    assert len(seen) == 1


@pytest.mark.parametrize(
    "path",
    [b"//evil.example/steal", b"/https://evil.example/", b"/%2f%2fevil.example/", b"/v1/a%2Fb"],
)
def test_upstream_authority_is_fixed(path):
    req = upstream_request(
        {
            "raw_path": path,
            "query_string": b"url=https://evil.example",
            "headers": [(b"host", b"evil.example")],
            "method": "POST",
        },
        b"{}",
        b"master",
    )
    assert req.url.host == "api.typesafe.ai" and req.url.scheme == "https"
    assert req.url.raw_path == path + b"?url=https://evil.example"


async def test_body_limit_prevents_upstream_call():
    def handler(request):
        pytest.fail("Oversize body reached upstream")

    async with client_for(handler) as client:
        result = await client.post("/test", headers=AUTH, content=b"x" * (MAX_BODY_BYTES + 1))
    assert result.status_code == 413


class TrackedStream(httpx.AsyncByteStream):
    closed = False

    async def __aiter__(self):
        yield b"first"
        yield b"second"

    async def aclose(self):
        self.closed = True


async def test_stream_closes_upstream_on_client_disconnect():
    stream = TrackedStream()
    result = ProxyResponse(httpx.Response(200, stream=stream))

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("disconnected")

    with pytest.raises(ClientDisconnect):
        await result({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert stream.closed


@pytest.mark.parametrize(
    "changes",
    [
        {"TYPESAFE_MASTER_API_TOKEN_1": ""},
        {"TYPESAFE_TEST_API_TOKEN_2": "client-one"},
        {"TYPESAFE_MASTER_API_TOKEN_1": "client-one"},
        {"TYPESAFE_TEST_API_TOKEN_3": "orphan"},
        {"TYPESAFE_TEST_API_TOKEN_bad": "bad"},
        {"TYPESAFE_TEST_API_TOKEN_1": "line\nbreak"},
        {"RATE_LIMIT_PER_MINUTE": "0"},
        {"RATE_LIMIT_BURST": "NaN"},
    ],
)
def test_invalid_configuration_fails_closed_without_secret_values(changes):
    with pytest.raises(ValueError) as error:
        Settings.from_env(ENV | changes)
    assert "client-one" not in str(error.value) and "master-one" not in str(error.value)


def test_empty_configuration_rejected_and_repr_redacted():
    with pytest.raises(ValueError):
        Settings.from_env({})
    assert "client-one" not in repr(Settings.from_env(ENV))
    assert "master-one" not in repr(Settings.from_env(ENV))
