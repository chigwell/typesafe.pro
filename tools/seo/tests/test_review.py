import json
import subprocess
import time

import pytest
from conftest import FakeFeed, FakeProvider, idea

from seo_content.catalog import Catalog, CatalogError, atomic_write, canonical, sha256
from seo_content.providers import Budget
from seo_content.review import RUN_ID, ReviewError, ReviewSession


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    content = root / "content" / "use-cases"
    checksum = sha256(canonical([]))
    atomic_write(
        content / "manifest.json",
        {"schema_version": 1, "total": 0, "shards": [], "catalog_hash": checksum},
    )
    atomic_write(
        content / "release.json",
        {
            "schema_version": 1,
            "run_id": "initial",
            "source_sha": "initial",
            "catalog_hash": checksum,
            "generated_at": "2026-09-25T00:00:00Z",
            "pages": [],
        },
    )
    (root / ".gitignore").write_text("content/use-cases/drafts/\n")
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "initial")
    return root


class StubDevServer:
    def __init__(self):
        self.warmed = []
        self.stopped = False

    def page_url(self, slug):
        return f"http://stub/use-cases/{slug}"

    def ensure(self, ask=None):
        return True

    def warm(self, slug):
        self.warmed.append(slug)
        return True

    def stop(self):
        self.stopped = True


def session(repo, answers, **options):
    replies = iter(answers)
    lines = []
    providers = []

    def factory(budget):
        provider = FakeProvider(budget)
        providers.append(provider)
        return provider

    review = ReviewSession(
        repo / "content" / "use-cases",
        budget=Budget(max_calls=400, max_seconds=600),
        provider_factory=factory,
        repo_root=repo,
        dev_server=StubDevServer(),
        open_browser=False,
        prompt=lambda text: next(replies),
        out=lines.append,
        clock_url=None,
        sleep=lambda seconds: None,
        **{"max_pages": 1, "session_id": "local-test", "inspiration": FakeFeed(), **options},
    )
    review.lines = lines
    review.providers = providers
    return review


def committed_paths(root):
    return git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()


def test_approve_appends_releases_and_commits(repo):
    review = session(repo, ["1", "1", "a"])
    report = review.run()
    catalog = Catalog(repo / "content" / "use-cases")
    assert len(catalog.pages) == 1 and catalog.pages[0].demo is not None
    release = catalog.validate_release()
    assert [p.slug for p in release.pages] == [catalog.pages[0].slug]
    assert release.run_id == "local-test-1" and RUN_ID.fullmatch(release.run_id)
    assert release.source_sha == git(repo, "rev-parse", "HEAD~1")
    checkpoint = repo / "content" / "use-cases" / "runs" / (sha256(b"local-test-1")[:24] + ".json")
    saved = json.loads(checkpoint.read_bytes())
    assert saved["report"]["mode"] == "review" and saved["report"]["approved_count"] == 1
    assert not list((repo / "content" / "use-cases" / "drafts").glob("*.json"))
    assert git(repo, "log", "-1", "--format=%s") == "chore(content): add use case route-workshop-10"
    assert committed_paths(repo) and all(
        p.startswith("content/use-cases/") for p in committed_paths(repo)
    )
    assert git(repo, "status", "--porcelain") == ""
    assert report.approved_count == 1 and report.status == "prepared"
    assert review.dev_server.warmed == ["route-workshop-10"] and review.dev_server.stopped


def test_demo_feedback_regenerates_only_the_demo(repo):
    review = session(repo, ["1", "1", "f", "d", "Use emoji instead", "", "q"])
    review.run()
    provider = review.providers[0]
    drafts = list((repo / "content" / "use-cases" / "drafts").glob("*.json"))
    assert len(drafts) == 1
    draft = json.loads(drafts[0].read_bytes())
    assert draft["status"] == "pending" and draft["attempt"] == 2
    assert draft["feedback"] == [
        {**draft["feedback"][0], "scope": "demo", "text": "Use emoji instead"}
    ]
    assert provider.demo_attempts == 2 and provider.demo_feedback == ["Use emoji instead"]
    assert draft["page"]["demo"]["title"] == "Mood bar 1"
    assert git(repo, "log", "--format=%s").splitlines() == ["initial"]
    assert Catalog(repo / "content" / "use-cases").pages == []


