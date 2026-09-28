import json
from pathlib import Path

import httpx
import pytest
from conftest import FakeApi

from seo_content.content_api import ContentApi, ContentApiError
from seo_content.maintenance import heuristic_taxonomy, import_files, read_catalog

CONTENT = Path(__file__).resolve().parents[3] / "content" / "use-cases"


def client(handler):
    return ContentApi(
        base="https://api.test",
        token="t" * 40,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_requests_carry_the_bearer_token_and_parse_json():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [{"slug": "a"}]})

    assert client(handler).drafts() == [{"slug": "a"}]
    assert seen[0].headers["authorization"] == "Bearer " + "t" * 40
    assert str(seen[0].url) == "https://api.test/admin/api/content/drafts"


@pytest.mark.parametrize("status,retryable", [(401, False), (409, False), (429, True), (503, True)])
def test_errors_are_typed_for_the_retry_logic(status, retryable):
    api = client(lambda request: httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(ContentApiError) as failure:
        api.publish("a-slug")
    assert failure.value.status == status and failure.value.retryable is retryable
    assert failure.value.detail == "nope"


def test_network_errors_are_retryable_and_token_is_required():
    def broken(request):
        raise httpx.ConnectError("offline")

    with pytest.raises(ContentApiError) as failure:
        client(broken).categories()
    assert failure.value.retryable
    with pytest.raises(ContentApiError, match="missing_content_token"):
        ContentApi(base="https://api.test", token="")
    with pytest.raises(ContentApiError, match="https"):
        ContentApi(base="http://api.test", token="t" * 40)


def test_put_sends_the_listing_and_review_state():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"slug": "x", "status": "draft", "revision": 1})

    client(handler).put(
        {"slug": "x"}, category="routing-triage", tags=["a", "b"], meta={"review": {}}, novelty=0.9
    )
    assert bodies[0] == {
        "page": {"slug": "x"},
        "status": "draft",
        "category": "routing-triage",
        "tags": ["a", "b"],
        "inspiration": {"review": {}},
        "novelty": 0.9,
    }


@pytest.mark.skipif(not (CONTENT / "manifest.json").exists(), reason="file catalog removed")
def test_import_moves_the_file_catalog_into_the_api():
    api, lines = FakeApi(), []
    pages, released = read_catalog(CONTENT)
    assert import_files(CONTENT, taxonomy="heuristic", api=api, out=lines.append) == 0
    assert sorted(api.published()) == sorted(released)
    for page in pages:
        item = api.items[page.slug]
        assert item["published_at"] == page.created_at
        assert item["category"] and len(item["tags"]) >= 2
    drafts = [slug for slug, item in api.items.items() if item["status"] == "draft"]
    for slug in drafts:
        assert api.items[slug]["meta"]["review"]["concept"]
    assert len(api.runs) == len(list((CONTENT / "runs").glob("*.json")))
    assert lines[-1].startswith(f"Imported {len(released)} published page(s)")


def test_heuristic_taxonomy_always_returns_a_category_and_two_tags():
    from conftest import FakeProvider, idea

    from seo_content.pipeline import create_page

    category, tags = heuristic_taxonomy(create_page(idea(1), 0.95, FakeProvider()))
    assert category == "routing-triage" and len(tags) >= 2
