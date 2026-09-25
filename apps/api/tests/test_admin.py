import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from conftest import ENV, VALID_REQUEST

from proxy.activity import Activity, buckets
from proxy.admin import COOKIE, session_cookie, valid_session
from proxy.config import RETENTION_SECONDS, Settings
from proxy.system import SystemSampler
from proxy.telemetry import new_event

PASSWORD = ENV["ADMIN_PASSWORD"]
ORIGIN = {"Origin": "https://typesafe.pro"}


def no_upstream(request):
    pytest.fail("Admin request reached upstream")


def test_signed_session_expiry_tampering_and_rotation():
    settings = Settings.from_env(ENV)
    value = session_cookie(settings, now=100)
    assert valid_session(value, settings, now=101)
    assert not valid_session(value, settings, now=100 + settings.admin_session_ttl_seconds)
    assert not valid_session(value + "x", settings, now=101)
    assert not valid_session(value.replace("v1", "v2"), settings, now=101)
    assert not valid_session("v1.999999.nonce.\u00e9", settings, now=101)
    assert not valid_session(value, Settings.from_env(ENV | {"ADMIN_PASSWORD": "x" * 40}), now=101)


@pytest.mark.parametrize(
    "path",
    [
        "auth/session",
        "system",
        "summary",
        "ip-activity",
        "errors",
        "page-views",
        "seo/summary",
        "seo/pages",
        "seo/runs",
    ],
)
async def test_all_data_requires_session(client_for, path):
    async with client_for(no_upstream) as client:
        response = await client.get("/admin/api/" + path, headers=ORIGIN)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["access-control-allow-origin"] == "https://typesafe.pro"
        assert response.headers["access-control-allow-credentials"] == "true"


async def test_login_logout_and_invalid_session(client_for, redis):
    async with client_for(no_upstream) as client:
        bad = await client.post("/admin/api/auth/login", json={"password": "bad"}, headers=ORIGIN)
        assert bad.status_code == 401
        result = await client.post(
            "/admin/api/auth/login", json={"password": PASSWORD}, headers=ORIGIN
        )
        assert result.status_code == 200
        cookie = result.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert "Domain=" not in cookie and "Path=/admin/api" in cookie
        assert not await redis.keys("ts:admin:login:*")
        assert (await client.get("/admin/api/auth/session")).status_code == 200
        client.cookies.set(COOKIE, "tampered", domain="api.typesafe.pro", path="/admin/api")
        assert (await client.get("/admin/api/auth/session")).status_code == 401
        await client.post("/admin/api/auth/login", json={"password": PASSWORD})
        assert (await client.post("/admin/api/auth/logout", headers=ORIGIN)).status_code == 200
        assert (await client.get("/admin/api/auth/session")).status_code == 401


async def test_atomic_lockout_per_real_ip_and_retry(client_for):
    async with client_for(no_upstream, env={"ADMIN_LOGIN_MAX_ATTEMPTS": "3"}) as client:
        headers = ORIGIN | {"X-Real-IP": "203.0.113.1"}
        responses = await asyncio.gather(
            *[
                client.post("/admin/api/auth/login", json={"password": "bad"}, headers=headers)
                for _ in range(8)
            ]
        )
        assert sorted(row.status_code for row in responses) == [401] * 3 + [429] * 5
        blocked = await client.post(
            "/admin/api/auth/login", json={"password": PASSWORD}, headers=headers
        )
        assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
        assert (
            await client.post(
                "/admin/api/auth/login",
                json={"password": PASSWORD},
                headers=ORIGIN | {"X-Real-IP": "203.0.113.2"},
            )
        ).status_code == 200


async def test_untrusted_peer_cannot_rotate_forwarded_ip(client_for):
    async with client_for(no_upstream, env={"ADMIN_LOGIN_MAX_ATTEMPTS": "1"}) as client:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(client.app, client=("203.0.113.10", 1234)),
            base_url="https://api.typesafe.pro",
        ) as attacker:
            for n, expected in ((1, 401), (2, 429)):
                response = await attacker.post(
                    "/admin/api/auth/login",
                    json={"password": "bad"},
                    headers={"X-Real-IP": f"192.0.2.{n}"},
                )
                assert response.status_code == expected