def test_text_feedback_keeps_the_demo(repo):
    review = session(repo, ["1", "1", "f", "t", "Shorter intro", "", "q"])
    review.run()
    provider = review.providers[0]
    assert provider.demo_attempts == 1
    draft = json.loads(
        next((repo / "content" / "use-cases" / "drafts").glob("*.json")).read_bytes()
    )
    assert draft["attempt"] == 2 and draft["page"]["demo"]["title"] == "Mood bar 1"


def test_skip_is_recorded_committed_and_excluded_from_later_rounds(repo):
    review = session(repo, ["1", "1", "s", "Too generic", "q"])
    report = review.run()
    skips = json.loads((repo / "content" / "use-cases" / "review-skips.json").read_bytes())
    assert [item["slug"] for item in skips["skipped"]] == ["route-workshop-10"]
    assert skips["skipped"][0]["reason"] == "Too generic"
    assert git(repo, "log", "-1", "--format=%s") == "chore(content): record skipped use-case ideas"
    assert committed_paths(repo) == ["content/use-cases/review-skips.json"]
    assert report.skipped_count == 1 and report.approved_count == 0
    assert any("route-workshop-10" in line for line in review.lines)
    assert not list((repo / "content" / "use-cases" / "drafts").glob("*.json"))


def test_resume_reviews_pending_draft_without_new_ideas(repo):
    session(repo, ["1", "1", "q"]).run()
    assert list((repo / "content" / "use-cases" / "drafts").glob("*.json"))
    review = session(repo, ["a"])
    review.run(resume=True)
    assert review.providers[0].round == 0
    assert len(Catalog(repo / "content" / "use-cases").pages) == 1
    assert git(repo, "log", "-1", "--format=%s").startswith("chore(content): add use case")


def test_each_approval_gets_its_own_run_id(repo):
    review = session(repo, ["1", "1", "a", "1", "1", "a"], max_pages=2)
    review.run()
    catalog = Catalog(repo / "content" / "use-cases")
    assert len(catalog.pages) == 2
    assert catalog.validate_release().run_id == "local-test-2"
    runs = sorted((repo / "content" / "use-cases" / "runs").glob("*.json"))
    assert len(runs) == 2
    assert len(git(repo, "log", "--format=%s").splitlines()) == 3


def test_auto_select_needs_no_choices(repo):
    review = session(repo, ["a"], auto_select=True)
    review.run()
    assert len(Catalog(repo / "content" / "use-cases").pages) == 1


def test_dirty_catalog_refuses_to_start(repo):
    (repo / "content" / "use-cases" / "release.json").write_text("{}")
    with pytest.raises(ReviewError, match="commit or stash"):
        session(repo, []).run()


def test_skips_file_alone_does_not_block_start(repo):
    atomic_write(
        repo / "content" / "use-cases" / "review-skips.json",
        {"schema_version": 1, "skipped": []},
    )
    review = session(repo, ["q"])
    review.run()
    assert git(repo, "log", "-1", "--format=%s") == "chore(content): record skipped use-case ideas"


def test_merge_in_progress_refuses_to_start(repo):
    (repo / ".git" / "MERGE_HEAD").write_text("deadbeef\n")
    with pytest.raises(ReviewError, match="merge"):
        session(repo, []).run()


def test_corrupt_catalog_is_hard_failure(repo):
    (repo / "content" / "use-cases" / "manifest.json").write_text("{}")
    git(repo, "commit", "-q", "-am", "corrupt")
    with pytest.raises(CatalogError):
        session(repo, []).run()


def test_invalid_session_id_rejected(repo):
    with pytest.raises(ReviewError, match="session ID"):
        session(repo, [], session_id="local-2026-09-27T10:00:00Z").run()


def test_generation_failure_offers_feedback_retry(repo):
    class OneBadDemo(FakeProvider):
        def evaluate(self, request):
            if self.demo_attempts <= 6 and "mood" in request.questions:
                self.example_probability = 0.2
            else:
                self.example_probability = 0.95
            return super().evaluate(request)

    review = session(repo, ["1", "1", "r", "Try a simpler visual", "", "a"])
    review.provider_factory = lambda budget: OneBadDemo(budget)
    report = review.run()
    assert report.approved_count == 1
    assert report.rejections.get("demo_sample_failed") == 2


