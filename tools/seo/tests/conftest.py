import pytest

from seo_content.catalog import atomic_write, canonical, sha256
from seo_content.models import (
    SEO,
    Description,
    DraftExamples,
    EvaluationResponse,
    Explanation,
    Idea,
    Ideas,
)
from seo_content.pipeline import create_page


@pytest.fixture
def content(tmp_path):
    directory = tmp_path / "content"
    checksum = sha256(canonical([]))
    atomic_write(
        directory / "manifest.json",
        {
            "schema_version": 1,
            "total": 0,
            "shards": [],
            "catalog_hash": checksum,
        },
    )
    atomic_write(
        directory / "release.json",
        {
            "schema_version": 1,
            "run_id": "initial",
            "source_sha": "initial",
            "catalog_hash": checksum,
            "generated_at": "2026-09-25T00:00:00Z",
            "pages": [],
        },
    )
    return directory


@pytest.fixture
def baseline(tmp_path):
    path = tmp_path / "baseline.json"
    atomic_write(
        path,
        {
            "schema_version": 1,
            "run_id": "",
            "source_sha": "",
            "catalog_hash": "",
            "generated_at": None,
            "pages": [],
        },
    )
    return path


def idea(number=1):
    return Idea(
        slug=f"route-workshop-{number}",
        industry="workshops",
        audience="developers",
        task_type="intent-routing",
        search_intent=f"Route workshop message {number}",
        summary=f"Dispatch distinct workshop workflow {number}",
        problem=f"Workshop workflow {number} needs a particular semantic decision.",
        input_description=f"A fictional request for workflow {number}",
        decision=f"Select workshop action number {number}",
        action=f"Dispatch {number}",
    )


class FakeProvider:
    """Synthetic responses are exclusively test fixtures, never production content."""

    def __init__(self, budget=None):
        self.budget = budget
        self.round = 0
        self.duplicate_probability = 0.05
        self.example_probability = 0.95
        self.quality_probability = 0.95

    def charge(self):
        if self.budget:
            self.budget.charge()

    def structured(self, schema, task, context):
        self.charge()
        if schema is Ideas:
            self.round += 1
            return Ideas(ideas=[idea(self.round * 10 + i) for i in range(10)])
        if schema is Description:
            return Description(
                intro="A developer receives different workshop requests. " * 3,
                problem=context["scenario"]["problem"] * 3,
            )
        if schema is DraftExamples:
            return DraftExamples(
                examples=[
                    {
                        "name": kind.title(),
                        "kind": kind,
                        "request": {
                            "model": "jev-latest",
                            "state": {"message": f"Repair {kind}"},
                            "questions": {
                                "repair": {"type": "noul", "instructions": "Is repair requested?"}
                            },
                        },
                        "expected": {"repair": {"type": "noul", "min": 0.8, "max": 1.0}},
                        "expected_description": "A repair request is identified.",
                    }
                    for kind in ("primary", "alternative", "edge")
                ]
            )
        if schema is Explanation:
            return Explanation(
                solution="Use the typed probability to route the request. " * 5,
                limitations=[
                    "Escalate unclear messages for review.",
                    "Missing workshop details need follow-up.",
                ],
            )
        if schema is SEO:
            return SEO(
                title="Route workshop requests with TypeSafe",
                description="Build a workshop routing workflow with verified "
                "TypeSafe requests and interactive examples for developers.",
            )
        raise AssertionError(schema)

    def evaluate(self, request):
        self.charge()
        if any(key.startswith("duplicate_") for key in request.questions):
            value = self.duplicate_probability
        elif "useful" in request.questions:
            value = self.quality_probability
        else:
            value = self.example_probability
        return EvaluationResponse(
            model="jev-test-only",
            answers={key: {"type": "noul", "noul": value} for key in request.questions},
        )


@pytest.fixture
def page():
    return create_page(idea(), 0.95, FakeProvider())
