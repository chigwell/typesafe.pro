import json

import pytest
from conftest import FakeProvider, idea

from seo_content.catalog import Catalog, CatalogError, atomic_write, release_page
from seo_content.models import Ideas
from seo_content.novelty import Rejected, check_novelty, shortlist
from seo_content.pipeline import create_page, generate
from seo_content.providers import Budget, ProviderError


def test_full_run_limits_and_idempotency(content, baseline, tmp_path):
    report_file = tmp_path / "report.json"
    report = generate(
        content,
        run_id="ci/42",
        source_sha="abc",
        baseline=baseline,
        report_path=report_file,
        provider_factory=FakeProvider,
    )
    assert report.status == "prepared"
    assert report.generated_count == 5
    assert report.rounds == 1
    assert report.api_calls < 200
    catalog = Catalog(content)
    assert len(catalog.pages) == len(catalog.validate_release().pages) == 5
    before = report_file.read_bytes()

    def never_called(_):
        raise AssertionError("completed run must not invoke providers")

    rerun = generate(
        content,
        run_id="ci/42",
        source_sha="abc",
        baseline=baseline,
        report_path=report_file,
        provider_factory=never_called,
    )
    assert rerun == report
    assert before == report_file.read_bytes()
    with pytest.raises(CatalogError):
        generate(
            content,
            run_id="ci/42",
            source_sha="different",
            baseline=baseline,
            report_path=report_file,
            provider_factory=never_called,
        )


def test_missing_provider_is_soft_failure(content, baseline, tmp_path):
    def unavailable(_):
        raise ProviderError("missing_credentials")

    report = generate(
        content,
        run_id="no-secret",
        source_sha="abc",
        baseline=baseline,
        report_path=tmp_path / "report.json",
        provider_factory=unavailable,
    )
    assert report.status == "failed" and report.reason == "missing_credentials"
    assert Catalog(content).validate_release().pages == []


def test_pending_pages_use_publication_allowance_first(content, baseline, tmp_path, page):
    catalog = Catalog(content)
    catalog.add(page)
    report = generate(
        content,
        run_id="retry",
        source_sha="abc",
        baseline=baseline,
        report_path=tmp_path / "report.json",
        provider_factory=FakeProvider,
        max_new_pages=1,
    )
    assert report.status == "prepared" and report.api_calls == 0
    assert report.generated_count == 0
    assert Catalog(content).validate_release().pages == [release_page(page)]


def test_five_rounds_when_every_idea_is_rejected(content, baseline, tmp_path, page):
    catalog = Catalog(content)
    catalog.add(page)
    atomic_write(
        baseline,
        {
            **json.loads((content / "release.json").read_bytes()),
            "catalog_hash": catalog.manifest.catalog_hash,
            "pages": [release_page(page).model_dump()],
        },
    )

    class Duplicates(FakeProvider):
        def structured(self, schema, task, context):
            if schema is Ideas:
                self.charge()
                return Ideas(ideas=[idea()] * 10)
            return super().structured(schema, task, context)

    report = generate(
        content,
        run_id="duplicates",
        source_sha="abc",
        baseline=baseline,
        report_path=tmp_path / "report.json",
        provider_factory=Duplicates,
    )
    assert report.rounds == 5 and report.api_calls == 5
    assert report.status == "skipped" and report.rejected_count == 50


def test_budget_preserves_only_complete_pages(content, baseline, tmp_path):
    budget = Budget(max_calls=12)
    report = generate(
        content,
        run_id="bounded",
        source_sha="abc",
        baseline=baseline,
        report_path=tmp_path / "report.json",
        provider_factory=FakeProvider,
        budget=budget,
    )
    assert report.api_calls == 12 and report.reason == "budget_exhausted"
    assert report.status == "prepared" and report.generated_count == 1
    assert len(Catalog(content).validate_release().pages) == 1


def test_elapsed_budget_never_calls_provider(content, baseline, tmp_path):
    budget = Budget(max_seconds=0)
    report = generate(
        content,
        run_id="expired",
        source_sha="abc",
        baseline=baseline,
        report_path=tmp_path / "report.json",
        provider_factory=FakeProvider,
        budget=budget,
    )
    assert report.api_calls == 0 and report.reason == "budget_exhausted"


def test_corrupt_catalog_is_hard_failure(content, baseline, tmp_path):
    (content / "manifest.json").write_text("{}")
    with pytest.raises(CatalogError):
        generate(
            content,
            run_id="bad",
            source_sha="abc",
            baseline=baseline,
            report_path=tmp_path / "report.json",
            provider_factory=FakeProvider,
        )


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
    existing[248] = existing[248].model_copy(update={"task_type": "intent-routing"})
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


def test_invalid_candidate_stage_continues_with_other_candidates(content, baseline, tmp_path):
    from seo_content.models import Description
    from seo_content.providers import StageError

    class OneBadCandidate(FakeProvider):
        failed = False

        def structured(self, schema, task, context):
            if schema is Description and not self.failed:
                self.failed = True
                raise StageError("llm_stage_failed")
            return super().structured(schema, task, context)

    report = generate(
        content,
        run_id="one-bad",
        source_sha="abc",
        baseline=baseline,
        report_path=tmp_path / "report.json",
        provider_factory=OneBadCandidate,
    )
    assert report.generated_count == 5
    assert report.rejections == {"llm_stage_failed": 1}


def test_invalid_ideas_can_retry_rounds(content, baseline, tmp_path):
    from seo_content.providers import StageError

    class BadIdeas(FakeProvider):
        def structured(self, schema, task, context):
            self.charge()
            raise StageError("llm_stage_failed")

    report = generate(
        content,
        run_id="bad-ideas",
        source_sha="abc",
        baseline=baseline,
        report_path=tmp_path / "report.json",
        provider_factory=BadIdeas,
    )
    assert report.rounds == 5 and report.status == "skipped"
    assert report.rejections == {"idea_stage_failed": 5}


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


def test_expanded_fingerprint_collision_rejects_candidate_not_deployment(
    content, baseline, tmp_path, page, monkeypatch
):
    catalog = Catalog(content)
    catalog.add(page)
    atomic_write(
        baseline,
        {
            **json.loads((content / "release.json").read_bytes()),
            "catalog_hash": catalog.manifest.catalog_hash,
            "pages": [release_page(page).model_dump()],
        },
    )

    def expanded_duplicate(idea, novelty, provider):
        return page.model_copy(update={"slug": idea.slug, "summary": idea.summary})

    monkeypatch.setattr("seo_content.pipeline.create_page", expanded_duplicate)
    report = generate(
        content,
        run_id="expanded-duplicate",
        source_sha="abc",
        baseline=baseline,
        report_path=tmp_path / "report.json",
        provider_factory=FakeProvider,
    )
    assert report.status == "skipped" and report.rounds == 5
    assert report.rejections == {"expanded_scenario_duplicate": 50}
    assert Catalog(content).pages == [page]


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
