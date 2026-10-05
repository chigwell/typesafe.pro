"""Verify all article examples with the existing bounded repair policy."""

from .models import DraftExamples, Example, assert_expected
from .novelty import Rejected


def verify_examples(
    drafts: DraftExamples, context: dict, provider, now, warn=None
) -> list[Example]:
    """Execute all three predictions; return only when every example passes."""
    # Expectations are predictions; when the live API disagrees, show the model what it
    # actually returned and let it adjust inputs or expectations (at most two repairs).
    for attempt in range(3):
        examples, mismatches = [], []
        for draft in drafts.examples:
            response = provider.evaluate(draft.request)
            try:
                assert_expected(draft, response)
            except ValueError as exc:
                mismatches.append(
                    {
                        "example": draft.kind,
                        "problem": str(exc),
                        "expected": {
                            k: v.model_dump(exclude_none=True) for k, v in draft.expected.items()
                        },
                        "actual_answers": response.model_dump(exclude_none=True)["answers"],
                    }
                )
                continue
            examples.append(
                Example(**draft.model_dump(exclude_none=True), response=response, verified_at=now())
            )
        if not mismatches:
            break
        if attempt == 2:
            raise Rejected("example_expectation_failed")
        if warn:
            warn(f"{len(mismatches)} example(s) did not match the live API; repairing")
        drafts = provider.structured(
            DraftExamples,
            (
                "Some examples did not match the live API (see `failed_examples` with the "
                "actual answers). Return all three examples again. Keep the questions "
                "identical across examples. For each failed example either change its "
                "input so the intended outcome is clearly expressed, or change its "
                "expectation to the behaviour you now expect, keeping it defensible and "
                "consistent with the scenario. Keep the passing examples unchanged."
            ),
            {
                **context,
                "previous_examples": drafts.model_dump(exclude_none=True),
                "failed_examples": mismatches,
            },
        )
    return examples
