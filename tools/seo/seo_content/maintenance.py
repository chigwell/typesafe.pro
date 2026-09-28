"""One-time import of the former file catalog, and a schema check of the stored pages."""

import json
from pathlib import Path

import httpx

from .content_api import ContentApi, ContentApiError
from .models import Page
from .pipeline import choose_taxonomy
from .providers import Budget, ProviderError, Providers

CATEGORY_HINTS = [
    ("moderation-safety", ("spam", "abuse", "moderation", "safety", "toxic", "fraud", "authentic")),
    ("tone-sentiment", ("tone", "sentiment", "mood", "emotion", "polite", "frustration")),
    ("quality-completeness", ("complete", "clarity", "quality", "missing", "readiness")),
    ("scoring-prioritisation", ("scoring", "severity", "urgency", "priority", "level", "spice")),
    ("routing-triage", ("routing", "triage", "queue", "dispatch", "escalat")),
    ("matching-recommendation", ("matching", "recommend", "palette", "pairing", "fit")),
    ("detection-classification", ("detect", "classif", "screening", "check", "flag")),
]


def heuristic_taxonomy(page: Page) -> tuple[str, list[str]]:
    text = f"{page.task_type} {page.summary} {page.decision}".lower()
    category = next(
        (slug for slug, words in CATEGORY_HINTS if any(word in text for word in words)),
        "creative-lifestyle",
    )
    tags = [part for part in page.task_type.split("-") if len(part) > 2][:3]
    domain = "-".join(page.industry.lower().replace("&", " ").split()[:2])
    tags = [t for t in dict.fromkeys([*tags, domain]) if t][:5]
    while len(tags) < 2:
        tags.append("use-case")
    return category, tags


def read_catalog(content_dir: Path) -> tuple[list[Page], set[str]]:
    manifest = json.loads((content_dir / "manifest.json").read_text())
    pages = []
    for shard in manifest["shards"]:
        data = json.loads((content_dir / shard["file"]).read_text())
        pages += [Page.model_validate(item) for item in data["pages"]]
    release = json.loads((content_dir / "release.json").read_text())
    return pages, {item["slug"] for item in release["pages"]}


def import_files(content_dir: Path, *, taxonomy="llm", api=None, provider=None, out=print) -> int:
    api = api or ContentApi()
    categories = api.categories()
    if taxonomy == "llm" and provider is None:
        provider = Providers(Budget(max_calls=60, max_seconds=1800))

    def listing(page: Page):
        if taxonomy == "llm":
            try:
                chosen = choose_taxonomy(page, categories, provider)
                return chosen.category, list(chosen.tags)
            except (ProviderError, ValueError) as exc:
                out(f"  ! {page.slug}: model taxonomy failed ({str(exc)[:80]}); using heuristic")
        return heuristic_taxonomy(page)

    pages, released = read_catalog(content_dir)
    counts = {"published": 0, "drafts": 0, "runs": 0}
    for page in pages:
        status = "published" if page.slug in released else "draft"
        category, tags = listing(page)
        api.put(
            page.model_dump(exclude_none=True),
            status=status,
            category=category,
            tags=tags,
            novelty=page.verification.novelty_probability,
            published_at=page.created_at if status == "published" else None,
        )
        counts["published" if status == "published" else "drafts"] += 1
        out(f"  {status:9} {page.slug}  [{category} · {', '.join(tags)}]")
    stored = {page.slug for page in pages}
    for path in sorted((content_dir / "drafts").glob("*.json")):
        draft = json.loads(path.read_text())
        if draft.get("status") != "pending" or path.stem in stored:
            continue
        page = Page.model_validate(draft["page"])
        category, tags = listing(page)
        meta = {
            "headline": draft.get("inspiration"),
            "review": {
                "idea": draft["idea"],
                "concept": draft["concept"],
                "feedback": draft.get("feedback", []),
                "attempt": draft.get("attempt", 1),
                "created_at": draft.get("created_at"),
            },
        }
        api.put(
            page.model_dump(exclude_none=True),
            status="draft",
            category=category,
            tags=tags,
            meta=meta,
            novelty=draft.get("novelty"),
        )
        counts["drafts"] += 1
        out(f"  draft     {page.slug}  [{category} · {', '.join(tags)}]")
    for path in sorted((content_dir / "runs").glob("*.json")):
        report = json.loads(path.read_text()).get("report")
        if not isinstance(report, dict):
            continue
        try:
            api.record_run(report)
            counts["runs"] += 1
        except ContentApiError as exc:
            out(f"  ! run {report.get('run_id')}: {exc} {getattr(exc, 'detail', '') or ''}")
    out(
        f"Imported {counts['published']} published page(s), {counts['drafts']} draft(s) and "
        f"{counts['runs']} run report(s)."
    )
    return 0


def check(api=None, client=None, out=print) -> int:
    """Every draft and every published page must still satisfy the page schema."""
    api = api or ContentApi()
    client = client or httpx.Client(timeout=30)
    failures = 0
    for draft in api.drafts():
        try:
            Page.model_validate(draft["page"])
        except ValueError as exc:
            failures += 1
            out(f"  ! draft {draft['slug']}: {str(exc)[:200]}")
    page, total, seen = 1, None, 0
    while total is None or seen < total:
        listing = client.get(f"{api.base}/v1/use-cases", params={"page": page, "page_size": 48})
        listing.raise_for_status()
        body = listing.json()
        total = body["total"]
        for item in body["items"]:
            seen += 1
            detail = client.get(f"{api.base}/v1/use-cases/{item['slug']}")
            try:
                detail.raise_for_status()
                Page.model_validate(detail.json()["page"])
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                failures += 1
                out(f"  ! {item['slug']}: {str(exc)[:200]}")
        if not body["items"]:
            break
        page += 1
    out(f"Checked {seen} published page(s); {failures} problem(s).")
    return 1 if failures else 0
