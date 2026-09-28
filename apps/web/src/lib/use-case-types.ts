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

export const DEMO_LIMITS = { html: 12_000, css: 8_000, js: 20_000, samples: [2, 4] as const };

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
  /** Development-only preview loaded from content/use-cases/drafts; never published. */
  draft?: boolean;
};

export type UseCaseRelease = {
  schema_version: 1;
  run_id: string;
  source_sha: string;
  catalog_hash: string;
  generated_at: string;
  pages: Array<Pick<UseCasePage, "slug" | "created_at" | "updated_at"> & { title: string }>;
};

export const USE_CASES_PAGE_SIZE = 24;
export const SITEMAP_CHUNK_SIZE = 10_000;
