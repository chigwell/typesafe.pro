import { DEFAULT_API_BASE } from "./typesafe";

const API_BASE = (
  process.env.NEXT_PUBLIC_TYPESAFE_API_BASE || DEFAULT_API_BASE
).replace(/\/$/, "");
export type ActivityWindow = "5m" | "1h" | "24h" | "7d";
export type Counts = Record<string, number>;
export interface Summary {
  window: ActivityWindow;
  from: number;
  to: number;
  totals: Counts;
  tiers: Array<{ name: string; requests: number; errors?: number }>;
  masters: Array<{
    name: string;
    requests: number;
    errors?: number;
    avg_upstream_ms?: number;
  }>;
  paths: Array<{ name: string; requests: number; errors?: number }>;
  status_codes: Record<string, number>;
  status_classes: Record<string, number>;
  upstream_statuses: Record<string, number>;
  telemetry: { dropped: number; last_flush_at: number | null };
}
export interface ResourceUsage {
  total_bytes: number;
  used_bytes: number;
  percent: number;
}
export interface Sample {
  at: number;
  cpu_percent: number | null;
  memory: ResourceUsage | null;
  disk: ResourceUsage | null;
  load: number[] | null;
}
export interface SystemStatus {
  status: "ok" | "partial";
  release: string;
  current: Sample | null;
  history: Sample[];
  redis: { ok: boolean; latency_ms: number | null };
  postgres: { ok: boolean; latency_ms: number | null };
  queue: {
    inflight: number;
    max_inflight: number;
    pending: Record<string, number>;
    body_bytes: number;
  };
  telemetry: {
    dropped_errors: number;
    dropped_activity: number;
    last_flush_at: number | null;
  };
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface IpActivity {
  ip: string;
  requests: number;
  errors: number;
  last_seen: number | null;
}
export interface PageViewRow {
  date: string;
  path: string;
  unique_visitors: number;
  total_hits: number;
  first_seen_at: string;
  last_seen_at: string;
}
export interface ErrorEvent {
  id: string;
  created_at: string;
  request_id: string;
  client_ip: string | null;
  client_tier: string;
  method: string;
  path: string;
  status: number;
  error_code: string;
  duration_ms: number;
  upstream_status: number | null;
  master_key_id: string | null;
  error_detail: string | null;
  raw_response: string | null;
  response_truncated: boolean;
}
export class AdminError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryAfter: number = 0,
  ) {
    super(message);
  }
}
export async function adminFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}/admin/api${path}`, {
    ...options,
    credentials: "include",
    cache: "no-store",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new AdminError(
      response.status,
      typeof data.detail === "string" ? data.detail : "Request failed",
      Number(response.headers.get("Retry-After")) || 0,
    );
  }
  return response.json();
}

export interface SeoPublication {
  run_id: string;
  source_sha: string;
  catalog_hash: string;
  generated_at: string;
  published_at: string;
  added_count: number;
  removed_count: number;
  total_pages: number;
}
export interface SeoRun {
  run_id: string;
  source_sha: string;
  status: "prepared" | "skipped" | "failed" | "published";
  generation_status: "prepared" | "skipped" | "failed";
  reason: string | null;
  started_at: string;
  finished_at: string;
  published_at: string | null;
  duration_seconds: number;
  seed: number | string;
  rounds: number;
  api_calls: number;
  input_tokens: number | null;
  output_tokens: number | null;
  generated_count: number;
  rejected_count: number;
  rejections: Record<string, number>;
  catalog_hash: string;
}
export interface SeoSummary {
  total_pages: number;
  added_last_deploy: number;
  latest_publication: SeoPublication | null;
  latest_attempt: SeoRun | null;
  totals: {
    runs: number;
    api_calls: number;
    input_tokens: number | null;
    output_tokens: number | null;
  };
}
export interface SeoPage {
  slug: string;
  title: string;
  path: string;
  created_at: string;
  updated_at: string;
  published_at: string;
  unique_visitors: number;
  total_hits: number;
}
