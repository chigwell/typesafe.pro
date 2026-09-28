// Server and browser client for the public, cached use-case API (see /openapi.json).
import { cache } from "react";
import type { components } from "./api-types";
import { DEFAULT_API_BASE } from "./typesafe";
import type { UseCasePage } from "./use-case-types";

export type UseCaseCard = components["schemas"]["UseCaseCard"];
export type UseCaseList = components["schemas"]["UseCaseList"];
export type Facets = components["schemas"]["Facets"];
export type Sitemap = components["schemas"]["Sitemap"];
export type UseCaseDetail = Omit<components["schemas"]["UseCaseDetail"], "page"> & { page: UseCasePage };
export type ListQuery = { q?: string; category?: string; tag?: string; page?: number; page_size?: number };

export const PAGE_SIZE = 24;
export const SITEMAP_CHUNK_SIZE = 10_000;
const TIMEOUT_MS = 8000;

export class ContentApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function apiBase() {
  const value =
    (typeof process !== "undefined" && (process.env.TYPESAFE_API_BASE || process.env.NEXT_PUBLIC_TYPESAFE_API_BASE)) ||
    DEFAULT_API_BASE;
  return value.replace(/\/+$/, "");
}

export function listParams(query: ListQuery) {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set("q", query.q.trim().slice(0, 200));
  if (query.category) params.set("category", query.category);
  if (query.tag) params.set("tag", query.tag);
  if (query.page && query.page > 1) params.set("page", String(Math.min(query.page, 500)));
  params.set("page_size", String(query.page_size ?? PAGE_SIZE));
  return params;
}

async function getJson<T>(path: string, init: RequestInit = {}, base = apiBase()): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const outer = init.signal;
  outer?.addEventListener("abort", () => controller.abort(), { once: true });
  try {
    const response = await fetch(`${base}${path}`, {
      ...init,
      signal: controller.signal,
      credentials: "omit",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new ContentApiError(response.status, `Content API returned ${response.status}`);
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export function listUseCases(query: ListQuery, init?: RequestInit) {
  return getJson<UseCaseList>(`/v1/use-cases?${listParams(query)}`, init);
}

export function useCaseFacets(init?: RequestInit) {
  return getJson<Facets>("/v1/use-case-facets", init);
}

export function useCaseSitemap(chunk: number) {
  return getJson<Sitemap>(`/v1/use-cases-sitemap?chunk=${chunk}`, { cache: "no-store" });
}

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** One request per render for both generateMetadata and the page (React cache). */
export const getUseCase = cache(async (slug: string, preview?: string): Promise<UseCaseDetail | null> => {
  if (!SLUG.test(slug) || slug.length > 120) return null;
  try {
    const path = preview
      ? `/v1/use-cases/preview/${slug}?token=${encodeURIComponent(preview.slice(0, 200))}`
      : `/v1/use-cases/${slug}`;
    return await getJson<UseCaseDetail>(path, { cache: "no-store" });
  } catch (error) {
    if (error instanceof ContentApiError && error.status === 404) return null;
    throw error;
  }
});