def _duplicate_provider(budget):
    provider = FakeProvider(budget)
    provider.duplicate_probability = 0.9
    return provider


class ScriptedNovelty(FakeProvider):
    """Duplicate probabilities per candidate, consumed in order; default distinct."""

    def __init__(self, budget=None, values=()):
        super().__init__(budget)
        self.values = list(values)

    def evaluate(self, request):
        if any(key.startswith("duplicate_") for key in request.questions):
            self.duplicate_probability = self.values.pop(0) if self.values else 0.05
        return super().evaluate(request)


def seeded(repo):
    session(repo, ["1", "1", "a"]).run()


def test_duplicates_are_hidden_and_similar_ideas_flagged(repo):
    seeded(repo)
    review = session(repo, ["q"])
    review.provider_factory = lambda budget: ScriptedNovelty(budget, [0.9, 0.9, 0.5])
    report = review.run()
    shown = [line for line in review.lines if ". route-workshop-" in line]
    assert len(shown) == 7
    assert any("Hid 2 idea(s)" in line for line in review.lines)
    assert any(
        "partly similar to /use-cases/route-workshop-10 (novelty 0.50)" in line
        for line in review.lines
    )
    assert report.rejections == {"semantic_duplicate": 2}


def test_reviewer_can_accept_a_partly_similar_idea(repo):
    seeded(repo)
    # Partly similar ideas are listed after the clearly new ones (9 candidates here).
    review = session(repo, ["9", "1", "a"])
    review.provider_factory = lambda budget: ScriptedNovelty(budget, [0.5])
    review.run()
    pages = Catalog(repo / "content" / "use-cases").pages
    assert len(pages) == 2 and pages[1].verification.novelty_probability == 0.5


def test_remaining_ideas_stay_available_after_one_is_used(repo):
    review = session(repo, ["1", "1", "s", "", "1", "1", "a"], max_pages=1)
    review.run()
    offers = [line for line in review.lines if line.startswith(" 1. ")]
    assert offers[0].startswith(" 1. route-workshop-10") and offers[1].startswith(
        " 1. route-workshop-11"
    )
    assert review.providers[0].round == 1


def test_only_duplicates_request_a_new_round_automatically(repo):
    seeded(repo)
    review = session(repo, ["q"])
    review.provider_factory = lambda budget: ScriptedNovelty(budget, [0.95] * 10)
    review.run()
    assert any("no new ideas survived" in line for line in review.lines)
    assert any("round 2" in line for line in review.lines)


def test_transient_provider_failures_are_retried(repo):
    from seo_content.providers import ProviderError

    class Flaky(FakeProvider):
        failures = 2

        def structured(self, schema, task, context, **options):
            if self.failures:
                self.failures -= 1
                error = ProviderError("llm_provider_unavailable")
                error.detail = "provider_timeout"
                raise error
            return super().structured(schema, task, context)

    review = session(repo, ["1", "1", "a"])
    review.provider_factory = Flaky
    report = review.run()
    assert report.approved_count == 1
    assert sum("retrying in" in line for line in review.lines) == 2
    assert any("(provider_timeout)" in line for line in review.lines)


def test_persistent_provider_failure_asks_and_can_quit(repo):
    from seo_content.providers import ProviderError

    class Down(FakeProvider):
        def structured(self, schema, task, context, **options):
            raise ProviderError("llm_provider_unavailable")

    review = session(repo, ["q"])
    review.provider_factory = Down
    report = review.run()
    assert report.approved_count == 0
    assert any("Session ended by reviewer" in line for line in review.lines)


def test_credentials_errors_are_not_retried(repo):
    from seo_content.providers import ProviderError

    class Unauthorized(FakeProvider):
        def structured(self, schema, task, context, **options):
            raise ProviderError("provider_http_401", retryable=False)

    review = session(repo, [])
    review.provider_factory = Unauthorized
    review.run()
    assert any("Provider failure: provider_http_401" in line for line in review.lines)
    assert not any("retrying" in line for line in review.lines)


