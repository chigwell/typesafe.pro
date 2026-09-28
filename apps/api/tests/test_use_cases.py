import asyncio
import copy
import json
import time
from pathlib import Path

import pytest
from conftest import ENV

from proxy.content_store import fingerprint, preview_token, valid_preview
from proxy.use_case_schema import Page

TOKEN = "content-token-for-tests-0123456789abcdef"
CONTENT_ENV = {"TYPESAFE_CONTENT_TOKEN_1": TOKEN}
AUTH = {"Authorization": f"Bearer {TOKEN}"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "use_case_page.json").read_text())
ROOT = Path(__file__).resolve().parents[3]


def unused(request):
    raise AssertionError("upstream must not be called")


def variant(slug, title, words, **extra):
    """A distinct valid page: new slug, title and scenario text (so the fingerprint differs)."""
    page = copy.deepcopy(FIXTURE)
    page["slug"] = slug
    page["seo"]["title"] = title
    page["summary"] = f"{title}. {words}."
    page["problem"] = f"{words}. " + page["problem"]
    page["decision"] = f"{words} decision."
    page.update(extra)
    return page


async def put(client, page, **body):
    return await client.put(
        f"/admin/api/content/use-cases/{page['slug']}", json={"page": page, **body}, headers=AUTH
    )


@pytest.fixture
def api(client_for):
    return lambda env=None: client_for(unused, env=CONTENT_ENV | (env or {}))


async def test_migration_seeds_categories(store):
    rows = await store.pool.fetch("SELECT slug FROM use_case_categories ORDER BY sort_order")
    assert [r["slug"] for r in rows][:2] == ["routing-triage", "moderation-safety"]
    assert len(rows) == 8


def test_schema_copy_matches_generator():
    api_copy = (ROOT / "apps/api/proxy/use_case_schema.py").read_text()
    generator = (ROOT / "tools/seo/seo_content/models.py").read_text()
    assert api_copy == generator, "keep proxy/use_case_schema.py identical to seo_content/models.py"


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong-token-000000000000000000000"}]
)
async def test_content_writes_require_the_content_token(api, headers):
    async with api() as client:
        response = await client.put(
            f"/admin/api/content/use-cases/{FIXTURE['slug']}",
            json={"page": FIXTURE},
            headers=headers,
        )
        assert response.status_code == 401
        assert (await client.get("/admin/api/content/drafts", headers=headers)).status_code == 401


async def test_admin_cookie_session_cannot_write_content(api):
    async with api() as client:
        login = await client.post("/admin/api/auth/login", json={"password": ENV["ADMIN_PASSWORD"]})
        assert login.status_code == 200
        response = await client.put(
            f"/admin/api/content/use-cases/{FIXTURE['slug']}", json={"page": FIXTURE}
        )
        assert response.status_code == 401


