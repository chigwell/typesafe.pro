import httpx
import pytest

from seo_content.inspiration import (
    MAX_REQUESTS,
    HackerNewsFeed,
    InspirationUnavailable,
    WordsFeed,
    clean_title,
    feed_for,
)


def feed(handler):
    return HackerNewsFeed(client=httpx.Client(transport=httpx.MockTransport(handler)))


def algolia(hits):
    return httpx.Response(200, json={"hits": hits})


def hit(i, title, url=None):
    return {"objectID": str(i), "title": title, "url": url}


def test_clean_title():
    assert clean_title("Show HN: GPU-font – match fonts") == "GPU-font – match fonts"
    assert clean_title("Ask HN:  What   do you\x00 use?") == "What do you use?"
    assert clean_title("Ask HN: Who is hiring? (October)") is None
    assert clean_title("x" * 500) == "x" * 200
    assert clean_title(None) is None and clean_title("   ") is None


def test_next_returns_fresh_unseen_titles_each_round():
    hits = [hit(i, f"Story {i}", f"https://e.test/{i}") for i in range(12)]
    hn = feed(lambda request: algolia(hits))
    first = hn.next(5)
    second = hn.next(5)
    assert [h.title for h in first] == [f"Story {i}" for i in range(5)]
    assert [h.id for h in second] == list(range(5, 10))
    assert first[0].url == "https://e.test/0" and first[0].source == "hn"


def test_unsafe_urls_are_dropped():
    hn = feed(lambda request: algolia([hit(1, "A", "javascript:alert(1)")]))
    assert hn.next(1)[0].url is None


def test_firebase_is_the_fallback_and_skips_dead_items():
    def handler(request):
        path = request.url.path
        if request.url.host == "hn.algolia.com":
            return httpx.Response(503)
        if path.endswith("newstories.json"):
            return httpx.Response(200, json=[1, 2, 3, 4])
        item = int(path.rsplit("/", 1)[1].split(".")[0])
        data = {"id": item, "type": "story", "title": f"Item {item}"}
        if item == 2:
            data["dead"] = True
        if item == 3:
            data["type"] = "comment"
        return httpx.Response(200, json=data)

    assert [h.title for h in feed(handler).next(2)] == ["Item 1", "Item 4"]


def test_total_failure_raises_unavailable():
    with pytest.raises(InspirationUnavailable):
        feed(lambda request: httpx.Response(500)).next(5)

    def broken(request):
        raise httpx.ConnectError("offline")

    with pytest.raises(InspirationUnavailable):
        feed(broken).next(5)


def test_request_limit_is_enforced():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json=[] if "newstories" in str(request.url) else {"hits": []})

    hn = feed(handler)
    for _ in range(MAX_REQUESTS):
        with pytest.raises(InspirationUnavailable):
            hn.next(1)
    assert len(calls) <= MAX_REQUESTS


def test_words_feed_and_factory():
    import random

    words = WordsFeed(random.Random(1)).next(5)
    assert len(words) == 5 and all(w.source == "words" for w in words)
    assert feed_for("none").next(5) == []
    with pytest.raises(ValueError):
        feed_for("rss")