def test_failed_page_is_retried_automatically_once(repo):
    class QualityOnce(FakeProvider):
        judged = 0

        def evaluate(self, request):
            if "useful" in request.questions:
                self.judged += 1
                self.quality_probability = 0.5 if self.judged == 1 else 0.95
            return super().evaluate(request)

    review = session(repo, ["1", "1", "a"])
    review.provider_factory = QualityOnce
    report = review.run()
    assert report.approved_count == 1
    # A low quality score is now repaired in place instead of regenerating the page.
    assert report.rejections == {}
    assert any("revising the text" in line for line in review.lines)
    assert not any("Retrying automatically" in line for line in review.lines)


def test_budget_pause_excludes_reviewer_time():
    budget = Budget(max_seconds=10)
    with budget.paused():
        time.sleep(0.05)
    assert budget.elapsed < 0.03


def test_dev_server_detects_a_broken_server_without_starting_another(tmp_path):
    import http.server
    import threading

    from seo_content.review import DevServer

    class Broken(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<pre>missing required error components, refreshing...</pre>"
            self.send_response(404)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Broken)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        lines, questions = [], []
        dev = DevServer(f"http://127.0.0.1:{server.server_port}", tmp_path, lines.append)
        assert dev.listening() and not dev.is_up(timeout=2)
        assert dev.ensure(lambda text: questions.append(text) or "c") is False
        assert dev.process is None
        assert questions and "[r]estart" in questions[0]
        assert any("not rendering pages correctly" in line for line in lines)
    finally:
        server.shutdown()


def test_approval_uses_the_draft_currently_on_disk(repo):
    drafts = repo / "content" / "use-cases" / "drafts"
    answers = iter(["1", "1"])
    state = {"edited": False}

    def prompt(text):
        if text.startswith("[a]pprove") and not state["edited"]:
            # Simulates a regeneration written by another process while the session waits.
            path = next(drafts.glob("*.json"))
            data = json.loads(path.read_bytes())
            data["page"]["demo"]["title"] = "Regenerated elsewhere"
            data["attempt"] = 7
            data["updated_at"] = "2099-01-01T00:00:00Z"
            path.write_text(json.dumps(data))
            state["edited"] = True
            return "o"
        if text.startswith("[a]pprove"):
            return "a"
        return next(answers)

    review = session(repo, [])
    review.prompt = prompt
    review.run()
    page = Catalog(repo / "content" / "use-cases").pages[0]
    assert page.demo.title == "Regenerated elsewhere"
    assert any("now reviewing attempt 7" in line for line in review.lines)


def test_ctrl_c_during_generation_ends_cleanly(repo):
    from seo_content.models import DemoCode

    class Interrupted(FakeProvider):
        def structured(self, schema, task, context, **options):
            if schema is DemoCode:
                raise KeyboardInterrupt
            return super().structured(schema, task, context)

    review = session(repo, ["1", "1"])
    review.provider_factory = Interrupted
    report = review.run()
    assert report.approved_count == 0
    assert any("Session ended by reviewer" in line for line in review.lines)
    assert review.dev_server.stopped


def test_progress_is_printed_for_each_stage(repo):
    review = session(repo, ["1", "1", "q"])
    review.run()
    text = "\n".join(review.lines)
    for label in (
        "proposing ideas",
        "writing the three examples",
        "writing the interactive demo",
        "running an input on the live API",
        "judging page quality",
    ):
        assert f"· {label}" in text
    assert "Ctrl+C" in text


def test_headlines_seed_each_round_and_are_shown(repo):
    feed = FakeFeed()
    review = session(repo, ["n", "q"], inspiration=feed)
    review.run()
    text = "\n".join(review.lines)
    assert "Inspiration (test headlines):" in text
    assert "1. Headline 1-0" in text and "1. Headline 2-0" in text
    assert "↳ from: Headline 1-" in text
    assert feed.calls == 2
    contexts = review.providers[0].idea_contexts
    assert [h["title"] for h in contexts[0]["inspiration"]][:2] == ["Headline 1-0", "Headline 1-1"]
    assert contexts[1]["inspiration"][0]["title"] == "Headline 2-0"
    assert contexts[1]["already_proposed"], "second round must see the first round's ideas"


