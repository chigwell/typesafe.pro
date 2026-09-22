import asyncio
import gzip
import json

import httpx
import pytest
from conftest import ENV, VALID_REQUEST
from starlette.requests import ClientDisconnect

from proxy.config import MAX_BODY_BYTES, Settings
from proxy.transport import ProxyResponse, upstream_request

AUTH = {"Authorization": "Bearer client-one"}


def response(status=200, body=b"ok", headers=None):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers)


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
async def test_invalid_auth_is_anonymous(headers, client_for, store):
    def handler(request):
        assert request.headers["authorization"].startswith("Bearer master-")
        return response(422, b"invalid request")

    async with client_for(handler) as client:
        result = await client.post("/v1/systemone", headers=headers, json=VALID_REQUEST)
    assert result.status_code == 422
    event = await store.pool.fetchrow("SELECT * FROM proxy_error_events")
    assert event["client_tier"] == "anonymous"
    assert event["ip_hash"] == event["client_hash"]


async def test_transparent_request_and_multiple_tokens(client_for):
    method = "POST"
    seen = []

    def handler(request):
        seen.append(request)
        return response(422, b'{ "upstream": "validation" }', [("X-Trace", "a"), ("X-Trace", "b")])

    body = b"  " + json.dumps(VALID_REQUEST | {"raw": "unchanged"}).encode() + b"\n"
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


async def test_health_bypasses_admission(client_for):
    calls = []

    def handler(request):
        calls.append(request)
        return response()

    async with client_for(handler) as client:
        result = await client.get("/health")
        assert result.json() == {"ok": True, "service": "typesafe-proxy", "release": "test-release"}
        assert result.headers["cache-control"] == "no-store"
        assert result.headers["access-control-allow-origin"] == "*"
        assert result.headers["access-control-expose-headers"] == "X-Request-ID, Retry-After"
        assert result.headers["x-request-id"]
        assert not calls
        for path in ("/", "/docs", "/openapi.json", "/health/"):
            assert (await client.get(path)).status_code == 404
        assert (await client.post("/health")).status_code == 405
        assert not calls


async def test_cors_preflight_bypasses_upstream_and_admission(client_for):
    calls = []

    def handler(request):
        calls.append(request)
        return response()

    async with client_for(handler) as client:
        result = await client.options(
            "/v1/systemone",
            headers={
                "Origin": "https://typesafe.pro",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )
    assert result.status_code == 204
    assert result.headers["access-control-allow-origin"] == "*"
    assert "POST" in result.headers["access-control-allow-methods"]
    assert "Authorization" in result.headers["access-control-allow-headers"]
    assert result.headers["access-control-expose-headers"] == "X-Request-ID, Retry-After"
    assert result.headers["x-request-id"]
    assert not calls


async def test_limiter_concurrency_and_key_isolation(client_for):
    calls = []

    async def handler(request):
        await asyncio.sleep(0)
        calls.append(request)
        return response()

    async with client_for(handler) as client:
        results = await asyncio.gather(
            *[client.post("/v1/systemone", json=VALID_REQUEST, headers=AUTH) for _ in range(11)]
        )
        assert sum(r.status_code == 200 for r in results) == 10
        denied = next(r for r in results if r.status_code == 429)
        assert denied.headers["retry-after"] == "1"
        assert len(calls) == 10
        assert (
            await client.post(
                "/v1/systemone", json=VALID_REQUEST, headers={"Authorization": "Bearer client-two"}
            )
        ).status_code == 200


async def test_strip_hop_headers_keep_duplicates_and_never_reuse_cookies(client_for):
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
        result = await client.post(
            "/v1/systemone",
            json=VALID_REQUEST,
            headers=AUTH | {"Connection": "X-Private", "X-Private": "secret"},
        )
        assert len(result.headers.get_list("set-cookie")) == 2
        assert result.headers["x-trace"] == "safe"
        assert "connection" not in result.headers and "x-private" not in result.headers
        client.cookies.clear()
        await client.post(
            "/v1/systemone", json=VALID_REQUEST, headers={"Authorization": "Bearer client-two"}
        )
    assert "x-private" not in seen[0].headers
    assert "connection" not in seen[0].headers
    assert "cookie" not in seen[1].headers


async def test_compressed_bytes_are_not_decoded_in_proxy(client_for):
    compressed = gzip.compress(b"unchanged bytes" * 100)
    async with client_for(
        lambda req: response(
            headers={"Content-Encoding": "gzip", "Content-Length": str(len(compressed))},
            body=compressed,
        )
    ) as client:
        async with client.stream(
            "POST", "/v1/systemone", json=VALID_REQUEST, headers=AUTH
        ) as result:
            raw = b"".join([chunk async for chunk in result.aiter_raw()])
            assert raw == compressed
            assert result.headers["content-length"] == str(len(compressed))
            assert result.headers["content-encoding"] == "gzip"


@pytest.mark.parametrize(
    "error,status",
    [(httpx.ConnectError, 502), (httpx.ReadTimeout, 504), (httpx.ConnectTimeout, 504)],
)
async def test_network_failures_do_not_expose_details_or_retry(error, status, caplog, client_for):
    calls = []

    def handler(request):
        calls.append(request)
        raise error("sensitive-upstream-detail", request=request)

    async with client_for(handler) as client:
        result = await client.post("/v1/systemone?secret=hidden", json=VALID_REQUEST, headers=AUTH)
    assert result.status_code == status
    assert len(calls) == 1
    assert "sensitive" not in result.text
    assert "hidden" not in caplog.text and "master-one" not in caplog.text


async def test_redirect_returned_without_following(client_for):
    seen = []

    def handler(request):
        seen.append(request)
        return response(307, headers={"Location": "https://other.example/"})

    async with client_for(handler) as client:
        result = await client.post("/v1/systemone", json=VALID_REQUEST, headers=AUTH)
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


async def test_body_limit_prevents_upstream_call(client_for):
    def handler(request):
        pytest.fail("Oversize body reached upstream")

    async with client_for(handler) as client:
        result = await client.post(
            "/v1/systemone",
            headers=AUTH | {"Content-Type": "application/json"},
            content=b"x" * (MAX_BODY_BYTES + 1),
        )
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
        {"TYPESAFE_ADMIN_API_TOKEN_1": ""},
        {"TYPESAFE_ADMIN_API_TOKEN_bad": "bad"},
        {"TYPESAFE_TEST_API_TOKEN_1": "line\nbreak"},
        {"MAX_PENDING_REQUESTS": "0"},
        {"MAX_INFLIGHT_REQUESTS": "NaN"},
        {"TOKEN_HASH_SECRET": "short"},
        {"TYPESAFE_MASTER_API_TOKEN_2": "master-one"},
        {"TYPESAFE_ADMIN_API_TOKEN_1": "master-one"},
        {"TYPESAFE_ADMIN_API_TOKEN_2": "admin-one"},
    ],
)
def test_invalid_configuration_fails_closed_without_secret_values(changes):
    with pytest.raises(ValueError) as error:
        Settings.from_env(ENV | changes)
    assert all(
        secret not in str(error.value) for secret in ("client-one", "master-one", "admin-one")
    )


def test_empty_configuration_rejected_and_repr_redacted():
    with pytest.raises(ValueError):
        Settings.from_env({})
    assert "client-one" not in repr(Settings.from_env(ENV))
    assert "master-one" not in repr(Settings.from_env(ENV))
    assert "admin-one" not in repr(Settings.from_env(ENV))
