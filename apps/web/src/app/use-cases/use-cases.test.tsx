import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useCaseFixture } from "@/test/use-case-fixture";
import type { UseCasePage } from "@/lib/use-case-types";

const catalog = vi.hoisted(() => ({ pages: [] as UseCasePage[] }));
vi.mock("@/lib/use-cases", async (load) => ({ ...await load<object>(), readUseCaseCatalog: () => catalog }));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));
import DetailPage, { generateMetadata, generateStaticParams } from "./[slug]/page";
import CatalogPage from "./page/[page]/page";

describe("static use-case routes", () => {
  it("renders the article, all inputs and response JSON without JavaScript", async () => {
    const page = useCaseFixture();
    page.examples.reverse();
    catalog.pages = [page];
    const markup = renderToStaticMarkup(await DetailPage({ params: Promise.resolve({ slug: page.slug }) }));
    expect(markup).toContain(page.problem);
    expect(markup).toContain("Something needs attention.");
    expect(markup).toContain("Previous verification response");
    expect(markup).toContain("TechArticle");
    expect(markup).toContain("BreadcrumbList");
    expect(markup).toContain("urllib");
    // The primary request is initial state even if the data array is unordered.
    expect(markup.match(/<textarea[^>]+id="use-case-request"[^>]*>([\s\S]*?)<\/textarea>/)?.[1]).toContain("sink is leaking");
    expect(markup).not.toContain("View count");
    expect(await generateMetadata({ params: Promise.resolve({ slug: page.slug }) })).toMatchObject({ title: page.seo.title, alternates: { canonical: `https://typesafe.pro/use-cases/${page.slug}` } });
    expect(generateStaticParams()).toEqual([{ slug: page.slug }]);
  });
  it("returns notFound for unknown slugs and out-of-range catalog pages", async () => {
    catalog.pages = [useCaseFixture()];
    await expect(DetailPage({ params: Promise.resolve({ slug: "missing" }) })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(CatalogPage({ params: Promise.resolve({ page: "2" }) })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(CatalogPage({ params: Promise.resolve({ page: "1" }) })).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
