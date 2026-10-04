import time

import pytest
from conftest import FakeApi, FakeFeed, FakeProvider, idea

from seo_content.providers import Budget
from seo_content.review import RUN_ID, ReviewError, ReviewSession


@pytest.fixture
def repo():
    """The content API the session talks to (in memory)."""
    return FakeApi()


def session(api, answers, **options):
    replies = iter(answers)
    lines = []
    providers = []
    opened = []

    def factory(budget):
        provider = FakeProvider(budget)
        providers.append(provider)
        return provider

    review = ReviewSession(
        budget=Budget(max_calls=400, max_seconds=600),
        provider_factory=factory,
        api_factory=lambda: api,
        preview_base="https://preview.test",
        open_browser=True,
        opener=opened.append,
        prompt=lambda text: next(replies),
        out=lines.append,
        clock_url=None,
        sleep=lambda seconds: None,
        **{"max_pages": 1, "session_id": "local-test", "inspiration": FakeFeed(), **options},
    )
    review.lines = lines
    review.providers = providers
    review.opened = opened
    return review


def test_approve_publishes_through_the_api_and_records_the_run(repo):
    review = session(repo, ["1", "1", "a"])
    report = review.run()
    assert repo.published() == ["route-workshop-10"]
    item = repo.items["route-workshop-10"]
    assert item["category"] == "routing-triage" and item["tags"] == ["workshops", "routing"]
    assert item["page"]["demo"] is not None
    assert item["meta"]["review"]["concept"]["title"] == "Mood bar 1"
    assert item["meta"]["headline"]["title"].startswith("Headline 1-")
    run = repo.runs[0]
    assert run["run_id"] == "local-test-1" and RUN_ID.fullmatch(run["run_id"])
    assert run["mode"] == "review" and run["approved_count"] == 1
    assert run["catalog_hash"] == "" and len(run["source_sha"]) >= 7
    assert review.opened == [
        "https://preview.test/use-cases/route-workshop-10?preview=tok-route-workshop-10"
    ]
    assert report.approved_count == 1 and report.status == "prepared"
    published = "published https://preview.test/use-cases/route-workshop-10"
    assert any(published in line for line in review.lines)


def test_demo_feedback_regenerates_only_the_demo(repo):
    review = session(repo, ["1", "1", "f", "d", "Use emoji instead", "", "q"])
    review.run()
    provider = review.providers[0]
    draft = repo.items["route-workshop-10"]
    assert draft["status"] == "draft" and draft["revision"] == 2
    state = draft["meta"]["review"]
    assert state["attempt"] == 2
    assert state["feedback"] == [
        {**state["feedback"][0], "scope": "demo", "text": "Use emoji instead"}
    ]
    assert provider.demo_attempts == 2 and provider.demo_feedback == ["Use emoji instead"]
    assert draft["page"]["demo"]["title"] == "Mood bar 1"
    assert repo.published() == [] and repo.runs == []


def test_text_feedback_keeps_the_demo(repo):
    review = session(repo, ["1", "1", "f", "t", "Shorter intro", "", "q"])
    review.run()
    assert review.providers[0].demo_attempts == 1
    draft = repo.items["route-workshop-10"]
    assert draft["meta"]["review"]["attempt"] == 2
    assert draft["page"]["demo"]["title"] == "Mood bar 1"
    # Category and tags chosen for the first attempt are kept.
    assert draft["category"] == "routing-triage"


def test_skip_is_recorded_archived_and_excluded_from_later_rounds(repo):
    review = session(repo, ["1", "1", "s", "Too generic", "q"])
    report = review.run()
    assert [item["slug"] for item in repo.skip_items] == ["route-workshop-10"]
    assert repo.skip_items[0]["reason"] == "Too generic"
    assert repo.status("route-workshop-10") == "archived"
    assert report.skipped_count == 1 and report.approved_count == 0
    assert any("route-workshop-10" in line for line in review.lines)