async def test_draft_is_private_until_published(api):
    async with api() as client:
        saved = await put(client, FIXTURE, category="tone-sentiment", tags=["Music", "colour"])
        assert saved.status_code == 200 and saved.json()["status"] == "draft"
        listing = await client.get("/v1/use-cases")
        assert listing.status_code == 200 and listing.json()["total"] == 0
        assert (await client.get(f"/v1/use-cases/{FIXTURE['slug']}")).status_code == 404
        drafts = (await client.get("/admin/api/content/drafts", headers=AUTH)).json()["items"]
        assert [d["slug"] for d in drafts] == [FIXTURE["slug"]]
        assert (
            drafts[0]["tags"] == ["colour", "music"] and drafts[0]["category"] == "tone-sentiment"
        )

        published = await client.post(
            f"/admin/api/content/use-cases/{FIXTURE['slug']}/publish", headers=AUTH
        )
        assert published.status_code == 200
        listing = (await client.get("/v1/use-cases")).json()
        assert listing["total"] == 1
        card = listing["items"][0]
        assert card["category"] == {"slug": "tone-sentiment", "name": "Tone & sentiment"}
        assert [t["slug"] for t in card["tags"]] == ["colour", "music"]
        assert card["has_demo"] is True and card["published_at"]
        detail = await client.get(f"/v1/use-cases/{FIXTURE['slug']}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["page"]["examples"][0]["response"] == FIXTURE["examples"][0]["response"]
        assert body["status"] == "published" and body["related"] == []


async def test_public_responses_are_cacheable_with_etags(api):
    async with api() as client:
        await put(client, FIXTURE, status="published")
        first = await client.get(f"/v1/use-cases/{FIXTURE['slug']}")
        assert first.headers["cache-control"].startswith("public, max-age=60")
        assert first.headers["access-control-allow-origin"] == "*"
        again = await client.get(
            f"/v1/use-cases/{FIXTURE['slug']}", headers={"If-None-Match": first.headers["etag"]}
        )
        assert again.status_code == 304 and again.content == b""


async def test_writes_invalidate_the_cache_immediately(api):
    async with api() as client:
        assert (await client.get("/v1/use-cases")).json()["total"] == 0
        await put(client, FIXTURE, status="published")
        assert (await client.get("/v1/use-cases")).json()["total"] == 1
        await client.post(f"/admin/api/content/use-cases/{FIXTURE['slug']}/archive", headers=AUTH)
        assert (await client.get("/v1/use-cases")).json()["total"] == 0
        assert (await client.get(f"/v1/use-cases/{FIXTURE['slug']}")).status_code == 404


async def test_full_text_search_filters_and_pagination(api):
    async with api() as client:
        pages = [
            (
                variant("refund-request-routing", "Route refund requests", "refund billing"),
                "routing-triage",
                ["support"],
            ),
            (
                variant("spam-review-detection", "Detect spam product reviews", "spam reviews"),
                "moderation-safety",
                ["reviews", "support"],
            ),
            (
                variant("playlist-colour-mood", "Colour a playlist mood", "playlist colour"),
                "tone-sentiment",
                ["music"],
            ),
        ]
        for page, category, tags in pages:
            response = await put(client, page, status="published", category=category, tags=tags)
            assert response.status_code == 200, response.text
        spam = (await client.get("/v1/use-cases", params={"q": "spam reviews"})).json()
        assert [i["slug"] for i in spam["items"]][0] == "spam-review-detection"
        phrase = (await client.get("/v1/use-cases", params={"q": '"route refund"'})).json()
        assert [i["slug"] for i in phrase["items"]] == ["refund-request-routing"]
        either = (await client.get("/v1/use-cases", params={"q": "refund or spam"})).json()
        assert {i["slug"] for i in either["items"]} == {
            "refund-request-routing",
            "spam-review-detection",
        }
        assert (await client.get("/v1/use-cases", params={"q": "zzzqqq"})).json()["total"] == 0
        by_category = (
            await client.get("/v1/use-cases", params={"category": "tone-sentiment"})
        ).json()
        assert [i["slug"] for i in by_category["items"]] == ["playlist-colour-mood"]
        by_tag = (await client.get("/v1/use-cases", params={"tag": "support"})).json()
        assert by_tag["total"] == 2
        both = await client.get("/v1/use-cases", params={"tag": "support", "q": "refund"})
        assert [i["slug"] for i in both.json()["items"]] == ["refund-request-routing"]
        paged = (await client.get("/v1/use-cases", params={"page": 2, "page_size": 2})).json()
        assert paged["total"] == 3 and len(paged["items"]) == 1 and paged["page"] == 2
        for bad in ({"page": 0}, {"page_size": 49}, {"q": "x" * 201}, {"category": "Bad Slug"}):
            assert (await client.get("/v1/use-cases", params=bad)).status_code == 422
        facets = (await client.get("/v1/use-case-facets")).json()
        counts = {c["slug"]: c["count"] for c in facets["categories"]}
        assert counts["routing-triage"] == 1 and counts["creative-lifestyle"] == 0
        assert facets["tags"][0] == {"slug": "support", "name": "support", "count": 2}
        detail = (await client.get("/v1/use-cases/refund-request-routing")).json()
        assert len(detail["related"]) == 2
        sitemap = (await client.get("/v1/use-cases-sitemap")).json()
        assert sitemap["total"] == 3 and sitemap["chunks"] == 1 and len(sitemap["items"]) == 3


async def test_invalid_pages_and_conflicts_are_rejected(api):
    async with api() as client:
        broken = copy.deepcopy(FIXTURE)
        broken["examples"] = broken["examples"][:2]
        assert (await put(client, broken)).status_code == 422
        response = await client.put(
            "/admin/api/content/use-cases/other-slug", json={"page": FIXTURE}, headers=AUTH
        )
        assert response.status_code == 422 and "slug" in response.json()["detail"]
        assert (await put(client, FIXTURE, category="no-such-category")).status_code == 422
        assert (await put(client, FIXTURE, status="published")).status_code == 200
        twin = copy.deepcopy(FIXTURE)
        twin["slug"] = "same-scenario-new-slug"
        clash = await put(client, twin)
        assert clash.status_code == 409 and FIXTURE["slug"] in clash.json()["detail"]
        assert (await put(client, FIXTURE, status="draft")).status_code == 409
        missing = await client.post("/admin/api/content/use-cases/nope/publish", headers=AUTH)
        assert missing.status_code == 404


async def test_imported_dates_are_preserved(api, store):
    async with api() as client:
        response = await put(
            client, FIXTURE, status="published", published_at="2026-09-27T20:00:00Z"
        )
        assert response.status_code == 200
        body = (await client.get(f"/v1/use-cases/{FIXTURE['slug']}")).json()
        assert body["published_at"] == "2026-09-27T20:00:00Z"
        assert body["updated_at"] == FIXTURE["updated_at"].replace("+00:00", "Z")


async def test_preview_tokens(api):
    async with api() as client:
        await put(client, FIXTURE)
        issued = await client.post(
            f"/admin/api/content/use-cases/{FIXTURE['slug']}/preview-token", headers=AUTH
        )
        token = issued.json()["token"]
        preview = await client.get(
            f"/v1/use-cases/preview/{FIXTURE['slug']}", params={"token": token}
        )
        assert preview.status_code == 200 and preview.json()["status"] == "draft"
        assert preview.headers["cache-control"] == "no-store"
        assert preview.headers["x-robots-tag"] == "noindex, nofollow"
        for slug, value in ((FIXTURE["slug"], token + "0"), ("other-slug", token)):
            response = await client.get(f"/v1/use-cases/preview/{slug}", params={"token": value})
            assert response.status_code == 404
    secret = b"secret-secret-secret-secret-secret"
    old = preview_token(secret, "a-slug", ttl=10, now=time.time() - 100)
    assert not valid_preview(secret, "a-slug", old)
    assert valid_preview(secret, "a-slug", preview_token(secret, "a-slug"))
    assert not valid_preview(secret, "a-slug", "garbage")


async def test_openapi_documents_only_public_content(api):
    async with api() as client:
        schema = (await client.get("/openapi.json")).json()
    paths = set(schema["paths"])
    assert paths == {
        "/v1/use-cases",
        "/v1/use-case-facets",
        "/v1/use-cases-sitemap",
        "/v1/use-cases/{slug}",
        "/v1/use-cases/preview/{slug}",
    }
    assert "UseCaseCard" in schema["components"]["schemas"]


async def test_cache_misses_are_rate_limited(api):
    async with api({"CONTENT_READ_RPM": "1", "CONTENT_READ_BURST": "2"}) as client:
        statuses = [
            (await client.get("/v1/use-cases", params={"q": f"word{i}"})).status_code
            for i in range(4)
        ]
        assert statuses[:2] == [200, 200] and statuses[-1] == 429
        # Cached responses are still served without spending the budget.
        assert (await client.get("/v1/use-cases", params={"q": "word0"})).status_code == 200


async def test_runs_and_skips(api, store):
    report = {
        "run_id": "local-20260928T101052Z-1",
        "source_sha": "a969713",
        "status": "prepared",
        "reason": "approved_by_reviewer",
        "started_at": "2026-09-28T10:10:52Z",
        "finished_at": "2026-09-28T10:30:00Z",
        "duration_seconds": 1100.5,
        "seed": 1,
        "rounds": 2,
        "api_calls": 50,
        "input_tokens": 1,
        "output_tokens": 2,
        "generated_count": 1,
        "rejected_count": 0,
        "rejections": {},
        "catalog_hash": "",
        "mode": "review",
        "approved_count": 1,
        "skipped_count": 0,
        "inspiration_source": "hn",
    }
    async with api() as client:
        recorded = await client.post("/admin/api/content/runs", json=report, headers=AUTH)
        assert recorded.status_code == 201 and recorded.json()["recorded"] is True
        skip = {
            "fingerprint": "a" * 64,
            "slug": "boring-idea",
            "summary": "Boring",
            "task_type": "x",
            "decision": "y",
            "reason": "too generic",
        }
        assert (
            await client.post("/admin/api/content/skips", json=skip, headers=AUTH)
        ).status_code == 201
        skips = (await client.get("/admin/api/content/skips", headers=AUTH)).json()["items"]
        assert skips[0]["slug"] == "boring-idea" and skips[0]["fingerprint"] == "a" * 64
    assert await store.pool.fetchval("SELECT count(*) FROM seo_runs") == 1


async def test_compact_listing_for_novelty_checks(api):
    async with api() as client:
        await put(client, FIXTURE, status="published")
        items = (await client.get("/admin/api/content/use-cases", headers=AUTH)).json()["items"]
    assert items[0]["slug"] == FIXTURE["slug"]
    assert items[0]["fingerprint"] == fingerprint(Page.model_validate(FIXTURE))
    assert set(items[0]) >= {"problem", "decision", "action", "task_type", "status"}


async def test_listing_stays_fast_with_1200_pages(api, store):
    content = json.dumps(FIXTURE)
    await store.pool.executemany(
        """INSERT INTO use_cases (slug, status, fingerprint, title, meta_description, summary,
           industry, audience, task_type, content, created_at, updated_at, published_at)
           VALUES ($1, 'published', $2, $3, 'd', $4, 'industry', 'audience', $5,
                   $6::jsonb, now(), now(), now())""",
        [
            (
                f"seeded-case-{i}",
                f"{i:064d}",
                f"Seeded title {i} {'spam' if i % 10 == 0 else 'routing'}",
                f"summary {i}",
                f"task-{i % 40}",
                content,
            )
            for i in range(1200)
        ],
    )
    await store.pool.execute("ANALYZE use_cases")
    async with api() as client:
        started = time.perf_counter()
        results = await asyncio.gather(
            client.get("/v1/use-cases", params={"q": "spam", "page": 3}),
            client.get("/v1/use-cases", params={"page": 50}),
            client.get("/v1/use-cases-sitemap"),
        )
        elapsed = time.perf_counter() - started
    assert [r.status_code for r in results] == [200, 200, 200]
    assert results[0].json()["total"] == 120
    assert results[1].json()["total"] == 1200 and len(results[1].json()["items"]) == 24
    assert results[2].json()["total"] == 1200
    assert elapsed < 2, f"three cold queries took {elapsed:.2f}s"


def test_fingerprint_matches_the_generator():
    import sys

    sys.path.insert(0, str(ROOT / "tools" / "seo"))
    try:
        from seo_content.catalog import fingerprint as generator_fingerprint
        from seo_content.models import Page as GeneratorPage
    finally:
        sys.path.pop(0)
    page = Page.model_validate(FIXTURE)
    assert fingerprint(page) == generator_fingerprint(GeneratorPage.model_validate(FIXTURE))
