import json

import pytest
from conftest import FakeProvider, idea
from pydantic import ValidationError

from seo_content import catalog as storage
from seo_content.catalog import Catalog, CatalogError, canonical, sha256
from seo_content.models import DraftExample, EvaluationResponse, assert_expected
from seo_content.pipeline import create_page


def test_shard_rollover_and_hashes(content, page, monkeypatch):
    monkeypatch.setattr(storage, "MAX_PAGES", 1)
    catalog = Catalog(content)
    catalog.add(page)
    catalog.add(create_page(idea(2), 0.95, FakeProvider()))
    assert [s.count for s in catalog.manifest.shards] == [1, 1]
    entries = [s.model_dump() for s in catalog.manifest.shards]
    assert catalog.manifest.catalog_hash == sha256(canonical(entries))
    raw = (content / "pages-0001.json").read_bytes()
    assert catalog.manifest.shards[0].sha256 == sha256(raw)
    index = json.loads((content / "index-0001.json").read_bytes())
    assert index["scenarios"][0]["slug"] == page.slug


def test_byte_limit_rollover(content, page, monkeypatch):
    catalog = Catalog(content)
    catalog.add(page)
    monkeypatch.setattr(storage, "MAX_BYTES", (content / "pages-0001.json").stat().st_size + 100)
    catalog.add(create_page(idea(2), 0.95, FakeProvider()))
    assert len(catalog.manifest.shards) == 2


@pytest.mark.parametrize("filename", ["pages-0001.json", "index-0001.json"])
def test_tampering_rejected(content, page, filename):
    Catalog(content).add(page)
    (content / filename).write_text("{}")
    with pytest.raises(CatalogError):
        Catalog(content)


def test_existing_pages_not_rewritten(content, page):
    catalog = Catalog(content)
    catalog.add(page)
    before = json.loads((content / "pages-0001.json").read_bytes())["pages"][0]
    catalog.add(create_page(idea(2), 0.95, FakeProvider()))
    after = json.loads((content / "pages-0001.json").read_bytes())["pages"][0]
    assert before == after


@pytest.mark.parametrize("kind", ["choice", "noul", "score"])
def test_expected_response_contract(kind):
    question = {"type": kind, "instructions": "Judge the message"}
    expected = {"type": kind}
    if kind == "choice":
        question["criteria"] = {"yes": "Present", "no": "Absent"}
        expected["choice"] = "yes"
        answer = {
            "type": kind,
            "choice": "yes",
            "confidence": 0.9,
            "probabilities": {"yes": 0.95, "no": 0.05},
        }
    else:
        expected.update(min=0.8, max=1)
        answer = {"type": kind, kind: 0.9}
        if kind == "score":
            question["criteria"] = ["Low", "High"]
            answer.update(
                confidence=0.8, probabilities={"0": 0.1, "1": 0.9}, legend={"0": "Low", "1": "High"}
            )
    example = DraftExample(
        name="Test",
        kind="primary",
        expected_description="Expected behavior",
        request={"state": "Message", "questions": {"q": question}},
        expected={"q": expected},
    )
    response = EvaluationResponse(model="jev-test-only", answers={"q": answer})
    assert_expected(example, response)
    response.answers = {}
    with pytest.raises(ValueError):
        assert_expected(example, response)


def test_useless_expected_range_rejected():
    with pytest.raises(ValidationError):
        DraftExample(
            name="Test",
            kind="primary",
            expected_description="Anything",
            request={
                "state": "Message",
                "questions": {"q": {"type": "noul", "instructions": "Does it match?"}},
            },
            expected={"q": {"type": "noul", "min": 0, "max": 1}},
        )


def test_score_uses_weighted_level_index_above_one():
    levels = ["Absent", "Minimal", "Partial", "Mostly complete", "Complete"]
    example = DraftExample(
        name="Complete report",
        kind="primary",
        expected_description="Near the highest level",
        request={
            "state": "All sections complete",
            "questions": {
                "q": {"type": "score", "instructions": "How complete?", "criteria": levels}
            },
        },
        expected={"q": {"type": "score", "min": 3.5, "max": 4}},
    )
    response = EvaluationResponse(
        model="jev-test-only",
        answers={
            "q": {
                "type": "score",
                "score": 3.86,
                "confidence": 0.8,
                "probabilities": {"0": 0, "1": 0, "2": 0, "3": 0.14, "4": 0.86},
                "legend": {str(i): level for i, level in enumerate(levels)},
            }
        },
    )
    assert_expected(example, response)
    response.answers["q"].score = 4.1
    with pytest.raises(ValueError, match="exceeds rubric"):
        assert_expected(example, response)


def test_distribution_integrity_checked():
    example = DraftExample(
        name="Choice",
        kind="primary",
        expected_description="Select yes",
        request={
            "state": "Yes",
            "questions": {
                "q": {
                    "type": "choice",
                    "instructions": "Select",
                    "criteria": {"yes": None, "no": None},
                }
            },
        },
        expected={"q": {"type": "choice", "choice": "yes"}},
    )
    response = EvaluationResponse(
        model="jev-test-only",
        answers={
            "q": {
                "type": "choice",
                "choice": "yes",
                "confidence": 0.9,
                "probabilities": {"yes": 0.9, "no": 0.9},
            }
        },
    )
    with pytest.raises(ValueError, match="sum to one"):
        assert_expected(example, response)