def test_hacker_news_outage_falls_back_to_words(repo):
    review = session(repo, ["q"], inspiration=FakeFeed(fail=True))
    report = review.run()
    assert any("unavailable (offline); using random words" in line for line in review.lines)
    assert report.inspiration_source == "words"
    assert len(review.providers[0].idea_contexts[0]["inspiration"]) == 5


def test_draft_records_its_inspiration_and_catalog_gets_plain_idea(repo):
    session(repo, ["1", "1", "q"]).run()
    draft = json.loads(
        next((repo / "content" / "use-cases" / "drafts").glob("*.json")).read_bytes()
    )
    assert draft["inspiration"]["title"].startswith("Headline 1-")
    assert "inspired_by" not in draft["idea"] and "inspired_by" not in draft["page"]


def test_near_identical_ideas_are_hidden_before_duplicate_checks(repo):
    from seo_content.models import IdeaCandidate, Ideas

    class Clones(FakeProvider):
        def structured(self, schema, task, context, **options):
            if schema is Ideas:
                self.idea_contexts.append(context)
                base = [IdeaCandidate(**idea(1).model_dump())]
                twins = [
                    IdeaCandidate(
                        **idea(1).model_dump()
                        | {"slug": f"route-workshop-copy-{i}", "problem": f"Other {i} problem."}
                    )
                    for i in range(4)
                ]
                others = [IdeaCandidate(**idea(20 + i).model_dump()) for i in range(5)]
                return Ideas(ideas=base + twins + others)
            return super().structured(schema, task, context, **options)

    review = session(repo, ["q"])
    review.provider_factory = Clones
    report = review.run()
    assert report.rejections.get("low_diversity") == 4
    assert any("Hid 4 near-identical idea(s)" in line for line in review.lines)


def test_too_few_clean_ideas_trigger_extra_rounds_with_feedback(repo):
    seeded(repo)
    review = session(repo, ["q"])
    # Every idea of the first two rounds is partly similar; the third round is clean.
    made = []
    review.provider_factory = lambda budget: (
        made.append(ScriptedNovelty(budget, [0.5] * 18)) or made[-1]
    )
    review.run()
    text = "\n".join(review.lines)
    assert "Only 0 clearly new idea(s); asking for more with feedback (1/2)" in text
    contexts = made[0].idea_contexts
    assert len(contexts) == 3
    near = contexts[1]["too_similar_last_time"]
    assert near and near[0]["too_similar_to"]["summary"].startswith("Dispatch case10")
    first = next(i for i, line in enumerate(review.lines) if line.startswith(" 1. "))
    assert "partly similar" not in review.lines[first + 2]


def test_unfocused_ideas_are_hidden_and_best_shown_first(repo):
    class Focus(FakeProvider):
        def evaluate(self, request):
            response = super().evaluate(request)
            for key, answer in response.answers.items():
                if key.startswith("focused_"):
                    index = int(key.split("_")[1])
                    answer.noul = 0.2 if index < 3 else 0.5 + index / 20
            return response

    review = session(repo, ["q"])
    review.provider_factory = Focus
    report = review.run()
    assert report.rejections.get("unfocused") == 3
    assert any("Hid 3 unfocused idea(s)." in line for line in review.lines)
    offers = [line for line in review.lines if ". route-workshop-" in line]
    assert offers[0].startswith(" 1. route-workshop-19")


def test_long_candidate_lists_are_capped_with_more(repo):
    seeded(repo)
    review = session(repo, ["m", "q"])
    # Two partly similar rounds plus a third: far more than twelve candidates.
    review.provider_factory = lambda budget: ScriptedNovelty(budget, [0.5] * 27)
    review.run()
    first = review.lines.index(next(line for line in review.lines if line.startswith(" 1. ")))
    listing = [line for line in review.lines[first:] if ". route-workshop-" in line]
    assert any("more partly similar idea(s): press m" in line for line in review.lines)
    assert any(line.startswith("13. ") for line in listing)
