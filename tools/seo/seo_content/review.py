"""Interactive local review: propose ideas, generate a page with a demo, preview it in the
running Next.js dev server, then approve (append + commit), give feedback, or skip."""

import json
import os
import random
import re
import secrets
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from pydantic import ValidationError

from .catalog import (
    Catalog,
    atomic_write,
    fingerprint,
    release_page,
    sha256,
)
from .demo import propose_concepts
from .models import DemoConcept, Idea, Page, Release, Report
from .novelty import Rejected, novelty_scan
from .pipeline import create_page, now, propose_ideas, rebuild_demo
from .providers import Budget, BudgetExhausted, ProviderError, Providers, StageError

RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
CONTENT = "content/use-cases"
MAX_IDEA_ROUNDS = 10
RETRY_DELAYS = (10, 30)
DUPLICATE = 0.8
SIMILAR = 0.2
LINE = "─" * 72


class ReviewError(Exception):
    pass


class Quit(Exception):
    """The reviewer ended the session; pending drafts stay on disk."""


def session_id_now():
    return datetime.now(UTC).strftime("local-%Y%m%dT%H%M%SZ")


class Git:
    def __init__(self, root: Path):
        self.root = root

    def run(self, *args, check=True):
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=check
        )

    def output(self, *args) -> str:
        return self.run(*args).stdout.strip()

    def changed_content_paths(self) -> list[str]:
        paths = []
        for line in self.run("status", "--porcelain", "--", CONTENT).stdout.splitlines():
            path = line[3:].split(" -> ")[-1].strip().strip('"')
            if path.startswith(f"{CONTENT}/drafts/"):
                continue
            paths.append(path)
        return paths


