import type { EvaluationRequest, JsonValue } from "../typesafe";

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
