export type QuestionType = "choice" | "noul" | "score";

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type ChoiceQuestion = {
  type: "choice";
  instructions: JsonValue;
  criteria: Record<string, JsonValue>;
};

export type NoulQuestion = {
  type: "noul";
  instructions: JsonValue;
  criteria?: {
    true?: JsonValue;
    false?: JsonValue;
  };
};

export type ScoreQuestion = {
  type: "score";
  instructions: JsonValue;
  criteria: JsonValue[];
};

export type Question = ChoiceQuestion | NoulQuestion | ScoreQuestion;

export type EvaluationRequest = {
  model: string;
  state: JsonValue;
  questions: Record<string, Question>;
};

export type ChoiceAnswer = {
  type: "choice";
  choice: string;
  probabilities: Record<string, number>;
  confidence: number;
};

export type NoulAnswer = {
  type: "noul";
  noul: number;
};

export type ScoreAnswer = {
  type: "score";
  score: number;
  probabilities: Record<string, number>;
  confidence: number;
  legend: Record<string, unknown>;
};

export type Answer = ChoiceAnswer | NoulAnswer | ScoreAnswer;

export type EvaluationResponse = {
  model: string;
  answers: Record<string, Answer>;
  usage?: {
    input_tokens: number;
    output_tokens: number;
  };
};

export type PresetVariant = {
  name: string;
  state: string;
  answer: Answer;
  next: string;
};

export type Preset = {
  id: string;
  title: string;
  description: string;
  group: "support" | "everyday" | "developers";
  type: QuestionType;
  icon: "mail" | "zap" | "star" | "book" | "receipt" | "route" | "tag" | "file-check" | "bug";
  questionId: string;
  instructions: JsonValue;
  criteria?: Record<string, JsonValue> | JsonValue[];
  from: string;
  to: string;
  tags: string;
  variants: PresetVariant[];
};

export type SampleMatch = {
  preset: Preset;
  index: number;
  sample: PresetVariant;
};

export const API_ENDPOINT = "/v1/systemone";
export const DEFAULT_MODEL = "jev-latest";
export const DEFAULT_API_BASE = "https://api.typesafe.pro";
export const MAX_BODY_BYTES = 65_536;
export const MAX_RESPONSE_BYTES = 1_048_576;
export const MAX_QUESTIONS = 20;
export const LIVE_TIMEOUT_MS = 20_000;

