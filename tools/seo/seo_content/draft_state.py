"""Typed internal review records and lossless draft/API conversion helpers.

TypedDict annotations describe existing records; they add no runtime validation.
"""

from collections.abc import Callable
from typing import Literal, TypedDict

from pydantic import ValidationError

from .models import DemoConcept, Idea, Page


class Feedback(TypedDict):
    at: str
    scope: Literal["text", "demo", "concept", "both"]
    text: str


class ReviewState(TypedDict):
    idea: dict
    concept: dict
    feedback: list[Feedback]
    attempt: int
    created_at: str | None


class ReviewMetadata(TypedDict):
    headline: dict | None
    review: ReviewState


class ReviewDraft(TypedDict):
    slug: str
    idea: dict
    concept: dict
    page: dict
    novelty: float
    feedback: list[Feedback]
    attempt: int
    created_at: str | None
    category: str | None
    tags: list[str]
    revision: int | None


def review_metadata(
    idea: Idea,
    concept: DemoConcept,
    feedback: list[Feedback],
    attempt: int,
    created_at: str | None,
    headline: dict | None,
    now: Callable[[], str],
) -> ReviewMetadata:
    return {
        "headline": headline,
        "review": {
            "idea": idea.model_dump(),
            "concept": concept.model_dump(exclude_none=True),
            "feedback": feedback,
            "attempt": attempt,
            "created_at": created_at or now(),
        },
    }


def saved_draft(
    page: Page,
    meta: ReviewMetadata,
    novelty: float,
    category: str | None,
    tags: list[str],
    saved: dict,
) -> ReviewDraft:
    return {
        "slug": page.slug,
        "idea": meta["review"]["idea"],
        "concept": meta["review"]["concept"],
        "page": page.model_dump(exclude_none=True),
        "novelty": novelty,
        "feedback": meta["review"]["feedback"],
        "attempt": meta["review"]["attempt"],
        "created_at": meta["review"]["created_at"],
        "category": category,
        "tags": tags,
        "revision": saved["revision"],
    }


def draft_from_api(item: dict, warn) -> ReviewDraft | None:
    review = (item.get("inspiration") or {}).get("review") or {}
    try:
        Page.model_validate(item["page"])
        Idea.model_validate(review["idea"])
        DemoConcept.model_validate(review["concept"])
    except (ValidationError, KeyError, TypeError):
        warn(f"draft {item.get('slug')} has no review state and was ignored")
        return None
    return {
        "slug": item["slug"],
        "idea": review["idea"],
        "concept": review["concept"],
        "page": item["page"],
        "novelty": item.get("novelty") or 0.8,
        "feedback": review.get("feedback", []),
        "attempt": review.get("attempt", 1),
        "created_at": review.get("created_at"),
        "category": item.get("category"),
        "tags": item.get("tags", []),
        "revision": item.get("revision"),
    }


def compact_fields(item: dict) -> dict:
    return {key: item[key] for key in Idea.model_fields}


def feedback_notes(feedback: list[Feedback]) -> tuple[list[str], list[str]]:
    text_notes = [f["text"] for f in feedback if f["scope"] in ("text", "both")]
    demo_notes = [f["text"] for f in feedback if f["scope"] in ("demo", "both", "concept")]
    return text_notes, demo_notes
