import type { EvaluationRequest, EvaluationResponse, Question, QuestionType } from "./typesafe";

export type UseCaseExpected = Record<string, { type: QuestionType; choice?: string; min?: number; max?: number }>;

export type UseCaseExample = {
  name: string;
  kind: "primary" | "alternative" | "edge";
  request: EvaluationRequest;
  expected: UseCaseExpected;
  expected_description: string;
  response: EvaluationResponse;
  verified_at: string;
};

export type UseCaseDemoSample = {
  request: EvaluationRequest;
  description: string;
  expected: UseCaseExpected;
  response: EvaluationResponse;
  verified_at: string;
};

/** A visual, interactive demo generated for the page and rendered in a sandboxed iframe. */
export type UseCaseDemo = {
  title: string;
  concept: string;
  interaction: string;
  visual: string;
  questions: Record<string, Question>;
  html: string;
  css: string;
  js: string;
  samples: UseCaseDemoSample[];
  verified_at: string;
};

export type UseCasePage = {
  schema_version: 1;
  slug: string;
  industry: string;
  audience: string;
  task_type: string;
  search_intent: string;
  summary: string;
  problem: string;
  input_description: string;
  decision: string;
  action: string;
  seo: { title: string; description: string };
  intro: string;
  solution: string;
  limitations: string[];
  examples: UseCaseExample[];
  demo?: UseCaseDemo;
  verification: {
    model: string;
    verified_at: string;
    quality: { useful: number; supported: number; consistent: number };
    novelty_probability: number;
  };
  created_at: string;
  updated_at: string;
  /** Signed draft preview from the content API; never publicly listed. */
  draft?: boolean;
};
