import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCaseDemoFixture, useCaseFixture } from "@/test/use-case-fixture";
import type { UseCaseDetail, UseCaseList } from "@/lib/content-api";

const api = vi.hoisted(() => ({
  detail: null as unknown,
  list: null as unknown,
  listError: false,
  calls: [] as unknown[],
}));
vi.mock("@/lib/content-api", async (load) => ({
  ...(await load<object>()),
  getUseCase: async (slug: string, preview?: string) => {
    api.calls.push({ slug, preview });
    return api.detail;
  },
  listUseCases: async (query: unknown) => {
    api.calls.push(query);
    if (api.listError) throw new Error("down");
    return api.list;
  },
  useCaseFacets: async () => ({ total: 1, categories: [{ slug: "routing-triage", name: "Routing & triage", description: "", count: 1 }], tags: [{ slug: "support", name: "support", count: 1 }] }),
}));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  permanentRedirect: (url: string) => { throw new Error(`REDIRECT ${url}`); },
}));
import DetailPage, { generateMetadata } from "./[slug]/page";
import ListingPage, { generateMetadata as listingMetadata } from "./(catalog)/page";
import LegacyPage from "./page/[page]/page";

const card = (slug: string) => ({ slug, title: `Title ${slug}`, summary: "Summary", industry: "Support", audience: "Teams", task_type: "routing", question_types: ["choice" as const], has_demo: true, category: { slug: "routing-triage", name: "Routing & triage" }, tags: [{ slug: "support", name: "support" }], published_at: "2026-09-25T12:00:00Z", updated_at: "2026-09-25T12:00:00Z" });

function detail(status: "draft" | "published" = "published"): UseCaseDetail {
  const page = { ...useCaseFixture(), demo: useCaseDemoFixture() };
  return { ...card(page.slug), status, page, related: [card("other-case")] } as UseCaseDetail;
}

const props = (slug: string, search: Record<string, string> = {}) => ({ params: Promise.resolve({ slug }), searchParams: Promise.resolve(search) });

beforeEach(() => {
  api.detail = detail();
  api.list = { items: [card("sort-maintenance-requests")], total: 30, page: 1, page_size: 24 } satisfies UseCaseList;
  api.listError = false;
  api.calls = [];
});

describe("use-case detail page from the API", () => {
  it("renders the article, examples, demo and JSON-LD on the server", async () => {
    const markup = renderToStaticMarkup(await DetailPage(props("sort-maintenance-requests")));
    const page = (api.detail as UseCaseDetail).page;
    expect(markup).toContain(page.problem);
    expect(markup).toContain("Previous verification response");
    expect(markup).toContain("TechArticle");
    expect(markup).toContain("BreadcrumbList");
    expect(markup).toContain("urllib");
    expect(markup).toContain('sandbox="allow-scripts"');
    expect(markup).toContain('href="/use-cases?tag=support"');
    expect(markup).toContain('href="/use-cases?category=routing-triage"');
    expect(markup).toContain("Title other-case");
    expect(markup).not.toContain("use-case-draft-banner");
    const metadata = await generateMetadata(props("sort-maintenance-requests"));
    expect(metadata).toMatchObject({ title: page.seo.title, alternates: { canonical: `https://typesafe.pro/use-cases/${page.slug}` } });
    expect(metadata.robots).toBeUndefined();
  });
  it("shows drafts only through a preview token, marked and not indexable", async () => {
    api.detail = detail("draft");
    const markup = renderToStaticMarkup(await DetailPage(props("sort-maintenance-requests", { preview: "123.abc" })));
    expect(markup).toContain("Draft preview");
    expect(api.calls).toContainEqual({ slug: "sort-maintenance-requests", preview: "123.abc" });
    const metadata = await generateMetadata(props("sort-maintenance-requests", { preview: "123.abc" }));
    expect(metadata.robots).toEqual({ index: false, follow: false });
  });
  it("returns notFound when the API has no such page", async () => {
    api.detail = null;
    await expect(DetailPage(props("missing"))).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("use-case listing", () => {
  it("renders the first results on the server with pagination links", async () => {
    const markup = renderToStaticMarkup(await ListingPage({ searchParams: Promise.resolve({}) }));
    expect(markup).toContain("Title sort-maintenance-requests");
    expect(markup).toContain("30 use cases");
    expect(markup).toContain('href="/use-cases?page=2"');
    expect(markup).toContain("Routing &amp; triage (1)");
  });
  it("passes URL filters to the API and keeps filtered views out of the index", async () => {
    await ListingPage({ searchParams: Promise.resolve({ q: "refund", tag: "support", category: "Bad Value", page: "3" }) });
    expect(api.calls[0]).toMatchObject({ q: "refund", tag: "support", category: "", page: 3 });
    const metadata = await listingMetadata({ searchParams: Promise.resolve({ q: "refund" }) });
    expect(metadata.robots).toEqual({ index: false, follow: true });
    expect(metadata.alternates).toEqual({ canonical: "https://typesafe.pro/use-cases" });
    const paged = await listingMetadata({ searchParams: Promise.resolve({ page: "2" }) });
    expect(paged.alternates).toEqual({ canonical: "https://typesafe.pro/use-cases?page=2" });
  });
  it("degrades to a retry state instead of failing when the API is down", async () => {
    api.listError = true;
    const markup = renderToStaticMarkup(await ListingPage({ searchParams: Promise.resolve({}) }));
    expect(markup).toContain("could not be loaded");
    expect(markup).toContain("Try again");
  });
  it("redirects the former static pagination", async () => {
    await expect(LegacyPage({ params: Promise.resolve({ page: "2" }) })).rejects.toThrow("REDIRECT /use-cases?page=2");
    await expect(LegacyPage({ params: Promise.resolve({ page: "x" }) })).rejects.toThrow("REDIRECT /use-cases");
  });
});
