import { Footer } from "./Footer";
import { Header } from "./Header";
import { PublicPageViewTracker } from "./PublicPageViewTracker";
import { catalogPageCount, catalogUrl, readUseCaseCatalog } from "@/lib/use-cases";
import { USE_CASES_PAGE_SIZE, type UseCasePage } from "@/lib/use-case-types";

export function UseCaseCards({ pages }: { pages: UseCasePage[] }) {
  return <div className="use-case-grid">{pages.map((page) => <a className="use-case-card" key={page.slug} href={`/use-cases/${page.slug}`}><p className="eyebrow">{page.industry}</p><h2>{page.seo.title}</h2><p>{page.summary}</p><span className="use-case-card-link">Read the example →</span></a>)}</div>;
}

export function UseCaseCatalog({ page = 1 }: { page?: number }) {
  const { pages } = readUseCaseCatalog();
  const sorted = [...pages].sort((a, b) => b.created_at.localeCompare(a.created_at) || a.slug.localeCompare(b.slug));
  const count = catalogPageCount(pages);
  return <>
    <a className="skip-link" href="#use-case-catalog">Skip to use cases</a>
    <Header />
    <PublicPageViewTracker path={catalogUrl(page)} />
    <main className="container use-cases-main" id="use-case-catalog">
      <p className="eyebrow">Small decisions in real workflows</p>
      <h1>TypeSafe use cases{page > 1 ? ` — page ${page}` : ""}</h1>
      <p className="use-case-lede">Explore practical ways to turn text and application data into typed choices, yes/no probabilities, and scores. Each guide includes API-verified examples you can edit and try.</p>
      {pages.length ? <UseCaseCards pages={sorted.slice((page - 1) * USE_CASES_PAGE_SIZE, page * USE_CASES_PAGE_SIZE)} /> : <div className="use-case-empty"><h2>Examples are on their way.</h2><p>Meanwhile, explore choices, probabilities, and scores in the <a href="/#playground">TypeSafe playground</a>.</p></div>}
      {count > 1 ? <nav className="use-case-pagination" aria-label="Use case pagination">{page > 1 ? <a href={catalogUrl(page - 1)} rel="prev">← Previous</a> : <span />}<span>Page {page} of {count}</span>{page < count ? <a href={catalogUrl(page + 1)} rel="next">Next →</a> : <span />}</nav> : null}
    </main>
    <Footer />
  </>;
}
