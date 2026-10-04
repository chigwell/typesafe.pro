"""Interactive review: propose ideas, generate a page with a demo, save it as a draft in the
content API, preview it on the site with a signed link, then publish, revise or skip."""

import random
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser
from collections import Counter
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from pydantic import ValidationError

from .catalog import compact, fingerprint, normalized
from .content_api import ContentApi, ContentApiError
from .demo import propose_concepts
from .errors import ReviewError  # noqa: F401
from .inspiration import InspirationUnavailable, WordsFeed, feed_for
from .models import DemoConcept, Idea, Page, Report
from .novelty import Rejected, novelty_scan
from .pipeline import (
    choose_taxonomy,
    create_page,
    focus_scores,
    now,
    propose_ideas,
    rebuild_demo,
)
from .providers import Budget, BudgetExhausted, ProviderError, Providers, StageError

RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
MAX_IDEA_ROUNDS = 10
RETRY_DELAYS = (10, 30)
DUPLICATE = 0.8
SIMILAR = 0.2
NEAR_IDENTICAL = 0.5
MIN_FOCUS = 0.5
SHOWN = 12
CLEAN_TARGET = 5
EXTRA_ROUNDS = 2


def words_of(idea) -> set[str]:
    return set(normalized(f"{idea.slug.replace('-', ' ')} {idea.summary}").split())


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


LINE = "─" * 72


class Quit(Exception):
    """The reviewer ended the session; pending drafts stay in the content API."""


def session_id_now():
    return datetime.now(UTC).strftime("local-%Y%m%dT%H%M%SZ")


STAGES = {
    "Ideas": "proposing ideas",
    "DemoConcepts": "proposing demo concepts",
    "Description": "writing intro and problem",
    "DraftExamples": "writing the three examples",
    "Explanation": "writing the solution and limitations",
    "SEO": "writing title and meta description",
    "DemoCode": "writing the interactive demo",
    "ArticleRepair": "revising the text to pass the quality check",
}


class ProgressProvider:
    """Print one line per model/API stage so long LLM7 calls never look like a hang."""

    def __init__(self, provider, out):
        self.provider = provider
        self.out = out

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def _timed(self, label, call):
        started = time.monotonic()
        self.out(f"  · {label} …")
        result = call()
        seconds = time.monotonic() - started
        if seconds >= 20:
            self.out(f"    done in {seconds:.0f}s")
        return result

    def structured(self, schema, task, context, **options):
        label = STAGES.get(schema.__name__, schema.__name__)
        if schema.__name__ == "DraftExamples" and "failed_examples" in context:
            label = "repairing examples that the API answered differently"
        if schema.__name__ == "DemoCode" and "previous_attempt" in context:
            label = "revising the interactive demo"
        return self._timed(
            label, lambda: self.provider.structured(schema, task, context, **options)
        )

    def evaluate(self, request):
        keys = list(request.questions)
        if any(key.startswith("duplicate_") for key in keys):
            return self.provider.evaluate(request)
        if any(key.startswith("focused_") for key in keys):
            return self.provider.evaluate(request)
        label = "judging page quality" if "useful" in keys else "running an input on the live API"
        return self._timed(label, lambda: self.provider.evaluate(request))


