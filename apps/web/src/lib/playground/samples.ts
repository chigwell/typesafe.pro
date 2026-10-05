import { DEFAULT_MODEL, type Answer, type EvaluationRequest, type EvaluationResponse, type JsonValue, type Preset, type Question, type SampleMatch } from "../typesafe";
import { PRESETS } from "../presets";
import { canonical, clone } from "./shared";

export function requestFor(preset: Preset, index = 0): EvaluationRequest {
  const question = {
    type: preset.type,
    instructions: clone(preset.instructions),
  } as Question;

  if (preset.criteria !== undefined) {
    (question as Question & { criteria: JsonValue[] | Record<string, JsonValue> }).criteria =
      clone(preset.criteria);
  }

  return {
    state: clone(preset.variants[index].state),
    model: DEFAULT_MODEL,
    questions: {
      [preset.questionId]: question,
    },
  };
}

export function findSample(request: EvaluationRequest): SampleMatch | null {
  const target = canonical(request);
  for (const preset of PRESETS) {
    for (let index = 0; index < preset.variants.length; index += 1) {
      if (canonical(requestFor(preset, index)) === target) {
        return { preset, index, sample: preset.variants[index] };
      }
    }
  }
  return null;
}

export function answerForSample(found: SampleMatch): EvaluationResponse {
  return {
    model: "illustrative-sample",
    answers: {
      [found.preset.questionId]: clone(found.sample.answer) as Answer,
    },
  };
}
