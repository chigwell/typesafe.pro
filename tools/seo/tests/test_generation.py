import json
import random

import pytest
from conftest import FakeProvider, idea

from seo_content.novelty import Rejected, check_novelty, shortlist
from seo_content.pipeline import create_page, propose_ideas
from seo_content.providers import StageError


def test_propose_ideas_passes_recent_and_skipped_context():
    class Capture(FakeProvider):
        captured = None
        task = ""
        options = None

        def structured(self, schema, task, context, **options):
            self.captured = context
            self.task = task
            self.options = options
            return super().structured(schema, task, context)

    from seo_content.inspiration import Headline

    provider = Capture()
    headlines = [Headline(i, f"Title {i}", None, "hn") for i in range(5)]
    ideas = propose_ideas(
        [idea(3)], provider, random.Random(1), [{"summary": "Old idea"}], [], headlines
    )
    assert len(ideas.ideas) == 10
    assert provider.captured["skipped_scenarios"] == [{"summary": "Old idea"}]
    assert provider.captured["existing_scenarios"][0]["slug"] == "route-workshop-3"
    assert provider.captured["inspiration"][4] == {"index": 4, "title": "Title 4"}
    assert provider.captured["avoid_task_types"] == ["intent-routing-3"]
    assert "inspired_by" in provider.task and "never mention Hacker News" in provider.task
    # The fixed topic list made every round converge on the same themes.
    assert "spicy" not in provider.task and "music, food" not in provider.task
    assert provider.options == {"temperature": 1.0}


def test_invalid_ideas_raise_stage_error():
    class BadIdeas(FakeProvider):
        def structured(self, schema, task, context, **options):
            raise StageError("llm_stage_failed")

    with pytest.raises(StageError):
        propose_ideas([], BadIdeas(), random.Random(1))


def test_feedback_reaches_every_stage():
    seen = []

    class Capture(FakeProvider):
        def structured(self, schema, task, context, **options):
            seen.append(context["reviewer_feedback"])
            return super().structured(schema, task, context)

    create_page(idea(1), 0.95, Capture(), feedback=["Shorter intro", ""])
    assert seen and all(item == ["Shorter intro"] for item in seen)


@pytest.mark.parametrize(
    "probability,reason", [(0.81, "semantic_duplicate"), (0.5, "uncertain_novelty")]
)
def test_semantic_duplicate_or_uncertainty_rejected(probability, reason):
    provider = FakeProvider()
    provider.duplicate_probability = probability
    with pytest.raises(Rejected, match=reason):
        check_novelty(idea(2), [idea(1)], provider)


def test_novelty_distinct_task_allowed():
    assert check_novelty(idea(2), [idea(1)], FakeProvider()) == 0.95


def test_same_summary_slug_or_fingerprint_rejected():
    for change in (
        {"slug": "new-slug"},
        {"summary": "Changed wording"},
        {"slug": "new-slug", "summary": "Changed wording"},
    ):
        with pytest.raises(Rejected, match="deterministic_duplicate"):
            check_novelty(idea(1).model_copy(update=change), [idea(1)], FakeProvider())


def test_bm25_includes_all_matching_task_types():
    existing = [idea(i).model_copy(update={"task_type": "different-task"}) for i in range(250)]
    existing[248] = existing[248].model_copy(update={"task_type": idea(999).task_type})
    selected = shortlist(idea(999), existing)
    assert existing[248] in selected
    assert len(selected) <= 31
    assert shortlist(idea(999), existing[:200]) == existing[:200]


@pytest.mark.parametrize(
    "attr,reason",
    [
        ("example_probability", "example_expectation_failed"),
        ("quality_probability", "quality_threshold_failed"),
    ],
)
def test_bad_example_or_quality_never_publishes(attr, reason):
    provider = FakeProvider()
    setattr(provider, attr, 0.5)
    with pytest.raises(Rejected, match=reason):
        create_page(idea(1), 0.95, provider)


def test_calibration_pairs_validate_and_fit_requests():
    from pathlib import Path

    from seo_content.models import Idea
    from seo_content.novelty import novelty_request

    fixture = json.loads((Path(__file__).parent / "fixtures" / "novelty-pairs.json").read_bytes())
    assert any(pair["expected_duplicate"] for pair in fixture["pairs"])
    assert any(not pair["expected_duplicate"] for pair in fixture["pairs"])
    for pair in fixture["pairs"]:
        request = novelty_request(
            Idea.model_validate(pair["candidate"]), [Idea.model_validate(pair["existing"])]
        )
        assert set(request.questions) == {"duplicate_0"}


