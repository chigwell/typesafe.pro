import { MAX_BODY_BYTES, MAX_QUESTIONS, type EvaluationRequest, type EvaluationResponse } from "../typesafe";
import { isProbability, isRecord } from "./shared";

export function validateRequest(value: unknown): EvaluationRequest {
  if (!isRecord(value)) {
    throw new Error("The request must be a JSON object.");
  }
  const stack: Array<{ value: unknown; depth: number }> = [{ value, depth: 0 }];
  while (stack.length) {
    const item = stack.pop();
    if (!item) {
      continue;
    }
    if (item.depth > 24) {
      throw new Error("This playground accepts up to 24 levels of JSON nesting.");
    }
    if (typeof item.value === "number" && !Number.isFinite(item.value)) {
      throw new Error("JSON numbers must be finite.");
    }
    if (item.value !== null && typeof item.value === "object") {
      for (const nested of Object.values(item.value)) {
        stack.push({ value: nested, depth: item.depth + 1 });
      }
    }
  }

  const allowedFields = new Set(["state", "model", "questions"]);
  if (Object.keys(value).some((key) => !allowedFields.has(key))) {
    throw new Error("Use only state, model, and questions at the top level.");
  }
  if (
    typeof value.state !== "string" &&
    !isRecord(value.state) &&
    !Array.isArray(value.state)
  ) {
    throw new Error("State must be text, a JSON object, or an array.");
  }
  if (typeof value.state === "string" && !value.state.trim()) {
    throw new Error("Add some text to the state first.");
  }
  if (typeof value.model !== "string" || !value.model.trim() || value.model.length > 128) {
    throw new Error("Use a non-empty model name, such as jev-latest (up to 128 characters).");
  }
  if (!isRecord(value.questions)) {
    throw new Error("Questions must be an object with named questions.");
  }

  const questions = Object.entries(value.questions);
  if (!questions.length || questions.length > MAX_QUESTIONS) {
    throw new Error(`This playground accepts 1-${MAX_QUESTIONS} questions per request.`);
  }
  for (const [id, question] of questions) {
    if (!id.trim() || id.length > 128) {
      throw new Error("Each question needs a non-empty ID of at most 128 characters.");
    }
    if (!isRecord(question) || !["choice", "score", "noul"].includes(String(question.type))) {
      throw new Error(`"${id}": type must be choice, score, or noul.`);
    }
    if (Object.keys(question).some((key) => !["type", "instructions", "criteria"].includes(key))) {
      throw new Error(`"${id}": use only type, instructions, and criteria.`);
    }
    if (!Object.hasOwn(question, "instructions")) {
      throw new Error(`"${id}": add instructions describing what to judge.`);
    }
    validateEntry(question.instructions, `"${id}" instructions`);
    if (typeof question.instructions === "string" && !question.instructions.trim()) {
      throw new Error(`"${id}": write a question in instructions.`);
    }

    if (question.type === "choice") {
      if (
        !isRecord(question.criteria) ||
        !Object.keys(question.criteria).length ||
        Object.keys(question.criteria).length > 255
      ) {
        throw new Error(`"${id}": Choice needs 1-255 named options in criteria.`);
      }
      for (const [key, criterion] of Object.entries(question.criteria)) {
        if (!key.trim()) {
          throw new Error(`"${id}": every Choice option needs a name.`);
        }
        validateEntry(criterion, `"${id}" option "${key}"`);
      }
    } else if (question.type === "score") {
      if (!Array.isArray(question.criteria) || question.criteria.length < 2 || question.criteria.length > 10) {
        throw new Error(`"${id}": Score needs an ordered array of 2-10 descriptive levels.`);
      }
      question.criteria.forEach((entry, index) => validateEntry(entry, `"${id}" level ${index}`));
    } else if (Object.hasOwn(question, "criteria")) {
      if (
        !isRecord(question.criteria) ||
        Object.keys(question.criteria).some((key) => !["true", "false"].includes(key))
      ) {
        throw new Error(`"${id}": Noul criteria may contain only true and false descriptions.`);
      }
      Object.entries(question.criteria).forEach(([key, entry]) => {
        validateEntry(entry, `"${id}" ${key}`);
      });
    }
  }

  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > MAX_BODY_BYTES) {
    throw new Error("This playground limits a request to 64 KiB. Shorten the text or questions.");
  }
  return value as EvaluationRequest;
}

function validateEntry(value: unknown, label: string): void {
  if (value !== null && typeof value !== "string" && !isRecord(value) && !Array.isArray(value)) {
    throw new Error(`${label} must be text, an object, an array, or null.`);
  }
}

export function validateResponse(data: unknown, sentRequest: EvaluationRequest): EvaluationResponse {
  if (!isRecord(data) || typeof data.model !== "string" || !isRecord(data.answers)) {
    throw new Error("The gateway returned an unexpected response shape.");
  }

  for (const [id, question] of Object.entries(sentRequest.questions)) {
    const answer = data.answers[id];
    if (!isRecord(answer) || answer.type !== question.type) {
      throw new Error(`The response is missing a valid answer for "${id}".`);
    }

    if (answer.type === "noul") {
      if (!isProbability(answer.noul)) {
        throw new Error("A yes probability in the response is outside 0-1.");
      }
      continue;
    }

    if (!isProbability(answer.confidence) || !isRecord(answer.probabilities)) {
      throw new Error("The response has invalid confidence or probabilities.");
    }
    const probabilities = answer.probabilities as Record<string, unknown>;
    const expectedKeys =
      question.type === "choice"
        ? Object.keys(question.criteria)
        : question.type === "score"
          ? question.criteria.map((_, index) => String(index))
          : [];
    if (
      Object.keys(probabilities).length !== expectedKeys.length ||
      !expectedKeys.every((key) => Object.hasOwn(probabilities, key) && isProbability(probabilities[key]))
    ) {
      throw new Error("The returned options do not match the question.");
    }
    const total = Object.values(probabilities).reduce<number>(
      (sum, probability) => sum + Number(probability),
      0,
    );
    if (Math.abs(total - 1) > 0.02) {
      throw new Error("The returned probabilities do not add up to 1.");
    }
    if (answer.type === "choice" && question.type === "choice") {
      if (typeof answer.choice !== "string" || !Object.hasOwn(question.criteria, answer.choice)) {
        throw new Error("The response selected an option not present in this question.");
      }
    } else if (answer.type === "score" && question.type === "score" && (
      !Number.isFinite(answer.score) ||
      Number(answer.score) < 0 ||
      Number(answer.score) > question.criteria.length - 1 ||
      !isRecord(answer.legend)
    )) {
      throw new Error("The response contains an invalid score or legend.");
    }
  }

  return data as EvaluationResponse;
}
