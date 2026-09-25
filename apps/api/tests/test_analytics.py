from datetime import UTC, date, datetime

import httpx
import pytest
from conftest import ENV

from proxy.admin import COOKIE, session_cookie
from proxy.auth import digest
from proxy.config import Settings


def no_upstream(request):
    pytest.fail("Analytics request reached upstream")


async def test_page_view_endpoint_deduplicates_same_ip_path_day(client_for, store):
    async with client_for(no_upstream) as client:
        headers = {"X-Real-IP": "203.0.113.20"}
        first = await client.post("/analytics/view", json={"path": "/"}, headers=headers)
        second = await client.post("/analytics/view", json={"path": "/"}, headers=headers)
        assert first.status_code == second.status_code == 204

    rows = await store.pool.fetch("SELECT * FROM page_views")
    assert len(rows) == 1
    assert rows[0]["path"] == "/"
    assert rows[0]["hits"] == 2
    assert rows[0]["first_seen_at"] <= rows[0]["last_seen_at"]


async def test_page_views_group_by_day_path_and_visitor(store):
    settings = Settings.from_env(ENV)
    first_day = datetime(2026, 9, 24, 12, tzinfo=UTC)
    second_day = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def visitor(day: date, ip: str) -> str:
        return digest(settings.hash_secret, f"{day.isoformat()}:{ip}".encode(), "analytics-visitor")

    await store.record_page_view("/", visitor(first_day.date(), "203.0.113.1"), first_day)
    await store.record_page_view("/", visitor(first_day.date(), "203.0.113.1"), first_day)
    await store.record_page_view("/", visitor(first_day.date(), "203.0.113.2"), first_day)
    await store.record_page_view("/docs", visitor(first_day.date(), "203.0.113.1"), first_day)
    await store.record_page_view("/", visitor(second_day.date(), "203.0.113.1"), second_day)

    page = await store.page_view_page(first_day.date(), second_day.date(), 1, 10)
    rows = {(row["date"], row["path"]): row for row in page["items"]}
    assert page["total"] == 3
    assert rows[("2026-09-24", "/")]["unique_visitors"] == 2
    assert rows[("2026-09-24", "/")]["total_hits"] == 3
    assert rows[("2026-09-24", "/docs")]["unique_visitors"] == 1
    assert rows[("2026-09-25", "/")]["unique_visitors"] == 1


async def test_analytics_rejects_admin_and_query_paths(client_for, store):
    async with client_for(no_upstream) as client:
        for path in ("/admin", "/admin/users", "/?x=1", "/#hero"):
            response = await client.post("/analytics/view", json={"path": path})
            assert response.status_code == 400
    assert await store.pool.fetchval("SELECT count(*) FROM page_views") == 0


async def test_page_view_rate_limit(client_for):
    async with client_for(
        no_upstream, env={"ANALYTICS_VIEW_BURST": "2", "ANALYTICS_VIEW_RPM": "60"}
    ) as client:
        headers = {"X-Real-IP": "203.0.113.30"}
        responses = [
            await client.post("/analytics/view", json={"path": "/"}, headers=headers)
            for _ in range(3)
        ]
    assert [response.status_code for response in responses] == [204, 204, 429]
    assert int(responses[-1].headers["retry-after"]) > 0


async def test_untrusted_peer_cannot_rotate_analytics_ip(client_for):
    async with client_for(
        no_upstream, env={"ANALYTICS_VIEW_BURST": "1", "ANALYTICS_VIEW_RPM": "60"}
    ) as client:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(client.app, client=("203.0.113.10", 1234)),
            base_url="https://api.typesafe.pro",
        ) as attacker:
            first = await attacker.post(
                "/analytics/view",
                json={"path": "/"},
                headers={"X-Real-IP": "192.0.2.1"},
            )
            second = await attacker.post(
                "/analytics/view",
                json={"path": "/"},
                headers={"X-Real-IP": "192.0.2.2"},
            )
    assert first.status_code == 204
    assert second.status_code == 429


async def test_admin_page_views_endpoint_requires_session_and_reports(client_for, store):
    settings = Settings.from_env(ENV)
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)
    visitor = digest(settings.hash_secret, b"2026-09-25:203.0.113.1", "analytics-visitor")
    await store.record_page_view("/", visitor, now)

    async with client_for(no_upstream) as client:
        response = await client.get("/admin/api/page-views?from=2026-09-25&to=2026-09-25")
        assert response.status_code == 401
        client.cookies.set(
            COOKIE,
            session_cookie(settings),
            domain="api.typesafe.pro",
            path="/admin/api",
        )
        response = await client.get("/admin/api/page-views?from=2026-09-25&to=2026-09-25")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == [
        {
            "date": "2026-09-25",
            "path": "/",
            "unique_visitors": 1,
            "total_hits": 1,
            "first_seen_at": "2026-09-25T12:00:00Z",
            "last_seen_at": "2026-09-25T12:00:00Z",
        }
    ]
