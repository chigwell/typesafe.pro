"""Fresh entropy for idea generation: the newest Hacker News story titles.

Titles are untrusted third-party text. They only seed a domain, audience or work context
for the idea prompt; they are cleaned, truncated, labelled as data, and never published.
"""

import random
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

ALGOLIA = "https://hn.algolia.com/api/v1/search_by_date"
FIREBASE = "https://hacker-news.firebaseio.com/v0"
MAX_REQUESTS = 40
MAX_TITLE = 200
PREFIX = re.compile(r"^(?:show|ask|launch|tell)\s+hn\s*[:\-–]\s*", re.IGNORECASE)
SKIP = re.compile(r"who is hiring|who wants to be hired|freelancer\? seeking", re.IGNORECASE)
WORDS = (Path(__file__).parent / "words.txt").read_text().split()


class InspirationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Headline:
    id: int
    title: str
    url: str | None
    source: str

    def as_dict(self) -> dict:
        return {"source": self.source, "id": self.id, "title": self.title, "url": self.url}


def clean_title(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = "".join(ch if ch.isprintable() else " " for ch in value)
    text = PREFIX.sub("", " ".join(text.split()))
    if not text or SKIP.search(text):
        return None
    return text[:MAX_TITLE].rstrip()


def safe_url(value) -> str | None:
    return (
        value[:500]
        if isinstance(value, str) and value.startswith(("https://", "http://"))
        else None
    )


class HackerNewsFeed:
    """The newest stories, never repeating a story within one session."""

    label = "Hacker News, newest"

    def __init__(self, client: httpx.Client | None = None, timeout: float = 10):
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)
        self.seen: set[int] = set()
        self.requests = 0

    def _get(self, url, **params):
        if self.requests >= MAX_REQUESTS:
            raise InspirationUnavailable("request limit reached")
        self.requests += 1
        try:
            response = self.client.get(url, params=params or None)
            if response.status_code != 200:
                raise InspirationUnavailable(f"HTTP {response.status_code}")
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise InspirationUnavailable("network or JSON error") from None

    def _take(self, items, n) -> list[Headline]:
        found = []
        for item_id, title, url in items:
            if not isinstance(item_id, int) or item_id in self.seen:
                continue
            clean = clean_title(title)
            if clean is None:
                continue
            self.seen.add(item_id)
            found.append(Headline(item_id, clean, safe_url(url), "hn"))
            if len(found) == n:
                break
        return found

    def _algolia(self, n):
        data = self._get(ALGOLIA, tags="story", hitsPerPage=50 + len(self.seen))
        hits = data.get("hits") if isinstance(data, dict) else None
        if not isinstance(hits, list):
            raise InspirationUnavailable("unexpected response")
        items = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            try:
                item_id = int(hit.get("objectID"))
            except (TypeError, ValueError):
                continue
            items.append((item_id, hit.get("title"), hit.get("url")))
        return self._take(items, n)

    def _firebase(self, n):
        ids = self._get(f"{FIREBASE}/newstories.json")
        if not isinstance(ids, list):
            raise InspirationUnavailable("unexpected response")
        found = []
        for item_id in ids:
            if len(found) == n or self.requests >= MAX_REQUESTS:
                break
            if not isinstance(item_id, int) or item_id in self.seen:
                continue
            item = self._get(f"{FIREBASE}/item/{item_id}.json")
            if not isinstance(item, dict) or item.get("type") != "story":
                continue
            if item.get("dead") or item.get("deleted"):
                continue
            found += self._take([(item_id, item.get("title"), item.get("url"))], 1)
        return found

    def next(self, n: int = 5) -> list[Headline]:
        try:
            found = self._algolia(n)
        except InspirationUnavailable:
            found = []
        if len(found) < n:
            found += self._firebase(n - len(found))
        if not found:
            raise InspirationUnavailable("no fresh stories")
        return found


class WordsFeed:
    """Offline fallback: a few random words (the previous behaviour)."""

    label = "random words"

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()

    def next(self, n: int = 5) -> list[Headline]:
        return [Headline(-1, word, None, "words") for word in self.rng.sample(WORDS, n)]


class NoFeed:
    label = "none"

    def next(self, n: int = 5) -> list[Headline]:
        return []


def feed_for(mode: str, rng: random.Random | None = None):
    if mode == "hn":
        return HackerNewsFeed()
    if mode == "words":
        return WordsFeed(rng)
    if mode == "none":
        return NoFeed()
    raise ValueError(f"unknown inspiration source: {mode}")
