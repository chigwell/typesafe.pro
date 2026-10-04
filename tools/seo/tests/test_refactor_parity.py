"""Offline snapshots recorded before extracting generation/review responsibilities.

The digests cover complete ordered requests, prompts, contexts, options and responses.
Fixtures also retain serialized pages, drafts and reports so contract drift is readable.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from conftest import FakeApi, FakeFeed, FakeProvider, concept, idea

from seo_content import demo, pipeline, review
from seo_content.maintenance import import_files
from seo_content.novelty import Rejected
from seo_content.providers import Budget

FIXED_TIME = "2026-10-04T10:00:00Z"
FIXTURE = Path(__file__).parent / "fixtures" / "refactor-parity.json"


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class RecordingProvider(FakeProvider):
    def __init__(self, events, budget=None, *, repair=False, deteriorate=False):
        super().__init__(budget)
        self.events = events
        self.repair = repair
        self.deteriorate = deteriorate
        self.example_calls = 0
        self.quality_calls = 0

    def structured(self, schema, task, context, **options):
        event = {
            "call": "structured",
            "schema": schema.__name__,
            "input": digest({"task": task, "context": context, "options": options}),
        }
        self.events.append(event)
        if "failed_examples" in context:
            self.example_probability = 0.95
        result = super().structured(schema, task, context, **options)
        event["output"] = digest(result.model_dump(mode="json", exclude_none=True))
        return result

    def evaluate(self, request):
        event = {"call": "evaluate", "questions": list(request.questions)}
        event["input"] = digest(request.model_dump(mode="json", exclude_none=True))
        self.events.append(event)
        if "repair" in request.questions:
            self.example_calls += 1
            if self.repair and self.example_calls == 1:
                self.example_probability = 0.3
        result = super().evaluate(request)
        if "useful" in request.questions:
            self.quality_calls += 1
            if self.repair and self.quality_calls == 1:
                result.answers["consistent"].noul = 0.6
            if self.deteriorate:
                result.answers["consistent"].noul = {1: 0.79, 2: 0.5, 3: 0.6}[self.quality_calls]
        if "framing" in request.questions and self.repair:
            result.answers["framing"].noul = 0.44
            result.answers["solution"].noul = 0.58
        event["output"] = digest(result.model_dump(mode="json", exclude_none=True))
        return result


class RecordingApi:
    def __init__(self, events):
        self.events = events
        self.inner = FakeApi()

    def __getattr__(self, name):
        value = getattr(self.inner, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            event = {"call": name, "input": digest({"args": args, "kwargs": kwargs})}
            self.events.append(event)
            result = value(*args, **kwargs)
            event["output"] = digest(result)
            return result

        return call


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(pipeline, "now", lambda: FIXED_TIME)
    monkeypatch.setattr(review, "now", lambda: FIXED_TIME)
    monkeypatch.setattr(review.secrets, "randbits", lambda bits: 42)
    monkeypatch.setattr(review, "generator_version", lambda: "de21693")
    monkeypatch.setattr(review.time, "monotonic", lambda: 100.0)
    # Runtime exercise has separate integration tests; snapshots stay platform-independent.
    monkeypatch.setattr(demo, "check_syntax", lambda js: None)
    monkeypatch.setattr(demo, "exercise_demo", lambda result: None)


def scenarios():
    events, warnings = [], []
    provider = RecordingProvider(events, repair=True)
    page = pipeline.create_page(idea(), 0.95, provider, warn=warnings.append)
    result = {
        "repairs": {
            "events": events,
            "warnings": warnings,
            "page": page.model_dump(mode="json", exclude_none=True),
        }
    }
    events, warnings = [], []
    try:
        pipeline.create_page(
            idea(), 0.95, RecordingProvider(events, deteriorate=True), warn=warnings.append
        )
    except Rejected as exc:
        result["best_version_failure"] = {
            "events": events,
            "warnings": warnings,
            "reason": str(exc),
        }
    else:
        raise AssertionError("expected quality rejection")

    events, api = [], None
    api = RecordingApi(events)

    def session(answers):
        replies = iter(answers)
        return review.ReviewSession(
            session_id="local-parity",
            budget=Budget(max_calls=400, max_seconds=600, started=100.0),
            provider_factory=lambda budget: RecordingProvider(events, budget),
            api_factory=lambda: api,
            preview_base="https://preview.test",
            open_browser=False,
            prompt=lambda text: next(replies),
            out=lambda line: None,
            clock_url=None,
            sleep=lambda seconds: None,
            inspiration=FakeFeed(),
            max_pages=1,
        )

    first = session(["1", "1", "f", "d", "Use emoji instead", "", "q"])
    first_report = first.run()
    stored_draft = deepcopy(api.items)
    resumed = session(["f", "t", "Shorter intro", "", "a"])
    final_report = resumed.run(resume=True)
    result["review_resume"] = {
        "events": events,
        "drafts": stored_draft,
        "published": api.items,
        "runs": api.runs,
        "reports": [report.model_dump(mode="json") for report in (first_report, final_report)],
        "remaining_candidates": [item[0].slug for item in first.pool],
    }
    return result


def test_generation_review_transcripts_and_serialized_payloads_match_baseline(frozen):
    assert scenarios() == json.loads(FIXTURE.read_text())


def test_legacy_import_preserves_dates_review_state_and_reports(tmp_path, frozen):
    pages = [pipeline.create_page(idea(i), 0.95, FakeProvider()) for i in (1, 2, 3)]

    def write(name, payload):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))

    write("manifest.json", {"shards": [{"file": "pages.json"}]})
    write("pages.json", {"pages": [p.model_dump(exclude_none=True) for p in pages[:2]]})
    write("release.json", {"pages": [{"slug": pages[0].slug}]})
    pending = {
        "status": "pending",
        "page": pages[2].model_dump(exclude_none=True),
        "idea": idea(3).model_dump(),
        "concept": concept().model_dump(exclude_none=True),
        "feedback": [{"at": FIXED_TIME, "scope": "demo", "text": "Keep the bar"}],
        "attempt": 4,
        "created_at": "2026-01-02T03:04:05Z",
        "novelty": 0.93,
        "inspiration": {"title": "Legacy headline", "source": "hn"},
    }
    write(f"drafts/{pages[2].slug}.json", pending)
    write(f"drafts/{pages[1].slug}.json", {**pending, "page": pages[1].model_dump()})
    write("drafts/finished.json", {**pending, "status": "approved"})
    report = {"run_id": "legacy-run", "approved_count": 1, "started_at": FIXED_TIME}
    write("runs/01.json", {"report": report})
    write("runs/02.json", {"report": None})
    api, lines = FakeApi(), []
    assert import_files(tmp_path, taxonomy="heuristic", api=api, out=lines.append) == 0
    assert api.calls == ["categories", "put", "put", "put", "record_run"]
    assert api.items[pages[0].slug]["published_at"] == pages[0].created_at
    assert api.items[pages[1].slug]["published_at"] is None
    stored = api.items[pages[2].slug]
    assert stored["page"] == pending["page"] and stored["novelty"] == 0.93
    assert stored["meta"] == {
        "headline": pending["inspiration"],
        "review": {
            key: pending[key] for key in ("idea", "concept", "feedback", "attempt", "created_at")
        },
    }
    assert api.runs == [report]
    assert lines[-1] == "Imported 1 published page(s), 2 draft(s) and 1 run report(s)."