def brief(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ReviewSession:
    def __init__(
        self,
        *,
        session_id: str | None = None,
        budget: Budget | None = None,
        provider_factory=Providers,
        api_factory=ContentApi,
        preview_base="https://typesafe.pro",
        open_browser=True,
        opener=webbrowser.open,
        auto_select=False,
        max_pages=5,
        prompt=input,
        out=print,
        clock_url="https://api.typesafe.pro/health",
        sleep=time.sleep,
        inspiration="hn",
        headlines=5,
    ):
        self.session_id = session_id or session_id_now()
        self.budget = budget or Budget(max_calls=400, max_seconds=3600)
        self.provider_factory = provider_factory
        self.api_factory = api_factory
        self.preview_base = preview_base.rstrip("/")
        self.open_browser = open_browser
        self.opener = opener
        self.auto_select = auto_select
        self.max_pages = max_pages
        self.prompt = prompt
        self.out = out
        self.clock_url = clock_url
        self.sleep = sleep
        # Screened candidates (idea, novelty probability, most similar slug or None) that
        # stay available across selections until used, skipped or the session ends.
        self.pool: list[tuple[Idea, float, str | None]] = []
        self.proposed: list[dict] = []
        self.proposed_before_round: list[dict] = []
        self.headline_count = headlines
        self.origins: dict[str, dict] = {}
        self.focus: dict[str, float] = {}
        self.near_misses: list[dict] = []
        self.show_all = False
        self.started_at = now()
        self.seed = secrets.randbits(32)
        self.rng = random.Random(self.seed)
        self.feed = feed_for(inspiration, self.rng) if isinstance(inspiration, str) else inspiration
        self.inspiration_source = inspiration if isinstance(inspiration, str) else "hn"
        self.rounds = 0
        self.generated = 0
        self.approved = 0
        self.skipped = 0
        self.rejected = Counter()
        self.published: list[str] = []
        self.api = None
        self.known: list[Idea] = []
        self.categories: list[dict] = []
        self.provider = None
        self.source_sha = "0000000"

    # ----- console helpers -------------------------------------------------------------

    def ask(self, text: str) -> str:
        with self.budget.paused():
            try:
                return self.prompt(text).strip()
            except EOFError:
                raise Quit() from None

    def ask_multiline(self, title: str) -> str:
        self.out(f"{title} (finish with an empty line):")
        lines = []
        while True:
            line = self.ask("> ")
            if not line:
                break
            lines.append(line)
        return "\n".join(lines)

    def warn(self, message: str):
        self.out(f"  ! {message}")

    def header(self, title: str):
        self.out(f"\n{LINE}\n{title}\n{LINE}")

    # ----- lifecycle -------------------------------------------------------------------

    def preflight(self):
        if not RUN_ID.fullmatch(self.session_id):
            raise ReviewError("session ID must match ^[A-Za-z0-9_.-]{1,120}$")
        self.source_sha = generator_version()
        try:
            self.api = self.api_factory()
            self.categories = self.api.categories()
            self.refresh_known()
        except ContentApiError as exc:
            if exc.status == 401:
                raise ReviewError("the content API rejected TYPESAFE_CONTENT_TOKEN_1") from None
            raise ReviewError(f"the content API is not available ({exc})") from None
        self.provider = ProgressProvider(self.provider_factory(self.budget), self.out)
        self.check_clock()

    def refresh_known(self):
        """Every non-archived page and draft: the reference set for novelty and diversity."""
        self.known = [
            Idea.model_validate(compact_fields(item)) for item in self.api.compact_pages()
        ]

    def check_clock(self):
        if not self.clock_url:
            return
        try:
            with urllib.request.urlopen(self.clock_url, timeout=10) as response:
                remote = parsedate_to_datetime(response.headers["Date"])
        except (urllib.error.URLError, OSError, TypeError, ValueError, KeyError):
            return
        skew = abs((datetime.now(UTC) - remote).total_seconds())
        if skew > 300:
            self.warn(
                f"local clock differs from the API by {skew:.0f}s; the publication journal "
                "rejects releases generated in the future"
            )

    def run(self, *, resume=False) -> Report:
        self.header(f"TypeSafe use-case review · session {self.session_id}")
        self.out(
            "Press q at any prompt or Ctrl+C at any time to stop. Approved pages are "
            "published at once; unfinished drafts stay in the content API (--resume)."
        )
        self.preflight()
        try:
            if resume:
                for draft in self.pending_drafts():
                    if self.approved >= self.max_pages:
                        break
                    self.review_draft(draft)
            while self.approved < self.max_pages:
                idea, novelty, similar = self.pick_candidate()
                self.process_idea(idea, novelty, similar)
        except (Quit, KeyboardInterrupt):
            self.out("\nSession ended by reviewer; pending drafts are kept (--resume).")
        except BudgetExhausted:
            self.out("\nSession budget exhausted; pending drafts are kept (--resume).")
        except ProviderError as exc:
            self.out(f"\nProvider failure: {self.describe(exc)}; pending drafts are kept.")
        except ReviewError as exc:
            self.out(f"\nSession stopped: {exc}; pending drafts are kept (--resume).")
        return self.summary()

    @staticmethod
    def describe(exc: ProviderError) -> str:
        detail = getattr(exc, "detail", None)
        return f"{exc} ({detail})" if detail else str(exc)

    def resilient(self, what: str, call):
        """Run a provider stage; wait and retry transient failures instead of ending."""
        attempt = 0
        while True:
            try:
                return call()
            except (BudgetExhausted, StageError):
                raise
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                reason = self.describe(exc)
                if attempt < len(RETRY_DELAYS):
                    delay = RETRY_DELAYS[attempt]
                    attempt += 1
                    self.warn(f"{what} failed: {reason}; retrying in {delay}s")
                    with self.budget.paused():
                        self.sleep(delay)
                    continue
                answer = self.ask(f"{what} keeps failing ({reason}). [r]etry, [q]uit: ").lower()
                if answer != "r":
                    raise Quit() from None
                attempt = 0

    def summary(self) -> Report:
        report = self.report(self.session_id, "prepared" if self.approved else "skipped")
        self.header("Session summary")
        self.out(
            f"approved={self.approved} skipped={self.skipped} generated={self.generated} "
            f"api_calls={self.budget.calls} rejections={dict(self.rejected)}"
        )
        for slug in self.published:
            self.out(f"  published {self.preview_base}/use-cases/{slug}")
        if self.published:
            self.out("Published pages are live now (cached responses refresh within minutes).")
        return report

    def report(self, run_id: str, status: str, reason: str | None = None) -> Report:
        return Report(
            run_id=run_id,
            source_sha=self.source_sha,
            status=status,
            reason=reason or ("approved_by_reviewer" if self.approved else "no_pages_approved"),
            started_at=self.started_at,
            finished_at=now(),
            duration_seconds=round(self.budget.elapsed, 3),
            seed=self.seed,
            rounds=self.rounds,
            api_calls=self.budget.calls,
            input_tokens=self.budget.input_tokens,
            output_tokens=self.budget.output_tokens,
            generated_count=self.generated,
            rejected_count=sum(self.rejected.values()),
            rejections=dict(self.rejected),
            catalog_hash="",
            mode="review",
            inspiration_source=self.inspiration_source,
            approved_count=self.approved,
            skipped_count=self.skipped,
        )

    # ----- ideas -----------------------------------------------------------------------

    def skips(self) -> list[dict]:
        return self.resilient("Loading skipped ideas", self.api.skips)

    def record_skip(self, idea: Idea, reason: str, *, archive=False):
        item = {
            "slug": idea.slug,
            "fingerprint": fingerprint(idea),
            "task_type": idea.task_type,
            "summary": idea.summary,
            "decision": idea.decision,
            "reason": (reason or "")[:800],
        }
        self.resilient("Recording the skip", lambda: self.api.add_skip(item))
        if archive:
            self.resilient("Archiving the draft", lambda: self.api.archive(idea.slug))
        self.skipped += 1
        self.out(f"Skipped {idea.slug}.")

    def next_headlines(self) -> list:
        try:
            headlines = self.feed.next(self.headline_count)
        except InspirationUnavailable as exc:
            self.warn(f"{self.feed.label} unavailable ({exc}); using random words instead")
            self.feed = WordsFeed(self.rng)
            self.inspiration_source = "words"
            headlines = self.feed.next(self.headline_count)
        if headlines:
            self.out(f"Inspiration ({self.feed.label}):")
            for number, headline in enumerate(headlines, 1):
                self.out(f"  {number}. {brief(headline.title, 100)}")
        return headlines

    def diverse(self, candidates: list[Idea]) -> list[Idea]:
        """Drop near-identical ideas before spending API calls on duplicate checks."""
        from .pipeline import frequent_task_types

        avoid = {normalized(t) for t in frequent_task_types(self.known, [])[:6]}
        kept, types, seen = [], set(), [words_of(p) for p in self.known]
        seen += [
            set(normalized(f"{x['slug'].replace('-', ' ')} {x['summary']}").split())
            for x in self.proposed_before_round
        ]
        hidden = 0
        for idea in candidates:
            task = normalized(idea.task_type)
            words = words_of(idea)
            if (
                task in types
                or task in avoid
                or any(jaccard(words, w) >= NEAR_IDENTICAL for w in seen)
            ):
                hidden += 1
                self.rejected["low_diversity"] += 1
                continue
            types.add(task)
            seen.append(words)
            kept.append(idea)
        if hidden:
            self.out(f"Hid {hidden} near-identical idea(s).")
        return kept

    def fill_pool(self):
        """Collect focused, diverse, novel ideas; ask again with feedback when too few."""
        extra = 0
        while not self.pool or self.clean_count() < CLEAN_TARGET:
            if self.pool:
                if extra >= EXTRA_ROUNDS:
                    break
                extra += 1
                self.out(
                    f"Only {self.clean_count()} clearly new idea(s); asking for more with "
                    f"feedback ({extra}/{EXTRA_ROUNDS}) ..."
                )
            self.idea_round()
            if not self.pool:
                self.warn("no new ideas survived; asking for more")
        # Clearly new ideas first (most focused first), then partly similar ones from the
        # most to the least novel.
        self.pool.sort(
            key=lambda item: (
                item[2] is not None,
                -(self.focus.get(item[0].slug, 0) if item[2] is None else item[1]),
            )
        )

    def clean_count(self) -> int:
        return sum(1 for _, _, similar in self.pool if similar is None)

    def idea_round(self):
        if self.rounds >= MAX_IDEA_ROUNDS:
            raise ReviewError("too many idea rounds; end the session and start again")
        self.rounds += 1
        self.out(f"\nProposing ideas (round {self.rounds}) ...")
        headlines = self.next_headlines()
        skipped = self.skips()
        try:
            ideas = self.resilient(
                "Idea generation",
                lambda: propose_ideas(
                    self.known,
                    self.provider,
                    self.rng,
                    [{k: s[k] for k in ("summary", "task_type", "decision")} for s in skipped],
                    self.proposed[-60:],
                    headlines,
                    self.near_misses[-20:],
                ),
            )
        except StageError:
            self.rejected["idea_stage_failed"] += 1
            self.warn("the model did not return valid ideas; trying another round")
            return
        taken = {p.slug for p in self.known}
        taken.update(item[0].slug for item in self.pool)
        skipped_prints = {s["fingerprint"] for s in skipped}
        self.proposed_before_round = list(self.proposed)
        fresh = []
        for candidate in ideas.ideas:
            idea = Idea.model_validate(compact(candidate))
            self.proposed.append(
                {"slug": idea.slug, "summary": idea.summary, "task_type": idea.task_type}
            )
            if idea.slug in taken or fingerprint(idea) in skipped_prints:
                continue
            taken.add(idea.slug)
            if 0 <= candidate.inspired_by < len(headlines):
                self.origins[idea.slug] = headlines[candidate.inspired_by].as_dict()
            fresh.append(idea)
        fresh = self.focused(self.diverse(fresh))
        self.out(f"Checking {len(fresh)} ideas against the catalog for duplicates ...")
        hidden = 0
        by_slug = {p.slug: p for p in self.known}
        for idea in fresh:
            try:
                duplicate, similar = self.resilient(
                    "Duplicate check",
                    lambda idea=idea: novelty_scan(idea, self.known, self.provider),
                )
            except Rejected as exc:
                self.rejected[str(exc)] += 1
                hidden += 1
                continue
            if duplicate > SIMILAR and similar in by_slug:
                page = by_slug[similar]
                self.near_misses.append(
                    {
                        "idea": idea.summary,
                        "decision": idea.decision,
                        "too_similar_to": {"summary": page.summary, "decision": page.decision},
                    }
                )
            if duplicate >= DUPLICATE:
                self.rejected["semantic_duplicate"] += 1
                hidden += 1
                continue
            self.pool.append((idea, 1 - duplicate, similar if duplicate > SIMILAR else None))
        if hidden:
            self.out(f"Hid {hidden} idea(s) that duplicate existing pages.")

    def focused(self, ideas: list[Idea]) -> list[Idea]:
        """Ask Jev how focused each idea is; hide vague or specialist ones (one request)."""
        if not ideas:
            return ideas
        try:
            scores = self.resilient("Focus check", lambda: focus_scores(ideas, self.provider))
        except (StageError, ValueError):
            return ideas
        kept = []
        for idea, score in zip(ideas, scores, strict=True):
            self.focus[idea.slug] = score
            if score >= MIN_FOCUS:
                kept.append(idea)
            else:
                self.rejected["unfocused"] += 1
        if len(kept) < len(ideas):
            self.out(f"Hid {len(ideas) - len(kept)} unfocused idea(s).")
        return kept

    def pick_candidate(self) -> tuple[Idea, float, str | None]:
        while True:
            self.fill_pool()
            if self.auto_select:
                return self.pool.pop(0)
            self.header("Candidate ideas")
            shown = self.pool if self.show_all else self.pool[:SHOWN]
            for number, (idea, novelty, similar) in enumerate(shown, 1):
                self.out(f"{number:>2}. {idea.slug}  [{idea.industry} · {idea.task_type}]")
                self.out(f"    {brief(idea.summary, 110)}")
                origin = self.origins.get(idea.slug)
                if origin and origin["source"] == "hn":
                    self.out(f"    ↳ from: {brief(origin['title'], 100)}")
                if similar:
                    self.out(
                        f"    ⚠ partly similar to /use-cases/{similar} (novelty {novelty:.2f})"
                    )
            more = len(self.pool) - len(shown)
            if more:
                self.out(f"… {more} more partly similar idea(s): press m to list them.")
            options = "Pick an idea [number], [n]ew ideas, " + ("[m]ore, " if more else "")
            answer = self.ask(options + "[q]uit: ").lower()
            if answer == "m":
                self.show_all = True
                continue
            if answer == "q":
                raise Quit()
            if answer == "n":
                self.pool.clear()
                self.show_all = False
                continue
            if answer.isdigit() and 1 <= int(answer) <= len(shown):
                self.show_all = False
                return self.pool.pop(int(answer) - 1)
            self.warn("no valid selection")

    # ----- per idea --------------------------------------------------------------------

    def process_idea(self, idea: Idea, novelty: float, similar: str | None = None):
        self.header(f"Idea: {idea.slug}")
        self.out(brief(idea.problem, 300))
        concept = self.choose_concept(idea)
        if concept is None:
            return
        page = self.generate_page(idea, novelty, concept, feedback=[])
        if page is None:
            return
        draft = self.save_draft(idea, novelty, concept, page, attempt=1, feedback=[])
        self.review_draft(draft)

    def choose_concept(self, idea: Idea, feedback=()) -> DemoConcept | None:
        notes = list(feedback)
        while True:
            self.out("Proposing demo concepts ...")
            try:
                concepts = self.resilient(
                    "Demo concept generation",
                    lambda: propose_concepts(idea, self.provider, notes).concepts,
                )
            except StageError:
                self.rejected["demo_concept_failed"] += 1
                answer = self.ask("No valid concepts. [r]etry, [s]kip idea, [q]uit: ").lower()
                if answer == "r":
                    continue
                if answer == "q":
                    raise Quit() from None
                self.record_skip(idea, "no valid demo concept")
                return None
            if self.auto_select:
                return concepts[0]
            self.header("Demo concepts")
            for number, concept in enumerate(concepts, 1):
                self.out(f"{number}. {concept.title}")
                self.out(f"   Concept:     {brief(concept.concept, 200)}")
                self.out(f"   Interaction: {brief(concept.interaction, 200)}")
                self.out(f"   Visual:      {brief(concept.visual, 200)}")
                questions = ", ".join(f"{k} ({q.type})" for k, q in concept.questions.items())
                self.out(f"   Questions:   {questions}")
            answer = self.ask(
                "Pick a concept [1-3], [r]egenerate with feedback, [s]kip idea, [q]uit: "
            ).lower()
            if answer in ("1", "2", "3"):
                return concepts[int(answer) - 1]
            if answer == "r":
                text = self.ask_multiline("Describe the demo you want")
                if text:
                    notes.append(text)
                continue
            if answer == "q":
                raise Quit()
            if answer == "s":
                self.record_skip(idea, self.ask("Reason (optional): "))
                return None
            self.warn("no valid selection")

    def generate_page(self, idea, novelty, concept, *, feedback) -> Page | None:
        notes = list(feedback)
        automatic = 1
        while True:
            self.out("Generating page and demo (about 10–20 model and API calls) ...")
            try:
                page = self.resilient(
                    "Page generation",
                    lambda: create_page(
                        idea,
                        novelty,
                        self.provider,
                        feedback=notes,
                        demo_concept=concept,
                        warn=self.warn,
                    ),
                )
                if any(fingerprint(old) == fingerprint(page) for old in self.known):
                    raise Rejected("expanded_scenario_duplicate")
                self.generated += 1
                return page
            except (Rejected, StageError, ValidationError) as exc:
                reason = "page_schema_failed" if isinstance(exc, ValidationError) else str(exc)
                detail = getattr(exc, "detail", None)
                self.rejected[reason.split(":")[0]] += 1
                self.warn(
                    f"generation failed: {brief(reason, 100)}"
                    + (f" [{brief(detail, 500)}]" if detail else "")
                )
                if automatic:
                    automatic -= 1
                    notes.append(
                        f"A previous attempt failed automatic verification: {reason} {detail or ''}"
                    )
                    self.out("Retrying automatically with that failure as feedback ...")
                    continue
                answer = self.ask(
                    "[r]etry with feedback, [t]ry again as is, [s]kip idea, [q]uit: "
                ).lower()
                if answer == "r":
                    text = self.ask_multiline("Feedback for the next attempt")
                    if text:
                        notes.append(text)
                elif answer == "t":
                    continue
                elif answer == "q":
                    raise Quit() from None
                else:
                    self.record_skip(idea, self.ask("Reason (optional): "))
                    return None

    # ----- drafts ----------------------------------------------------------------------

    def taxonomy(self, page: Page) -> tuple[str | None, list[str]]:
        try:
            chosen = self.resilient(
                "Choosing category and tags",
                lambda: choose_taxonomy(page, self.categories, self.provider),
            )
            return chosen.category, list(chosen.tags)
        except (Rejected, StageError, ValidationError) as exc:
            self.warn(f"no category or tags assigned ({str(exc)[:120]}); edit them later")
            return None, []

    def save_draft(
        self, idea, novelty, concept, page, *, attempt, feedback, created_at=None, listing=None
    ):
        category, tags = listing or self.taxonomy(page)
        meta = {
            "headline": self.origins.get(page.slug),
            "review": {
                "idea": idea.model_dump(),
                "concept": concept.model_dump(exclude_none=True),
                "feedback": feedback,
                "attempt": attempt,
                "created_at": created_at or now(),
            },
        }
        saved = self.resilient(
            "Saving the draft",
            lambda: self.api.put(
                page.model_dump(exclude_none=True),
                status="draft",
                category=category,
                tags=tags,
                meta=meta,
                novelty=novelty,
            ),
        )
        if not any(item.slug == page.slug for item in self.known):
            self.known.append(Idea.model_validate(compact(page)))
        return {
            "slug": page.slug,
            "idea": meta["review"]["idea"],
            "concept": meta["review"]["concept"],
            "page": page.model_dump(exclude_none=True),
            "novelty": novelty,
            "feedback": feedback,
            "attempt": attempt,
            "created_at": meta["review"]["created_at"],
            "category": category,
            "tags": tags,
            "revision": saved["revision"],
        }

    def draft_from_api(self, item: dict) -> dict | None:
        review = (item.get("inspiration") or {}).get("review") or {}
        try:
            Page.model_validate(item["page"])
            Idea.model_validate(review["idea"])
            DemoConcept.model_validate(review["concept"])
        except (ValidationError, KeyError, TypeError):
            self.warn(f"draft {item.get('slug')} has no review state and was ignored")
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

    def read_draft(self, slug: str) -> dict | None:
        for item in self.resilient("Loading drafts", self.api.drafts):
            if item["slug"] == slug:
                return self.draft_from_api(item)
        return None

    def pending_drafts(self) -> list[dict]:
        drafts = [
            draft
            for item in self.resilient("Loading drafts", self.api.drafts)
            if (draft := self.draft_from_api(item)) is not None
        ]
        if drafts:
            self.out(f"Resuming {len(drafts)} pending draft(s).")
        return drafts

    def preview_url(self, slug: str) -> str:
        token = self.resilient("Creating a preview link", lambda: self.api.preview_token(slug))
        return f"{self.preview_base}/use-cases/{slug}?preview={token}"

    def preview(self, slug: str):
        url = self.preview_url(slug)
        self.out(f"Preview: {url}")
        if self.open_browser:
            with self.budget.paused():
                self.opener(url)

    def review_draft(self, draft: dict):
        idea = Idea.model_validate(draft["idea"])
        concept = DemoConcept.model_validate(draft["concept"])
        page = Page.model_validate(draft["page"])
        novelty = float(draft["novelty"])
        feedback = list(draft.get("feedback", []))
        attempt = int(draft.get("attempt", 1))
        created_at = draft.get("created_at")
        listing = (draft.get("category"), list(draft.get("tags") or []))
        loaded = draft.get("revision")
        self.preview(page.slug)
        while True:
            # The preview shows the stored draft; if another session changed it since it was
            # loaded, switch to that version before any decision.
            latest = self.read_draft(page.slug)
            if latest is not None and latest.get("revision") != loaded:
                page = Page.model_validate(latest["page"])
                concept = DemoConcept.model_validate(latest["concept"])
                feedback = list(latest.get("feedback", []))
                attempt = int(latest.get("attempt", attempt))
                listing = (latest.get("category"), list(latest.get("tags") or []))
                loaded = latest.get("revision")
                self.warn(f"the draft changed elsewhere; now reviewing attempt {attempt}")
            self.header(f"Review: {page.slug} (attempt {attempt})")
            self.out(f"Title: {page.seo.title}")
            self.out(f"Demo:  {page.demo.title if page.demo else 'none'}")
            tags = ", ".join(listing[1]) or "none"
            self.out(f"Listed under: {listing[0] or 'no category'} · tags: {tags}")
            answer = self.ask("[a]pprove  [f]eedback  [s]kip  [o]pen  [q]uit: ").lower()
            if answer == "a":
                self.approve(page)
                return
            if answer == "o":
                self.preview(page.slug)
                continue
            if answer == "q":
                raise Quit()
            if answer == "s":
                self.record_skip(idea, self.ask("Reason (optional): "), archive=True)
                return
            if answer != "f":
                self.warn("no valid selection")
                continue
            scope = self.ask("Regenerate [t]ext, [d]emo, [c]oncept, or [b]oth text and demo: ")
            scope = {"t": "text", "d": "demo", "c": "concept", "b": "both"}.get(scope.lower())
            if scope is None:
                self.warn("no valid selection")
                continue
            text = self.ask_multiline("Your feedback")
            if not text and scope != "concept":
                self.warn("empty feedback; nothing regenerated")
                continue
            feedback.append({"at": now(), "scope": scope, "text": text})
            text_notes = [f["text"] for f in feedback if f["scope"] in ("text", "both")]
            demo_notes = [f["text"] for f in feedback if f["scope"] in ("demo", "both", "concept")]
            try:
                self.out("Regenerating ...")
                current = page
                if scope == "text":
                    fresh = self.resilient(
                        "Text regeneration",
                        lambda: create_page(idea, novelty, self.provider, feedback=text_notes),
                    )
                    page = fresh.model_copy(update={"demo": current.demo})
                elif scope == "demo":
                    page = self.resilient(
                        "Demo regeneration",
                        lambda: rebuild_demo(
                            current, concept, self.provider, demo_notes, warn=self.warn
                        ),
                    )
                elif scope == "concept":
                    chosen = self.choose_concept(idea, demo_notes)
                    if chosen is None:
                        self.resilient("Archiving the draft", lambda: self.api.archive(page.slug))
                        return
                    concept = chosen
                    page = self.resilient(
                        "Demo regeneration",
                        lambda: rebuild_demo(
                            current, chosen, self.provider, demo_notes, warn=self.warn
                        ),
                    )
                else:
                    page = self.resilient(
                        "Page regeneration",
                        lambda: create_page(
                            idea,
                            novelty,
                            self.provider,
                            feedback=text_notes + demo_notes,
                            demo_concept=concept,
                            warn=self.warn,
                        ),
                    )
                self.generated += 1
            except (Rejected, StageError, ValidationError) as exc:
                reason = "page_schema_failed" if isinstance(exc, ValidationError) else str(exc)
                detail = getattr(exc, "detail", None)
                self.rejected[reason.split(":")[0]] += 1
                self.warn(
                    f"regeneration failed: {brief(reason, 100)}"
                    + (f" [{brief(detail, 500)}]" if detail else "")
                    + "; the draft is unchanged"
                )
                continue
            attempt += 1
            draft = self.save_draft(
                idea,
                novelty,
                concept,
                page,
                attempt=attempt,
                feedback=feedback,
                created_at=created_at,
                listing=listing,
            )
            loaded = draft["revision"]
            self.preview(page.slug)

    # ----- approval --------------------------------------------------------------------

    def approve(self, page: Page):
        if page.demo is None:
            raise ReviewError("a page without a verified demo cannot be approved")
        run_id = f"{self.session_id}-{self.approved + 1}"
        self.resilient("Publishing", lambda: self.api.publish(page.slug))
        self.approved += 1
        self.published.append(page.slug)
        report = self.report(run_id, "prepared", "approved_by_reviewer")
        try:
            self.resilient(
                "Recording the run", lambda: self.api.record_run(report.model_dump(mode="json"))
            )
        except ContentApiError as exc:
            self.warn(f"the run report was not recorded ({exc}); the page is published")
        self.out(f"Published {page.slug}: {self.preview_base}/use-cases/{page.slug}")


def compact_fields(item: dict) -> dict:
    return {key: item[key] for key in Idea.model_fields}


def generator_version() -> str:
    """The generator's git revision for run reports (hex), or zeros outside a checkout."""
    try:
        value = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "0000000"
    return value if re.fullmatch(r"[0-9a-f]{7,64}", value) else "0000000"
