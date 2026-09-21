import { describe, expect, it } from "vitest";
import { makeCode } from "./codegen";
import { PRESETS } from "./presets";
import { findSample, requestFor, validateRequest, validateResponse } from "./playground";

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

