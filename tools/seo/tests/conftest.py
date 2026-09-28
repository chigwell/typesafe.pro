import pytest

from seo_content.catalog import atomic_write, canonical, sha256
from seo_content.models import (
    SEO,
    ArticleRepair,
    DemoCode,
    DemoConcept,
    DemoConcepts,
    Description,
    DraftExamples,
    EvaluationResponse,
    Explanation,
    Idea,
    IdeaCandidate,
    Ideas,
)
from seo_content.pipeline import create_page

DEMO_QUESTIONS = {"mood": {"type": "noul", "instructions": "Is the message positive?"}}
DEMO_HTML = (
    '<label>Message <input id="demo-input" type="text"></label>'
    '<button id="demo-run" type="button">Check</button>'
    '<p id="demo-status" aria-live="polite"></p><div id="demo-visual"></div>'
)
DEMO_CSS = "#demo-visual{height:40px;background:var(--demo-accent);transition:width .4s}"
DEMO_JS = """const input = document.getElementById("demo-input");
const button = document.getElementById("demo-run");
const status = document.getElementById("demo-status");
const visual = document.getElementById("demo-visual");
button.addEventListener("click", async () => {
  button.disabled = true;
  try {
    const answers = await window.TypeSafeDemo.evaluate({ message: input.value });
    visual.style.width = Math.round(answers.mood.noul * 100) + "%";
    status.textContent = "Positive: " + answers.mood.noul.toFixed(2);
  } catch (error) {
    status.textContent = window.TypeSafeDemo.describeError(error);
  } finally {
    button.disabled = false;
  }
});
"""


def concept(number=1):
    return DemoConcept(
        title=f"Mood bar {number}",
        concept="A bar grows with how positive the message is.",
        interaction="Type a short customer message and press Check.",
        visual="The bar width follows the noul probability.",
        questions=DEMO_QUESTIONS,
    )


def demo_code():
    return DemoCode(
        html=DEMO_HTML,
        css=DEMO_CSS,
        js=DEMO_JS,
        samples=[
            {
                "state": {"message": "Thanks, this was fast and friendly!"},
                "description": "A clearly positive message.",
                "expected": {"mood": {"type": "noul", "min": 0.8, "max": 1.0}},
            },
            {
                "state": {"message": "Great support, thank you."},
                "description": "Another positive message.",
                "expected": {"mood": {"type": "noul", "min": 0.8, "max": 1.0}},
            },
        ],
    )


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
        task_type=f"intent-routing-{number}",
        search_intent=f"Route workshop message {number}",
        summary=f"Dispatch case{number} using alpha{number} beta{number} gamma{number}",
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
        self.demo_attempts = 0
        self.idea_contexts = []
        self.repairs = []
        self.repair_contexts = []
        self.demo_feedback = []

    def charge(self):
        if self.budget:
            self.budget.charge()

    def structured(self, schema, task, context, **options):
        self.charge()
        if schema is Ideas:
            self.round += 1
            self.idea_contexts.append(context)
            return Ideas(
                ideas=[
                    IdeaCandidate(**idea(self.round * 10 + i).model_dump(), inspired_by=i % 5)
                    for i in range(10)
                ]
            )
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
        if schema is ArticleRepair:
            self.repairs.append(context["failed_checks"])
            self.repair_contexts.append(context)
            framing = dict(context["framing"])
            framing["decision"] = "Choose one: " + framing["decision"]
            return ArticleRepair(
                framing=framing,
                description=context["description"],
                explanation=context["explanation"],
                seo=context["seo"],
                examples=[
                    {
                        "kind": e["kind"],
                        "name": f"Revised {e['kind']}",
                        "expected_description": e["expected_description"],
                    }
                    for e in context["verified_examples"]
                ],
            )
        if schema is DemoConcepts:
            return DemoConcepts(concepts=[concept(i) for i in (1, 2, 3)])
        if schema is DemoCode:
            self.demo_attempts += 1
            self.demo_feedback = list(context.get("reviewer_feedback", []))
            return demo_code()
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


@pytest.fixture
def demo_page():
    return create_page(idea(), 0.95, FakeProvider(), demo_concept=concept())


class FakeFeed:
    """Deterministic inspiration headlines; never touches the network."""

    label = "test headlines"

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def next(self, n=5):
        from seo_content.inspiration import Headline, InspirationUnavailable

        self.calls += 1
        if self.fail:
            raise InspirationUnavailable("offline")
        return [
            Headline(self.calls * 100 + i, f"Headline {self.calls}-{i}", None, "hn")
            for i in range(n)
        ]