def test_resume_reviews_pending_draft_without_new_ideas(repo):
    session(repo, ["1", "1", "q"]).run()
    assert repo.status("route-workshop-10") == "draft"
    review = session(repo, ["a"])
    review.run(resume=True)
    assert review.providers[0].round == 0
    assert repo.published() == ["route-workshop-10"]


def test_each_approval_gets_its_own_run_id(repo):
    review = session(repo, ["1", "1", "a", "1", "1", "a"], max_pages=2)
    review.run()
    assert len(repo.published()) == 2
    assert [run["run_id"] for run in repo.runs] == ["local-test-1", "local-test-2"]


def test_auto_select_needs_no_choices(repo):
    review = session(repo, ["a"], auto_select=True)
    review.run()
    assert len(repo.published()) == 1


def test_rejected_content_token_stops_before_any_generation(repo):
    repo.fail = ("categories", 401)
    review = session(repo, [])
    with pytest.raises(ReviewError, match="rejected TYPESAFE_CONTENT_TOKEN_1"):
        review.run()
    assert review.providers == []


def test_unreachable_content_api_is_a_clear_error(repo):
    repo.fail = ("categories", 503)
    with pytest.raises(ReviewError, match="not available"):
        session(repo, []).run()


def test_known_pages_come_from_the_api_for_duplicate_checks(repo):
    session(repo, ["1", "1", "a"]).run()
    review = session(repo, ["q"])
    review.run()
    assert [p.slug for p in review.known] == ["route-workshop-10"]
    offers = [line for line in review.lines if ". route-workshop-" in line]
    assert offers and not any("route-workshop-10 " in line for line in offers)


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
    assert len(repo.published()) == 2
    second = [slug for slug in repo.published() if slug != "route-workshop-10"][0]
    assert repo.items[second]["page"]["verification"]["novelty_probability"] == 0.5


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


def test_approval_uses_the_draft_stored_now(repo):
    answers = iter(["1", "1"])
    state = {"edited": False}

    def prompt(text):
        if text.startswith("[a]pprove") and not state["edited"]:
            # Another session regenerated the draft while this one waited.
            item = repo.items["route-workshop-10"]
            item["page"]["demo"]["title"] = "Regenerated elsewhere"
            item["meta"]["review"]["attempt"] = 7
            item["revision"] += 5
            state["edited"] = True
            return "o"
        if text.startswith("[a]pprove"):
            return "a"
        return next(answers)

    review = session(repo, [])
    review.prompt = prompt
    review.run()
    assert repo.published() == ["route-workshop-10"]
    assert repo.items["route-workshop-10"]["page"]["demo"]["title"] == "Regenerated elsewhere"
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


def test_draft_records_its_inspiration_and_page_gets_plain_idea(repo):
    session(repo, ["1", "1", "q"]).run()
    draft = repo.items["route-workshop-10"]
    assert draft["meta"]["headline"]["title"].startswith("Headline 1-")
    assert "inspired_by" not in draft["meta"]["review"]["idea"]
    assert "inspired_by" not in draft["page"]


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


def test_draft_conversion_preserves_defaults_aliases_and_zero_novelty(repo, page):
    from conftest import concept

    review = session(repo, [])
    item = {
        "slug": page.slug,
        "page": page.model_dump(exclude_none=True),
        "novelty": 0,
        "inspiration": {
            "review": {
                "idea": idea().model_dump(),
                "concept": concept().model_dump(exclude_none=True),
            }
        },
    }
    draft = review.draft_from_api(item)
    assert draft["page"] is item["page"]
    assert draft["idea"] is item["inspiration"]["review"]["idea"]
    assert draft["novelty"] == 0.8
    assert draft["feedback"] == [] and draft["attempt"] == 1
    assert draft["tags"] == []
    assert draft["created_at"] is None and draft["revision"] is None
    assert draft["category"] is None
    assert review.draft_from_api({"slug": "old-draft", "page": item["page"]}) is None
    assert review.lines[-1] == "  ! draft old-draft has no review state and was ignored"
