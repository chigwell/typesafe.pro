import {
  API_ENDPOINT,
  DEFAULT_API_BASE,
  DEFAULT_MODEL,
  LIVE_TIMEOUT_MS,
  MAX_BODY_BYTES,
  MAX_QUESTIONS,
  MAX_RESPONSE_BYTES,
  type Answer,
  type EvaluationRequest,
  type EvaluationResponse,
  type JsonValue,
  type Preset,
  type Question,
  type SampleMatch,
} from "./typesafe";
import { PRESETS } from "./presets";

export const API_BASE =
  process.env.NEXT_PUBLIC_TYPESAFE_API_BASE?.replace(/\/+$/, "") || DEFAULT_API_BASE;

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isJsonRecord(value: JsonValue): value is Record<string, JsonValue> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isProbability(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

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

export function canonical(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonical).join(",")}]`;
  }
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
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

export function simpleCompatible(request: EvaluationRequest): boolean {
  const questions = Object.values(request.questions);
  return (
    questions.length === 1 &&
    typeof request.state === "string" &&
    typeof questions[0]?.instructions === "string"
  );
}

export function shortCriterion(value: JsonValue): string {
  const text =
    typeof value === "string"
      ? value
      : isJsonRecord(value) && typeof value.label === "string"
        ? value.label
        : JSON.stringify(value);
  const colon = text.indexOf(":");
  const short = colon > 0 && colon < 30 ? text.slice(0, colon) : text;
  return short.length > 32 ? `${short.slice(0, 29)}...` : short;
}

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

export async function readBoundedJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json") && !contentType.includes("+json")) {
    throw new Error("The gateway returned a non-JSON response.");
  }
  if (!response.body) {
    throw new Error("The gateway returned an empty response.");
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      bytes += value.byteLength;
      if (bytes > MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw new Error("The response is larger than this playground can display (1 MiB).");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const buffer = new Uint8Array(bytes);
  let offset = 0;
  for (const chunk of chunks) {
    buffer.set(chunk, offset);
    offset += chunk.byteLength;
  }

  try {
    return JSON.parse(new TextDecoder().decode(buffer));
  } catch {
    throw new Error("The gateway returned invalid JSON.");
  }
}

export function httpError(response: Response): string {
  const statusCode = response.status;
  if (statusCode === 401 || statusCode === 403) {
    return "This request needs a valid typesafe.pro token. Add your gateway token in Advanced mode, or return to Sample mode.";
  }
  if (statusCode === 429) {
    const header = response.headers.get("Retry-After");
    let seconds = Number(header);
    if (header && !Number.isFinite(seconds)) {
      seconds = Math.ceil((Date.parse(header) - Date.now()) / 1000);
    }
    return header && Number.isFinite(seconds) && seconds > 0 && seconds <= 3600
      ? `The free rate limit was reached. Retry in ${Math.ceil(seconds)} seconds, or explore a sample.`
      : "The free rate limit was reached. Try again later, or explore a sample.";
  }
  if ([502, 503, 504, 529].includes(statusCode)) {
    return `The service is temporarily unavailable (HTTP ${statusCode}). Try again later, or use Sample mode.`;
  }
  if (statusCode === 400 || statusCode === 422) {
    return `The gateway rejected this request (HTTP ${statusCode}). Check the model, state, and questions in Advanced mode.`;
  }
  if (statusCode === 404) {
    return "The API endpoint was not found. Check that the gateway serves /v1/systemone.";
  }
  return `The gateway returned HTTP ${statusCode}. No answer has been substituted. You can still explore the samples.`;
}

export async function runLiveEvaluation(options: {
  request: EvaluationRequest;
  token?: string;
  signal: AbortSignal;
  apiBase?: string;
}): Promise<EvaluationResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }
  const response = await fetch(`${options.apiBase ?? API_BASE}${API_ENDPOINT}`, {
    method: "POST",
    headers,
    body: JSON.stringify(options.request),
    signal: options.signal,
    credentials: "omit",
    mode: "cors",
    cache: "no-store",
    redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) {
    if (response.body) {
      await response.body.cancel();
    }
    throw new Error(httpError(response));
  }
  return validateResponse(await readBoundedJson(response), options.request);
}

export function timeoutSignal(controller: AbortController, ms = LIVE_TIMEOUT_MS): { timer: number; signal: AbortSignal } {
  const timer = window.setTimeout(() => controller.abort("timeout"), ms);
  return { timer, signal: controller.signal };
}

export function answerForSample(found: SampleMatch): EvaluationResponse {
  return {
    model: "illustrative-sample",
    answers: {
      [found.preset.questionId]: clone(found.sample.answer) as Answer,
    },
  };
}