@pytest.mark.parametrize("existing_pages", [0, 1])
@pytest.mark.parametrize("crash_after", [1, 2, 3, 4])
def test_append_recovers_after_every_file_write(content, monkeypatch, crash_after, existing_pages):
    catalog = Catalog(content)
    original = create_page(idea(1), 0.95, FakeProvider())
    if existing_pages:
        catalog.add(original)
    approved = create_page(idea(2), 0.95, FakeProvider())
    real_write = storage.atomic_write
    writes = 0

    def interrupted_write(path, value):
        nonlocal writes
        real_write(path, value)
        writes += 1
        if writes == crash_after:
            raise OSError("simulated process interruption")

    monkeypatch.setattr(storage, "atomic_write", interrupted_write)
    with pytest.raises((OSError, CatalogError)):
        catalog.add(approved)
    monkeypatch.setattr(storage, "atomic_write", real_write)
    recovered = Catalog(content)
    expected = [original, approved] if existing_pages else [approved]
    assert recovered.pages == expected
    assert not (content / "append-journal.json").exists()
    assert Catalog(content).pages == expected


def test_recovery_itself_can_be_interrupted(content, monkeypatch):
    approved = create_page(idea(1), 0.95, FakeProvider())
    real_write = storage.atomic_write

    def fail_after_shard(path, value):
        real_write(path, value)
        if path.name.startswith("pages-"):
            raise OSError("interrupted during recovery")

    monkeypatch.setattr(storage, "atomic_write", fail_after_shard)
    with pytest.raises(CatalogError):
        Catalog(content).add(approved)
    with pytest.raises(CatalogError):
        Catalog(content)
    monkeypatch.setattr(storage, "atomic_write", real_write)
    assert Catalog(content).pages == [approved]


def test_invalid_journal_cannot_overwrite_existing_catalog(content, monkeypatch):
    catalog = Catalog(content)
    catalog.add(create_page(idea(1), 0.95, FakeProvider()))
    before = (content / "pages-0001.json").read_bytes()
    real_write = storage.atomic_write

    def fail_after_journal(path, value):
        real_write(path, value)
        if path.name == "append-journal.json":
            raise OSError("interrupted before mutation")

    monkeypatch.setattr(storage, "atomic_write", fail_after_journal)
    with pytest.raises(OSError):
        catalog.add(create_page(idea(2), 0.95, FakeProvider()))
    monkeypatch.setattr(storage, "atomic_write", real_write)
    journal = json.loads((content / "append-journal.json").read_bytes())
    journal["file"] = "../outside.json"
    real_write(content / "append-journal.json", journal)
    with pytest.raises(CatalogError):
        Catalog(content)
    assert (content / "pages-0001.json").read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"state": " \n "},
        {"questions": {"": {"type": "noul", "instructions": "Test?"}}},
        {"questions": {"x" * 129: {"type": "noul", "instructions": "Test?"}}},
        {"questions": {"🧪" * 65: {"type": "noul", "instructions": "Test?"}}},
        {"questions": {"q": {"type": "noul", "instructions": "\t "}}},
        {"questions": {"q": {"type": "choice", "instructions": "Test?", "criteria": {" ": None}}}},
    ],
)
def test_playground_request_constraints_reject_unrenderable_examples(changes):
    from seo_content.models import EvaluationRequest

    payload = {"state": "A message", "questions": {"q": {"type": "noul", "instructions": "Test?"}}}
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({**payload, **changes})


def test_playground_depth_counts_from_request_root():
    from seo_content.models import EvaluationRequest

    state = "leaf"
    for _ in range(23):
        state = {"child": state}
    request = {"state": state, "questions": {"q": {"type": "noul", "instructions": "Test?"}}}
    EvaluationRequest.model_validate(request)
    with pytest.raises(ValidationError, match="24 levels"):
        EvaluationRequest.model_validate({**request, "state": {"child": state}})


@pytest.mark.parametrize("change", ["instructions", "edge_only_review"])
def test_three_inputs_cannot_silently_change_the_question_rubric(change):
    from seo_content.models import DraftExamples

    examples = [
        {
            "name": kind,
            "kind": kind,
            "expected_description": "The message needs handling",
            "request": {
                "state": kind,
                "questions": {
                    "q": {
                        "type": "choice",
                        "instructions": "Which department?",
                        "criteria": {"billing": "Invoices", "support": "Software issues"},
                    }
                },
            },
            "expected": {"q": {"type": "choice", "choice": "billing"}},
        }
        for kind in ("primary", "alternative", "edge")
    ]
    DraftExamples(examples=examples)
    if change == "instructions":
        examples[-1]["request"]["questions"]["q"]["instructions"] = "Is manual review needed?"
    else:
        examples[-1]["request"]["questions"]["q"]["criteria"]["review"] = "Unclear intent"
    with pytest.raises(ValidationError, match="identical question IDs"):
        DraftExamples(examples=examples)
