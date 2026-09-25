"""Version 1 storage and generation contracts, aligned with the public playground API."""

import json
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, model_validator


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must contain non-whitespace characters")
    return value


Text = Annotated[str, Field(min_length=1, max_length=12000), AfterValidator(nonblank)]
Short = Annotated[str, Field(min_length=1, max_length=800), AfterValidator(nonblank)]
Probability = Annotated[float, Field(ge=0, le=1)]
Structured = str | dict[str, JsonValue] | list[JsonValue]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ChoiceQuestion(StrictModel):
    type: Literal["choice"]
    instructions: Structured
    criteria: Annotated[dict[str, Structured | None], Field(min_length=1, max_length=255)]


class NoulQuestion(StrictModel):
    type: Literal["noul"]
    instructions: Structured
    criteria: dict[Literal["true", "false"], Structured] | None = None


class ScoreQuestion(StrictModel):
    type: Literal["score"]
    instructions: Structured
    criteria: Annotated[list[Structured], Field(min_length=2, max_length=10)]


Question = Annotated[ChoiceQuestion | NoulQuestion | ScoreQuestion, Field(discriminator="type")]


class EvaluationRequest(StrictModel):
    model: Literal["jev-latest"] = "jev-latest"
    state: Structured
    questions: Annotated[dict[str, Question], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def fits_public_api(self):
        data = self.model_dump(exclude_none=True)
        stack = [(data, 0)]
        while stack:
            value, depth = stack.pop()
            if depth > 24:
                raise ValueError("playground requests accept at most 24 levels of nesting")
            if isinstance(value, dict):
                stack.extend((nested, depth + 1) for nested in value.values())
            elif isinstance(value, list):
                stack.extend((nested, depth + 1) for nested in value)
        if isinstance(self.state, str):
            nonblank(self.state)
        for question_id, question in self.questions.items():
            nonblank(question_id)
            # JavaScript String.length counts UTF-16 code units, not Unicode code points.
            if len(question_id.encode("utf-16-le", errors="surrogatepass")) // 2 > 128:
                raise ValueError("question IDs cannot exceed 128 UTF-16 code units")
            if isinstance(question.instructions, str):
                nonblank(question.instructions)
            if question.type == "choice":
                for label in question.criteria:
                    nonblank(label)
        try:
            raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            size = len(raw.encode())
        except (ValueError, UnicodeError):
            raise ValueError("request must contain finite numbers and valid Unicode") from None
        if size > 65_536:
            raise ValueError("request exceeds 65536 bytes")
        return self


class ChoiceAnswer(StrictModel):
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, Probability]
    confidence: Probability


class NoulAnswer(StrictModel):
    type: Literal["noul"]
    noul: Probability


class ScoreAnswer(StrictModel):
    type: Literal["score"]
    score: Annotated[float, Field(ge=0, le=9)]
    probabilities: dict[str, Probability]
    confidence: Probability
    legend: dict[str, JsonValue]


Answer = Annotated[ChoiceAnswer | NoulAnswer | ScoreAnswer, Field(discriminator="type")]


class Usage(StrictModel):
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]


class EvaluationResponse(StrictModel):
    model: Short
    answers: dict[str, Answer]
    usage: Usage | None = None


class Expected(StrictModel):
    type: Literal["choice", "noul", "score"]
    choice: str | None = None
    min: Annotated[float, Field(ge=0, le=9)] | None = None
    max: Annotated[float, Field(ge=0, le=9)] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.type == "choice":
            if not self.choice or self.min is not None or self.max is not None:
                raise ValueError("choice expectation requires only a choice label")
        elif self.choice is not None or self.min is None or self.max is None:
            raise ValueError("noul/score expectation requires min and max")
        elif self.min > self.max:
            raise ValueError("expected interval must be ordered")
        elif self.type == "noul" and (self.max > 1 or self.max - self.min > 0.8):
            raise ValueError("noul expected interval must be within [0,1] and narrower than 0.8")
        return self


class DraftExample(StrictModel):
    name: Short
    kind: Literal["primary", "alternative", "edge"]
    request: EvaluationRequest
    expected: dict[str, Expected]
    expected_description: Short

    @model_validator(mode="after")
    def expected_questions(self):
        if self.request.questions.keys() != self.expected.keys():
            raise ValueError("expected must cover exactly the request question IDs")
        for key, question in self.request.questions.items():
            expected = self.expected[key]
            if expected.type != question.type:
                raise ValueError("expectation type must match its question")
            if expected.type == "choice" and expected.choice not in question.criteria:
                raise ValueError("expected choice must exist in criteria")
            if expected.type == "score":
                maximum = len(question.criteria) - 1
                if expected.max > maximum or expected.max - expected.min > 0.8 * maximum:
                    raise ValueError("score interval must fit and meaningfully narrow its rubric")
        return self


class Example(DraftExample):
    response: EvaluationResponse
    verified_at: str

    @model_validator(mode="after")
    def verify_saved_answer(self):
        assert_expected(self, self.response)
        return self


