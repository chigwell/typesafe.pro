import { describe, expect, it } from "vitest";
import { makeCode } from "./codegen";
import { PRESETS } from "./presets";
import { answerForSample, clone, findSample, requestFor, validateRequest, validateResponse } from "./playground";

describe("playground helpers", () => {
  it("builds a valid request from a preset and finds its authored sample", () => {
    const request = requestFor(PRESETS[0], 0);

    expect(validateRequest(request)).toEqual(request);
    expect(findSample(request)?.sample.next).toContain("refund-help");
  });

  it("rejects malformed request JSON before live calls", () => {
    expect(() =>
      validateRequest({
        model: "jev-latest",
        state: "",
        questions: {},
        extra: true,
      }),
    ).toThrow(/top level|state/i);
  });

  it("validates live response answer shapes against question definitions", () => {
    const request = requestFor(PRESETS[0], 0);
    const response = {
      model: "jev-1.13.0",
      answers: {
        request_type: {
          type: "choice",
          choice: "refund",
          probabilities: { refund: 0.9, delivery: 0.08, other: 0.02 },
          confidence: 0.82,
        },
      },
      usage: { input_tokens: 20, output_tokens: 8 },
    };

    expect(validateResponse(response, request)).toEqual(response);
  });

  it("generates code snippets for the current gateway endpoint", () => {
    const code = makeCode("typescript", requestFor(PRESETS[1], 0));

    expect(code).toContain("https://api.typesafe.pro");
    expect(code).toContain("/v1/systemone");
    expect(code).toContain("is_urgent");
  });
});


describe("authored sample isolation", () => {
  it("retains JSON cloning semantics and does not share nested authored request or answer values", () => {
    expect(clone({ absent: undefined, nan: NaN, nested: [undefined, { value: 1 }] })).toEqual({ nan: null, nested: [null, { value: 1 }] });
    const first = requestFor(PRESETS[0]);
    const expected = requestFor(PRESETS[0]);
    if (first.questions[PRESETS[0].questionId].type === "choice") {
      const question = first.questions[PRESETS[0].questionId];
      if (question.type === "choice") question.criteria.refund = "Changed";
    }
    expect(requestFor(PRESETS[0])).toEqual(expected);
    const found = findSample(expected)!;
    const response = answerForSample(found);
    const expectedResponse = answerForSample(found);
    const answer = response.answers[found.preset.questionId];
    if (answer.type === "choice") answer.probabilities.refund = 0;
    expect(answerForSample(found)).toEqual(expectedResponse);
  });
  it("finds the same sample when question and criteria keys are reordered", () => {
    const request = requestFor(PRESETS[0]);
    const question = request.questions[PRESETS[0].questionId];
    if (question.type === "choice") question.criteria = Object.fromEntries(Object.entries(question.criteria).reverse());
    expect(findSample(request)?.index).toBe(0);
  });
});