def test_quality_judges_final_article_with_actual_template_support():
    class CaptureQuality(FakeProvider):
        captured = None

        def evaluate(self, request):
            if "useful" in request.questions:
                self.captured = request
            return super().evaluate(request)

    provider = CaptureQuality()
    page = create_page(idea(1), 0.95, provider)
    state = provider.captured.state
    assert set(state) == {"api_facts", "article", "page_template"}
    assert "Authoring guidance" not in state["api_facts"]
    assert state["article"]["problem"] == page.problem
    assert state["article"]["problem"] != idea(1).problem
    assert state["article"]["solution"] == page.solution
    assert state["article"]["examples"] == [p.model_dump(exclude_none=True) for p in page.examples]
    assert set(state["page_template"]["request_code"]["languages"]) == {
        "Python",
        "JavaScript",
        "TypeScript",
        "cURL",
        "Go",
        "PHP",
        "Java",
    }
    assert "downstream actions are not executed" in state["page_template"]["interactive_execution"]


def test_quality_boundary_remains_point_eight():
    provider = FakeProvider()
    provider.quality_probability = 0.799
    with pytest.raises(Rejected, match="quality_threshold_failed"):
        create_page(idea(1), 0.95, provider)
    provider.quality_probability = 0.8
    page = create_page(idea(1), 0.95, provider)
    assert page.verification.quality.useful == 0.8


def test_failed_examples_are_repaired_with_actual_answers():
    class FirstExamplesWrong(FakeProvider):
        example_calls = 0
        repair_context = None

        def structured(self, schema, task, context, **options):
            if "failed_examples" in context:
                self.repair_context = context
                self.example_probability = 0.95
            return super().structured(schema, task, context)

        def evaluate(self, request):
            if "repair" in request.questions:
                self.example_calls += 1
                if self.example_calls == 1:
                    self.example_probability = 0.3
            return super().evaluate(request)

    provider = FirstExamplesWrong()
    warnings = []
    page = create_page(idea(1), 0.95, provider, warn=warnings.append)
    failed = provider.repair_context["failed_examples"]
    assert failed[0]["actual_answers"]["repair"]["noul"] == 0.3
    assert page.examples[0].response.answers["repair"].noul == 0.95
    assert any("repairing" in item for item in warnings)


def test_uncertain_novelty_allowed_only_for_reviewer():
    provider = FakeProvider()
    provider.duplicate_probability = 0.5
    with pytest.raises(Rejected, match="uncertain_novelty"):
        check_novelty(idea(2), [idea(1)], provider)
    assert check_novelty(idea(2), [idea(1)], provider, allow_uncertain=True) == 0.5
    provider.duplicate_probability = 0.85
    with pytest.raises(Rejected, match="semantic_duplicate"):
        check_novelty(idea(2), [idea(1)], provider, allow_uncertain=True)


def test_failed_quality_check_repairs_prose_but_keeps_verified_examples():
    class LowConsistencyOnce(FakeProvider):
        judged = 0

        def evaluate(self, request):
            if "useful" in request.questions:
                self.judged += 1
                self.quality_probability = 0.95
                response = super().evaluate(request)
                if self.judged == 1:
                    response.answers["consistent"].noul = 0.78
                return response
            return super().evaluate(request)

    provider = LowConsistencyOnce()
    warnings = []
    page = create_page(idea(1), 0.95, provider, warn=warnings.append)
    assert provider.judged == 2
    failed = provider.repairs[0]
    assert [item["check"] for item in failed] == ["consistent"]
    assert failed[0]["score"] == 0.78 and "saved request/response" in failed[0]["question"]
    assert [e.name for e in page.examples] == [
        f"Revised {k}" for k in ("primary", "alternative", "edge")
    ]
    assert all(e.response.answers["repair"].noul == 0.95 for e in page.examples)
    assert page.verification.quality.consistent == 0.95
    assert any("consistent=0.78" in w for w in warnings)


def test_quality_gives_up_after_two_repairs():
    provider = FakeProvider()
    provider.quality_probability = 0.5
    with pytest.raises(Rejected, match="quality_threshold_failed: useful=0.50"):
        create_page(idea(1), 0.95, provider)
    assert len(provider.repairs) == 2