class DevServer:
    """Detect, optionally start, warm up and stop `next dev` for draft previews."""

    def __init__(self, url: str, root: Path, out, *, start_allowed=True):
        self.url = url.rstrip("/")
        self.root = root
        self.out = out
        self.start_allowed = start_allowed
        self.process = None

    def page_url(self, slug: str) -> str:
        return f"{self.url}/use-cases/{slug}"

    @property
    def port(self) -> int:
        return urllib.parse.urlsplit(self.url).port or 3000

    def _get(self, path: str, timeout: float) -> tuple[int | None, str]:
        request = urllib.request.Request(self.url + path, headers={"Cache-Control": "no-cache"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(400_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, ""
        except (urllib.error.URLError, OSError, ValueError):
            return None, ""

    def is_up(self, timeout=15) -> bool:
        status, body = self._get("/use-cases", timeout)
        return status == 200 and "use-case" in body

    def listening(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=2):
                return True
        except OSError:
            return False

    def ensure(self, ask=None) -> bool:
        if self.is_up():
            self.out(f"Dev server detected at {self.url}")
            return True
        if self.listening():
            # Something holds the port but does not render (for example a dev server whose
            # build directory was replaced). Starting another would move it to a new port.
            self.out(f"A server on port {self.port} is not rendering pages correctly.")
            answer = (
                ask(
                    f"[r]estart the process on port {self.port}, [c]ontinue without previews: "
                ).lower()
                if ask
                else "c"
            )
            if answer != "r" or not self.kill_listener():
                self.out("Continuing without automatic previews; restart `npm run dev:web`.")
                return False
        if not self.start_allowed:
            self.out(f"No dev server at {self.url}; run `npm run dev:web` for previews.")
            return False
        self.out(f"Starting `npm run dev:web` for previews at {self.url} ...")
        self.process = subprocess.Popen(
            ["npm", "run", "dev:web", "--", "--port", str(self.port)],
            cwd=self.root,
            # The dev server must never read the reviewer's keystrokes.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            if self.is_up(timeout=5):
                self.out("Dev server is ready.")
                return True
            time.sleep(2)
        self.out("Dev server did not become ready; previews must be opened manually.")
        return False

    def kill_listener(self) -> bool:
        try:
            pids = subprocess.run(
                ["lsof", "-t", f"-iTCP:{self.port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.split()
        except (OSError, subprocess.SubprocessError):
            return False
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError, PermissionError):
                pass
        for _ in range(20):
            if not self.listening():
                return True
            time.sleep(0.5)
        return False

    def warm(self, slug: str) -> bool:
        # `next dev` compiles on first request and caches generateStaticParams
        # stale-while-revalidate, so a new draft can 404 once; retry until it renders.
        for _ in range(15):
            status, body = self._get(f"/use-cases/{slug}", timeout=120)
            if status == 200 and slug in body:
                return True
            time.sleep(2)
        return False

    def stop(self):
        if self.process is None or self.process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            self.process.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
            try:
                self.process.kill()
            except OSError:
                pass


STAGES = {
    "Ideas": "proposing ideas",
    "DemoConcepts": "proposing demo concepts",
    "Description": "writing intro and problem",
    "DraftExamples": "writing the three examples",
    "Explanation": "writing the solution and limitations",
    "SEO": "writing title and meta description",
    "DemoCode": "writing the interactive demo",
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

    def structured(self, schema, task, context):
        label = STAGES.get(schema.__name__, schema.__name__)
        if schema.__name__ == "DraftExamples" and "failed_examples" in context:
            label = "repairing examples that the API answered differently"
        if schema.__name__ == "DemoCode" and "previous_attempt" in context:
            label = "revising the interactive demo"
        return self._timed(label, lambda: self.provider.structured(schema, task, context))

    def evaluate(self, request):
        keys = list(request.questions)
        if any(key.startswith("duplicate_") for key in keys):
            return self.provider.evaluate(request)
        label = "judging page quality" if "useful" in keys else "running an input on the live API"
        return self._timed(label, lambda: self.provider.evaluate(request))


def brief(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ReviewSession:
    def __init__(
        self,
        content_dir: Path,
        *,
        session_id: str | None = None,
        budget: Budget | None = None,
        provider_factory=Providers,
        repo_root: Path | None = None,
        dev_server=None,
        dev_url="http://localhost:3000",
        start_dev_server=True,
        open_browser=True,
        opener=webbrowser.open,
        auto_select=False,
        max_pages=5,
        prompt=input,
        out=print,
        clock_url="https://api.typesafe.pro/health",
        sleep=time.sleep,
    ):
        self.content_dir = Path(content_dir).resolve()
        self.repo_root = Path(repo_root).resolve() if repo_root else self.content_dir.parents[1]
        self.session_id = session_id or session_id_now()
        self.budget = budget or Budget(max_calls=400, max_seconds=3600)
        self.provider_factory = provider_factory
        self.dev_server = dev_server or DevServer(
            dev_url, self.repo_root, out, start_allowed=start_dev_server
        )
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
        self.git = Git(self.repo_root)
        self.started_at = now()
        self.seed = secrets.randbits(32)
        self.rng = random.Random(self.seed)
        self.rounds = 0
        self.generated = 0
        self.approved = 0
        self.skipped = 0
        self.rejected = Counter()
        self.commits = []
        self.catalog = None
        self.provider = None
        self.source_sha = ""

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
        if self.content_dir.relative_to(self.repo_root).as_posix() != CONTENT:
            raise ReviewError(f"content directory must be {CONTENT} inside the repository")
        try:
            toplevel = Path(self.git.output("rev-parse", "--show-toplevel")).resolve()
        except (subprocess.CalledProcessError, OSError):
            raise ReviewError("not inside a Git repository") from None
        if toplevel != self.repo_root:
            raise ReviewError("repository root does not match the content directory")
        if (self.repo_root / ".git" / "MERGE_HEAD").exists():
            raise ReviewError("finish the merge in progress before reviewing content")
        dirty = [
            path
            for path in self.git.changed_content_paths()
            if path != f"{CONTENT}/review-skips.json"
        ]
        if dirty:
            raise ReviewError(
                "commit or stash these changes in the content catalog first: " + ", ".join(dirty)
            )
        self.source_sha = self.git.output("rev-parse", "HEAD")
        self.catalog = Catalog(self.content_dir)
        self.provider = ProgressProvider(self.provider_factory(self.budget), self.out)
        self.check_clock()
        with self.budget.paused():
            self.dev_server.ensure(self.ask)

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
            "Press q at any prompt or Ctrl+C at any time to stop. Approved pages are already "
            "committed; unfinished drafts stay in content/use-cases/drafts/ (--resume)."
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
            self.out("\nSession ended by reviewer; pending drafts remain in drafts/.")
        except BudgetExhausted:
            self.out("\nSession budget exhausted; pending drafts remain in drafts/.")
        except ProviderError as exc:
            self.out(f"\nProvider failure: {self.describe(exc)}; pending drafts remain in drafts/.")
        except ReviewError as exc:
            self.out(f"\nSession stopped: {exc}; pending drafts remain in drafts/.")
        finally:
            try:
                self.commit_skips()
            finally:
                self.dev_server.stop()
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
        for sha, message in self.commits:
            self.out(f"  {sha} {message}")
        if self.commits:
            self.out("Run `git push` to deploy the approved pages.")
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
            catalog_hash=self.catalog.manifest.catalog_hash,
            mode="review",
            approved_count=self.approved,
            skipped_count=self.skipped,
        )

    # ----- ideas -----------------------------------------------------------------------

    def skips(self) -> list[dict]:
        path = self.content_dir / "review-skips.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_bytes())
            return list(data["skipped"])
        except (ValueError, KeyError, TypeError):
            raise ReviewError("review-skips.json is corrupt") from None

    def record_skip(self, idea: Idea, reason: str):
        skipped = self.skips()
        skipped.append(
            {
                "slug": idea.slug,
                "fingerprint": fingerprint(idea),
                "task_type": idea.task_type,
                "summary": idea.summary,
                "decision": idea.decision,
                "reason": reason or "",
                "at": now(),
            }
        )
        atomic_write(
            self.content_dir / "review-skips.json", {"schema_version": 1, "skipped": skipped}
        )
        self.skipped += 1
        self.out(f"Skipped {idea.slug}.")

    def fill_pool(self):
        """Propose ideas and keep only those that are not duplicates of the catalog."""
        while not self.pool:
            if self.rounds >= MAX_IDEA_ROUNDS:
                raise ReviewError("too many idea rounds; end the session and start again")
            self.rounds += 1
            self.out(f"\nProposing ideas (round {self.rounds}) ...")
            skipped = self.skips()
            try:
                ideas = self.resilient(
                    "Idea generation",
                    lambda: propose_ideas(
                        self.catalog.pages,
                        self.provider,
                        self.rng,
                        [{k: s[k] for k in ("summary", "task_type", "decision")} for s in skipped],
                        self.proposed[-60:],
                    ),
                )
            except StageError:
                self.rejected["idea_stage_failed"] += 1
                self.warn("the model did not return valid ideas; trying another round")
                continue
            taken = {p.slug for p in self.catalog.pages}
            taken.update(d["slug"] for d in self.pending_draft_files())
            skipped_prints = {s["fingerprint"] for s in skipped}
            fresh = []
            for idea in ideas.ideas:
                self.proposed.append({"slug": idea.slug, "summary": idea.summary})
                if idea.slug in taken or fingerprint(idea) in skipped_prints:
                    continue
                taken.add(idea.slug)
                fresh.append(idea)
            self.out(f"Checking {len(fresh)} ideas against the catalog for duplicates ...")
            hidden = 0
            for idea in fresh:
                try:
                    duplicate, similar = self.resilient(
                        "Duplicate check",
                        lambda idea=idea: novelty_scan(idea, self.catalog.pages, self.provider),
                    )
                except Rejected as exc:
                    self.rejected[str(exc)] += 1
                    hidden += 1
                    continue
                if duplicate >= DUPLICATE:
                    self.rejected["semantic_duplicate"] += 1
                    hidden += 1
                    continue
                self.pool.append((idea, 1 - duplicate, similar if duplicate > SIMILAR else None))
            if hidden:
                self.out(f"Hid {hidden} idea(s) that duplicate existing pages.")
            if not self.pool:
                self.warn("every idea duplicated the catalog; asking for new ones")

    def pick_candidate(self) -> tuple[Idea, float, str | None]:
        while True:
            self.fill_pool()
            if self.auto_select:
                return self.pool.pop(0)
            self.header("Candidate ideas")
            for number, (idea, novelty, similar) in enumerate(self.pool, 1):
                self.out(f"{number:>2}. {idea.slug}  [{idea.industry} · {idea.task_type}]")
                self.out(f"    {brief(idea.summary, 110)}")
                if similar:
                    self.out(
                        f"    ⚠ partly similar to /use-cases/{similar} (novelty {novelty:.2f})"
                    )
            answer = self.ask("Pick an idea [number], [n]ew ideas, [q]uit: ").lower()
            if answer == "q":
                raise Quit()
            if answer == "n":
                self.pool.clear()
                continue
            if answer.isdigit() and 1 <= int(answer) <= len(self.pool):
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
                if any(fingerprint(old) == fingerprint(page) for old in self.catalog.pages):
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

    def draft_path(self, slug: str) -> Path:
        return self.content_dir / "drafts" / f"{slug}.json"

    def save_draft(self, idea, novelty, concept, page, *, attempt, feedback, created_at=None):
        draft = {
            "schema_version": 1,
            "status": "pending",
            "attempt": attempt,
            "idea": idea.model_dump(),
            "novelty": novelty,
            "concept": concept.model_dump(exclude_none=True),
            "page": page.model_dump(exclude_none=True),
            "feedback": feedback,
            "created_at": created_at or now(),
            "updated_at": now(),
        }
        atomic_write(self.draft_path(page.slug), draft)
        return draft

    def read_draft(self, slug: str) -> dict | None:
        try:
            data = json.loads(self.draft_path(slug).read_bytes())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def pending_draft_files(self) -> list[dict]:
        directory = self.content_dir / "drafts"
        if not directory.is_dir():
            return []
        drafts = []
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_bytes())
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("status") == "pending":
                data["slug"] = path.stem
                drafts.append(data)
        return drafts

    def pending_drafts(self) -> list[dict]:
        drafts = []
        for data in self.pending_draft_files():
            try:
                Page.model_validate(data["page"])
                Idea.model_validate(data["idea"])
                DemoConcept.model_validate(data["concept"])
            except (ValidationError, KeyError, TypeError):
                self.warn(f"draft {data['slug']} is invalid and was ignored")
                continue
            drafts.append(data)
        if drafts:
            self.out(f"Resuming {len(drafts)} pending draft(s).")
        return drafts

    def preview(self, slug: str):
        url = self.dev_server.page_url(slug)
        with self.budget.paused():
            if not self.dev_server.warm(slug):
                self.warn("the dev server did not render the draft yet; try [o]pen again")
            self.out(f"Preview: {url}")
            if self.open_browser:
                self.opener(url)

    def review_draft(self, draft: dict):
        idea = Idea.model_validate(draft["idea"])
        concept = DemoConcept.model_validate(draft["concept"])
        page = Page.model_validate(draft["page"])
        novelty = float(draft["novelty"])
        feedback = list(draft.get("feedback", []))
        attempt = int(draft.get("attempt", 1))
        created_at = draft.get("created_at")
        loaded = draft.get("updated_at")
        self.preview(page.slug)
        while True:
            # The browser always shows the file on disk; if it changed since it was loaded
            # (another session or a manual regeneration), switch to it before any decision.
            latest = self.read_draft(page.slug)
            if latest is not None and latest.get("updated_at") != loaded:
                try:
                    page = Page.model_validate(latest["page"])
                    concept = DemoConcept.model_validate(latest["concept"])
                    feedback = list(latest.get("feedback", []))
                    attempt = int(latest.get("attempt", attempt))
                    loaded = latest.get("updated_at")
                    self.warn(f"the draft changed on disk; now reviewing attempt {attempt}")
                except (ValidationError, KeyError, TypeError, ValueError):
                    self.warn("the draft on disk changed but is invalid; keeping this version")
                    loaded = latest.get("updated_at")
            self.header(f"Review: {page.slug} (attempt {attempt})")
            self.out(f"Title: {page.seo.title}")
            self.out(f"Demo:  {page.demo.title if page.demo else 'none'}")
            answer = self.ask("[a]pprove  [f]eedback  [s]kip  [o]pen  [q]uit: ").lower()
            if answer == "a":
                self.approve(page)
                self.draft_path(page.slug).unlink(missing_ok=True)
                return
            if answer == "o":
                self.preview(page.slug)
                continue
            if answer == "q":
                raise Quit()
            if answer == "s":
                self.record_skip(idea, self.ask("Reason (optional): "))
                self.draft_path(page.slug).unlink(missing_ok=True)
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
                        self.draft_path(page.slug).unlink(missing_ok=True)
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
            )
            loaded = draft["updated_at"]
            self.preview(page.slug)

    # ----- approval --------------------------------------------------------------------

    def approve(self, page: Page):
        if page.demo is None:
            raise ReviewError("a page without a verified demo cannot be approved")
        run_id = f"{self.session_id}-{self.approved + 1}"
        self.catalog.add(page)
        release = Release(
            run_id=run_id,
            source_sha=self.source_sha,
            catalog_hash=self.catalog.manifest.catalog_hash,
            generated_at=now(),
            pages=[release_page(p) for p in self.catalog.pages],
        )
        atomic_write(self.content_dir / "release.json", release.model_dump())
        self.catalog.validate_release()
        self.approved += 1
        report = self.report(run_id, "prepared", "approved_by_reviewer")
        atomic_write(
            self.content_dir / "runs" / (sha256(run_id.encode())[:24] + ".json"),
            {
                "schema_version": 1,
                "complete": True,
                "report": report.model_dump(),
                "release": release.model_dump(),
            },
        )
        self.commit(f"chore(content): add use case {page.slug}")
        self.out(f"Approved {page.slug} ({len(self.catalog.pages)} pages in the catalog).")

    def commit(self, message: str):
        paths = self.git.changed_content_paths()
        if not paths:
            return
        self.git.run("add", "--", *paths)
        self.git.run("commit", "-q", "-m", message, "--", *paths)
        committed = self.git.output("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        outside = [p for p in committed.splitlines() if not p.startswith(f"{CONTENT}/")]
        if outside:
            raise ReviewError("commit touched files outside the content catalog: " + str(outside))
        sha = self.git.output("rev-parse", "--short", "HEAD")
        self.commits.append((sha, message))
        self.out(f"Committed {sha}: {message}")

    def commit_skips(self):
        if f"{CONTENT}/review-skips.json" in self.git.changed_content_paths():
            self.commit("chore(content): record skipped use-case ideas")
