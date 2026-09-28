import type { Metadata } from "next";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { PublicPageViewTracker } from "@/components/PublicPageViewTracker";
import { UseCaseBrowser } from "@/components/UseCaseBrowser";
import { type Facets, listUseCases, PAGE_SIZE, type UseCaseList, useCaseFacets } from "@/lib/content-api";
import { OG_IMAGE_URL, SITE_URL } from "@/lib/seo";
import { readQuery, type Search } from "@/lib/use-case-query";

export const dynamic = "force-dynamic";

export async function generateMetadata({ searchParams }: { searchParams: Search }): Promise<Metadata> {
  const query = await readQuery(searchParams);
  const filtered = Boolean(query.q || query.category || query.tag);
  const url = query.page > 1 && !filtered ? `${SITE_URL}/use-cases?page=${query.page}` : `${SITE_URL}/use-cases`;
  return {
    title: query.page > 1 && !filtered ? `TypeSafe Use Cases — page ${query.page}` : "TypeSafe Use Cases — Practical Jev API Examples",
    description: "Explore TypeSafe Jev use cases with verified API examples, interactive demos, editable requests, and code in seven languages. Build typed choices, probabilities, and scores.",
    alternates: { canonical: url },
    robots: filtered ? { index: false, follow: true } : undefined,
    openGraph: { title: "TypeSafe Use Cases", description: "Practical Jev API examples you can edit and try.", url, images: [OG_IMAGE_URL] },
  };
}

export default async function Page({ searchParams }: { searchParams: Search }) {
  const query = await readQuery(searchParams);
  const [list, facets] = await Promise.allSettled([
    listUseCases({ ...query, page_size: PAGE_SIZE }),
    useCaseFacets(),
  ]);
  const initial: UseCaseList | null = list.status === "fulfilled" ? list.value : null;
  const filters: Facets | null = facets.status === "fulfilled" ? facets.value : null;
  return <>
    <a className="skip-link" href="#use-case-catalog">Skip to use cases</a>
    <Header />
    <PublicPageViewTracker path="/use-cases" />
    <main className="container use-cases-main" id="use-case-catalog">
      <p className="eyebrow">Small decisions in real workflows</p>
      <h1>TypeSafe use cases{query.page > 1 ? ` — page ${query.page}` : ""}</h1>
      <p className="use-case-lede">Explore practical ways to turn text and application data into typed choices, yes/no probabilities, and scores. Each guide includes API-verified examples, an interactive demo, and requests you can edit and try.</p>
      <UseCaseBrowser initial={initial} facets={filters} query={query} />
    </main>
    <Footer />
  </>;
}