async def test_admin_cors_and_csrf_leave_public_cors_unchanged(client_for):
    async with client_for(no_upstream) as client:
        allowed = await client.options(
            "/admin/api/auth/login",
            headers=ORIGIN
            | {
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert allowed.status_code == 204
        assert allowed.headers["access-control-allow-credentials"] == "true"
        for origin in ("https://attacker.test", "https://evil.typesafe.pro", "null"):
            response = await client.post(
                "/admin/api/auth/login", json={"password": PASSWORD}, headers={"Origin": origin}
            )
            assert response.status_code == 403 and "set-cookie" not in response.headers
            assert "access-control-allow-origin" not in response.headers
        assert (
            await client.post("/admin/api/auth/logout", headers={"Sec-Fetch-Site": "cross-site"})
        ).status_code == 403
        public = await client.options(
            "/v1/systemone",
            headers={"Origin": "https://anywhere.test", "Access-Control-Request-Method": "POST"},
        )
        assert public.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in public.headers
        assert (await client.get("/admin/api/missing")).status_code == 404
        assert (await client.request("CUSTOM", "/admin/api/missing")).status_code == 404


async def test_login_fails_closed_when_limiter_unavailable(client_for, monkeypatch):
    async with client_for(no_upstream) as client:

        async def unavailable(*args, **kwargs):
            raise RuntimeError("private redis credentials")

        monkeypatch.setattr(client.app.state.redis, "eval", unavailable)
        response = await client.post("/admin/api/auth/login", json={"password": PASSWORD})
        assert response.status_code == 503 and "credentials" not in response.text


async def test_malformed_login_never_echoes_password(client_for):
    async with client_for(no_upstream, env={"ADMIN_LOGIN_MAX_ATTEMPTS": "10"}) as client:
        for body, expected in (
            ({"password": [PASSWORD]}, 400),
            ({"password": "\ud800"}, 400),
            ({"password": "a" * 5000}, 413),
        ):
            import json

            result = await client.post("/admin/api/auth/login", content=json.dumps(body))
            assert result.status_code == expected
            assert PASSWORD not in result.text


def event(ip="203.0.113.1", *, ago=0, error=False):
    result = new_event({"method": "POST", "path": "/v1/systemone"}, "test")
    result.update(
        client_ip=ip,
        client_tier="anonymous",
        status=502 if error else 200,
        error_code="upstream_error" if error else "",
        master_key_id="1",
        upstream_status=502 if error else 200,
        duration_ms=30,
        upstream_ms=20,
        estimated_tokens=100,
        usage_tokens=10,
        created_at=datetime.now(UTC) - timedelta(seconds=ago),
    )
    return result


async def test_rolling_aggregates_ip_pages_and_retention(redis):
    activity = Activity(redis, RETENTION_SECONDS)
    for row in (
        event(),
        event(error=True),
        event("2001:db8::1"),
        event("203.0.113.2", ago=7200),
        event("203.0.113.3", ago=RETENTION_SECONDS + 3600),
    ):
        activity.count(row, row["path"])
    await activity.flush()
    summary = await activity.snapshot("5m")
    assert summary["totals"]["requests"] == 3
    assert summary["totals"]["unique_ips"] == 2
    assert summary["totals"]["errors"] == 1
    assert summary["totals"]["avg_upstream_ms"] == 20
    assert summary["totals"]["avg_duration_ms"] == 30
    assert summary["totals"]["usage_tokens"] == 30
    assert summary["status_codes"] == {"200": 2, "502": 1}
    assert summary["upstream_statuses"] == {"200": 2, "502": 1}
    assert summary["tiers"][0]["name"] == "anonymous"
    first = await activity.ip_page("5m", 1, 1)
    second = await activity.ip_page("5m", 2, 1)
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["ip"] == "203.0.113.1"
    assert first["items"][0]["requests"] == 2 and first["items"][0]["errors"] == 1
    assert second["items"][0]["ip"] == "2001:db8::1"
    assert (await activity.snapshot("1h"))["totals"]["requests"] == 3
    for window in ("24h", "7d"):
        assert (await activity.snapshot(window))["totals"]["requests"] == 4
    for key in await redis.keys("ts:obs:60:*"):
        assert 0 < await redis.ttl(key) <= RETENTION_SECONDS


def test_rollup_buckets_are_disjoint_and_bounded():
    start = int(time.time() // 60) * 60 - RETENTION_SECONDS + 60
    end = start + RETENTION_SECONDS - 60
    selected = list(buckets(start, end))
    assert len(selected) <= 168 + 120
    cursor = start
    for key in selected:
        size, value = map(int, key.removeprefix("ts:obs:").split(":"))
        assert value == cursor
        cursor += size
    assert cursor == end + 60


async def test_activity_reserves_redis_headroom(redis, monkeypatch):
    activity = Activity(redis, RETENTION_SECONDS)

    async def memory_pressure(*args):
        return {"maxmemory": 100000, "used_memory": 91000}

    monkeypatch.setattr(redis, "info", memory_pressure)
    activity.count(event(), "/v1/systemone")
    await activity.flush()
    assert activity.dropped == 1
    assert not await redis.keys("ts:obs:*")
    with pytest.raises(RuntimeError, match="headroom"):
        await activity.snapshot("7d")


async def test_error_pages_filter_sanitize_and_real_ip(client_for, store):
    async with client_for(
        lambda request: httpx.Response(
            502, stream=httpx.ByteStream(b"Bearer private-token master-one")
        )
    ) as client:
        for ip in ("203.0.113.5", "2001:db8::2"):
            await client.post("/v1/systemone", json=VALID_REQUEST, headers={"X-Real-IP": ip})
        await client.app.state.telemetry.flush()
        await client.post("/admin/api/auth/login", json={"password": PASSWORD})
        first = (await client.get("/admin/api/errors?page=1&page_size=1&status=502")).json()
        second = (await client.get("/admin/api/errors?page=2&page_size=1&status=502")).json()
        assert first["total"] == 2 and second["total"] == 2
        assert first["items"][0]["id"] != second["items"][0]["id"]
        assert first["items"][0]["client_ip"] == "2001:db8::2"
        assert "private-token" not in str(first) and "master-one" not in str(first)
        assert "[redacted]" in str(first)
        empty = await client.get("/admin/api/errors?error_code=queue_timeout")
        assert empty.json()["total"] == 0
        assert (await client.get("/admin/api/errors?page_size=1000")).status_code == 422
        assert (await client.get("/admin/api/summary?window=wrong")).status_code == 422


async def test_system_partial_data_and_cpu_history(tmp_path, client_for, monkeypatch):
    async with client_for(
        no_upstream, env={"HOST_PROC_PATH": str(tmp_path), "HOST_DISK_PATH": str(tmp_path)}
    ) as client:
        sampler = client.app.state.system
        await sampler.close()
        sampler.sample()
        await client.post("/admin/api/auth/login", json={"password": PASSWORD})

        async def unavailable(*args, **kwargs):
            raise RuntimeError("private")

        monkeypatch.setattr(client.app.state.redis, "ping", unavailable)
        monkeypatch.setattr(client.app.state.store, "pool", SimpleNamespace(fetchval=unavailable))
        result = await client.get("/admin/api/system")
        assert result.status_code == 200
        data = result.json()
        assert data["status"] == "partial"
        assert data["current"]["cpu_percent"] is None
        assert data["current"]["disk"]["total_bytes"] > 0
        assert not data["redis"]["ok"] and not data["postgres"]["ok"]
        assert "private" not in result.text
        monkeypatch.undo()
    (tmp_path / "stat").write_text("cpu  10 0 10 80 0 0 0 0 0 0\n")
    (tmp_path / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 250 kB\n")
    (tmp_path / "loadavg").write_text("0.1 0.2 0.3 1/1 1\n")
    sampler = SystemSampler(Settings.from_env(ENV | {"HOST_PROC_PATH": str(tmp_path)}))
    sampler.sample()
    (tmp_path / "stat").write_text("cpu  20 0 20 160 0 0 0 0 0 0\n")
    sampler.sample()
    assert sampler.samples[-1]["cpu_percent"] == 20
    assert sampler.samples[-1]["memory"]["percent"] == 75
    assert sampler.samples[-1]["load"] == [0.1, 0.2, 0.3]
