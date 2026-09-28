import pytest
from pydantic import ValidationError

from seo_content.models import DraftExample, EvaluationResponse, assert_expected


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
