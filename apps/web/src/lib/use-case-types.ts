import type { EvaluationRequest, EvaluationResponse, QuestionType } from "./typesafe";

export type UseCaseExample = {
  name: string;
  kind: "primary" | "alternative" | "edge";
  request: EvaluationRequest;
  expected: Record<string, { type: QuestionType; choice?: string; min?: number; max?: number }>;
  expected_description: string;
  response: EvaluationResponse;
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
  verification: {
    model: string;
    verified_at: string;
    quality: { useful: number; supported: number; consistent: number };
    novelty_probability: number;
  };
  created_at: string;
  updated_at: string;
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
