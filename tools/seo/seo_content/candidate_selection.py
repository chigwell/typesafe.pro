"""Candidate diversity, focus screening and ordered pooling for review sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .catalog import compact, fingerprint, normalized
from .errors import ReviewError, StageError
from .models import Idea
from .novelty import Rejected, novelty_scan
from .pipeline import focus_scores, propose_ideas

if TYPE_CHECKING:
    from .review import ReviewSession


MAX_IDEA_ROUNDS = 10
DUPLICATE = 0.8
SIMILAR = 0.2
NEAR_IDENTICAL = 0.5
MIN_FOCUS = 0.5
CLEAN_TARGET = 5
EXTRA_ROUNDS = 2


def words_of(idea) -> set[str]:
    return set(normalized(f"{idea.slug.replace('-', ' ')} {idea.summary}").split())


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def diverse(session: ReviewSession, candidates: list[Idea]) -> list[Idea]:
    """Drop near-identical ideas before spending API calls on duplicate checks."""
    from .pipeline import frequent_task_types

    avoid = {normalized(t) for t in frequent_task_types(session.known, [])[:6]}
    kept, types, seen = [], set(), [words_of(p) for p in session.known]
    seen += [
        set(normalized(f"{x['slug'].replace('-', ' ')} {x['summary']}").split())
        for x in session.proposed_before_round
    ]
    hidden = 0
    for idea in candidates:
        task = normalized(idea.task_type)
        words = words_of(idea)
        if task in types or task in avoid or any(jaccard(words, w) >= NEAR_IDENTICAL for w in seen):
            hidden += 1
            session.rejected["low_diversity"] += 1
            continue
        types.add(task)
        seen.append(words)
        kept.append(idea)
    if hidden:
        session.out(f"Hid {hidden} near-identical idea(s).")
    return kept


def fill_pool(session: ReviewSession):
    """Collect focused, diverse, novel ideas; ask again with feedback when too few."""
    extra = 0
    while not session.pool or session.clean_count() < CLEAN_TARGET:
        if session.pool:
            if extra >= EXTRA_ROUNDS:
                break
            extra += 1
            session.out(
                f"Only {session.clean_count()} clearly new idea(s); asking for more with "
                f"feedback ({extra}/{EXTRA_ROUNDS}) ..."
            )
        session.idea_round()
        if not session.pool:
            session.warn("no new ideas survived; asking for more")
    # Clearly new ideas first (most focused first), then partly similar ones from the
    # most to the least novel.
    session.pool.sort(
        key=lambda item: (
            item[2] is not None,
            -(session.focus.get(item[0].slug, 0) if item[2] is None else item[1]),
        )
    )


def clean_count(session: ReviewSession) -> int:
    return sum(1 for _, _, similar in session.pool if similar is None)


def idea_round(session: ReviewSession):
    if session.rounds >= MAX_IDEA_ROUNDS:
        raise ReviewError("too many idea rounds; end the session and start again")
    session.rounds += 1
    session.out(f"\nProposing ideas (round {session.rounds}) ...")
    headlines = session.next_headlines()
    skipped = session.skips()
    try:
        ideas = session.resilient(
            "Idea generation",
            lambda: propose_ideas(
                session.known,
                session.provider,
                session.rng,
                [{k: s[k] for k in ("summary", "task_type", "decision")} for s in skipped],
                session.proposed[-60:],
                headlines,
                session.near_misses[-20:],
            ),
        )
    except StageError:
        session.rejected["idea_stage_failed"] += 1
        session.warn("the model did not return valid ideas; trying another round")
        return
    taken = {p.slug for p in session.known}
    taken.update(item[0].slug for item in session.pool)
    skipped_prints = {s["fingerprint"] for s in skipped}
    session.proposed_before_round = list(session.proposed)
    fresh = []
    for candidate in ideas.ideas:
        idea = Idea.model_validate(compact(candidate))
        session.proposed.append(
            {"slug": idea.slug, "summary": idea.summary, "task_type": idea.task_type}
        )
        if idea.slug in taken or fingerprint(idea) in skipped_prints:
            continue
        taken.add(idea.slug)
        if 0 <= candidate.inspired_by < len(headlines):
            session.origins[idea.slug] = headlines[candidate.inspired_by].as_dict()
        fresh.append(idea)
    fresh = session.focused(session.diverse(fresh))
    session.out(f"Checking {len(fresh)} ideas against the catalog for duplicates ...")
    hidden = 0
    by_slug = {p.slug: p for p in session.known}
    for idea in fresh:
        try:
            duplicate, similar = session.resilient(
                "Duplicate check",
                lambda idea=idea: novelty_scan(idea, session.known, session.provider),
            )
        except Rejected as exc:
            session.rejected[str(exc)] += 1
            hidden += 1
            continue
        if duplicate > SIMILAR and similar in by_slug:
            page = by_slug[similar]
            session.near_misses.append(
                {
                    "idea": idea.summary,
                    "decision": idea.decision,
                    "too_similar_to": {"summary": page.summary, "decision": page.decision},
                }
            )
        if duplicate >= DUPLICATE:
            session.rejected["semantic_duplicate"] += 1
            hidden += 1
            continue
        session.pool.append((idea, 1 - duplicate, similar if duplicate > SIMILAR else None))
    if hidden:
        session.out(f"Hid {hidden} idea(s) that duplicate existing pages.")


def focused(session: ReviewSession, ideas: list[Idea]) -> list[Idea]:
    """Ask Jev how focused each idea is; hide vague or specialist ones (one request)."""
    if not ideas:
        return ideas
    try:
        scores = session.resilient("Focus check", lambda: focus_scores(ideas, session.provider))
    except (StageError, ValueError):
        return ideas
    kept = []
    for idea, score in zip(ideas, scores, strict=True):
        session.focus[idea.slug] = score
        if score >= MIN_FOCUS:
            kept.append(idea)
        else:
            session.rejected["unfocused"] += 1
    if len(kept) < len(ideas):
        session.out(f"Hid {len(ideas) - len(kept)} unfocused idea(s).")
    return kept