def validate_response(request: EvaluationRequest, response: EvaluationResponse) -> None:
    if response.answers.keys() != request.questions.keys():
        raise ValueError("response must cover exactly the requested questions")
    for key, question in request.questions.items():
        answer = response.answers[key]
        if answer.type != question.type:
            raise ValueError("response type differs from question")
        if answer.type in ("choice", "score"):
            if abs(sum(answer.probabilities.values()) - 1) > 0.02:
                raise ValueError("answer probabilities must sum to one")
        if answer.type == "choice":
            if answer.probabilities.keys() != question.criteria.keys():
                raise ValueError("response choice options differ from request")
            if answer.choice not in answer.probabilities:
                raise ValueError("selected choice not in probability distribution")
            if answer.probabilities[answer.choice] < max(answer.probabilities.values()) - 0.001:
                raise ValueError("selected choice is not the highest probability")
        elif answer.type == "score":
            keys = {str(i) for i in range(len(question.criteria))}
            if answer.probabilities.keys() != keys or answer.legend.keys() != keys:
                raise ValueError("score levels differ from criteria")
            if answer.score > len(question.criteria) - 1:
                raise ValueError("score exceeds rubric")
            weighted = sum(int(i) * p for i, p in answer.probabilities.items())
            if abs(weighted - answer.score) > 0.05:
                raise ValueError("score differs from its weighted level probabilities")


def assert_expected(example: DraftExample, response: EvaluationResponse) -> None:
    validate_response(example.request, response)
    for key, expected in example.expected.items():
        answer = response.answers[key]
        if answer.type == "choice":
            if answer.choice != expected.choice:
                raise ValueError("unexpected choice")
        else:
            value = answer.noul if answer.type == "noul" else answer.score
            if not expected.min <= value <= expected.max:
                raise ValueError("answer outside expected range")


class Idea(StrictModel):
    slug: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=90)]
    industry: Short
    audience: Short
    task_type: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)]
    search_intent: Short
    summary: Short
    problem: Text
    input_description: Short
    decision: Short
    action: Short


class Ideas(StrictModel):
    ideas: Annotated[list[Idea], Field(min_length=10, max_length=10)]


class Description(StrictModel):
    intro: Annotated[str, Field(min_length=80, max_length=600), AfterValidator(nonblank)]
    problem: Annotated[str, Field(min_length=80, max_length=1200), AfterValidator(nonblank)]


class DraftExamples(StrictModel):
    examples: Annotated[list[DraftExample], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def kinds(self):
        if {item.kind for item in self.examples} != {"primary", "alternative", "edge"}:
            raise ValueError("exactly one primary, alternative and edge example required")
        states = {json.dumps(item.request.state, sort_keys=True) for item in self.examples}
        if len(states) != 3:
            raise ValueError("examples must have distinct input states")
        questions = {
            json.dumps(item.request.model_dump(exclude_none=True)["questions"], sort_keys=True)
            for item in self.examples
        }
        if len(questions) != 1:
            raise ValueError(
                "all three examples must use identical question IDs, instructions and criteria; "
                "include any review/no-match outcome in every example"
            )
        return self


class Explanation(StrictModel):
    solution: Annotated[str, Field(min_length=160, max_length=2200), AfterValidator(nonblank)]
    limitations: Annotated[list[Short], Field(min_length=2, max_length=3)]


class SEO(StrictModel):
    title: Annotated[str, Field(min_length=20, max_length=75), AfterValidator(nonblank)]
    description: Annotated[str, Field(min_length=70, max_length=175), AfterValidator(nonblank)]


class Quality(StrictModel):
    useful: Annotated[float, Field(ge=0.8, le=1)]
    supported: Annotated[float, Field(ge=0.8, le=1)]
    consistent: Annotated[float, Field(ge=0.8, le=1)]


class Verification(StrictModel):
    model: Short
    verified_at: str
    quality: Quality
    novelty_probability: Annotated[float, Field(ge=0.8, le=1)]


class Page(Idea):
    schema_version: Literal[1] = 1
    seo: SEO
    intro: Text
    solution: Text
    limitations: Annotated[list[Short], Field(min_length=1, max_length=6)]
    examples: Annotated[list[Example], Field(min_length=3, max_length=3)]
    verification: Verification
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def page_examples(self):
        DraftExamples(
            examples=[
                DraftExample.model_validate(item.model_dump(exclude={"response", "verified_at"}))
                for item in self.examples
            ]
        )
        from datetime import datetime

        for value in (
            self.created_at,
            self.updated_at,
            self.verification.verified_at,
            *(item.verified_at for item in self.examples),
        ):
            if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("timestamps must include a timezone")
        return self


class Shard(StrictModel):
    schema_version: Literal[1] = 1
    pages: Annotated[list[Page], Field(min_length=1, max_length=100)]


class ShardEntry(StrictModel):
    file: Annotated[str, Field(pattern=r"^pages-[0-9]{4,}\.json$")]
    count: Annotated[int, Field(ge=1, le=100)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Manifest(StrictModel):
    schema_version: Literal[1] = 1
    total: Annotated[int, Field(ge=0)]
    shards: list[ShardEntry]
    catalog_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ReleasePage(StrictModel):
    slug: str
    title: str
    created_at: str
    updated_at: str


class Release(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    source_sha: str
    catalog_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    generated_at: str
    pages: list[ReleasePage]


class Report(StrictModel):
    run_id: str
    source_sha: str
    status: Literal["prepared", "skipped", "failed"]
    reason: str
    started_at: str
    finished_at: str
    duration_seconds: float
    seed: int
    rounds: int = 0
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    generated_count: int = 0
    rejected_count: int = 0
    rejections: dict[str, int] = Field(default_factory=dict)
    catalog_hash: str
