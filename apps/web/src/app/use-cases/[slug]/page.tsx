import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { PublicPageViewTracker } from "@/components/PublicPageViewTracker";
import { UseCaseCards } from "@/components/UseCaseCatalog";
import { UseCasePlayground } from "@/components/UseCasePlayground";
import { readUseCaseCatalog } from "@/lib/use-cases";
import { jsonLd, OG_IMAGE_URL, SITE_NAME, SITE_URL } from "@/lib/seo";

export const dynamicParams = false;
export function generateStaticParams() {
  const { pages } = readUseCaseCatalog();
  return pages.length ? pages.map(({ slug }) => ({ slug })) : [{ slug: "_empty" }];
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const page = readUseCaseCatalog().pages.find((item) => item.slug === slug);
  if (!page) return {};
  const url = `${SITE_URL}/use-cases/${page.slug}`;
  return {
    title: page.seo.title,
    description: page.seo.description,
    alternates: { canonical: url },
    openGraph: { type: "article", title: page.seo.title, description: page.seo.description, url, siteName: SITE_NAME, publishedTime: page.created_at, modifiedTime: page.updated_at, images: [OG_IMAGE_URL] },
    twitter: { card: "summary_large_image", title: page.seo.title, description: page.seo.description, images: [OG_IMAGE_URL] },
  };
}

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const { pages } = readUseCaseCatalog();
  const page = pages.find((item) => item.slug === slug);
  if (!page) notFound();
  const exampleOrder = { primary: 0, alternative: 1, edge: 2 };
  const examples = [...page.examples].sort((a, b) => exampleOrder[a.kind] - exampleOrder[b.kind]);
  const url = `${SITE_URL}/use-cases/${page.slug}`;
  const related = pages.filter((item) => item.slug !== slug).sort((a, b) => Number(b.task_type === page.task_type) - Number(a.task_type === page.task_type) || Number(b.industry === page.industry) - Number(a.industry === page.industry) || a.slug.localeCompare(b.slug)).slice(0, 3);
  const structured = { "@context": "https://schema.org", "@graph": [
    { "@type": "TechArticle", headline: page.seo.title, description: page.seo.description, url, mainEntityOfPage: url, datePublished: page.created_at, dateModified: page.updated_at, inLanguage: "en", author: { "@type": "Organization", name: SITE_NAME, url: SITE_URL }, about: page.task_type, articleBody: [page.intro, page.problem, page.solution, ...page.limitations].join("\n\n") },
    { "@type": "BreadcrumbList", itemListElement: [{ "@type": "ListItem", position: 1, name: "Home", item: SITE_URL }, { "@type": "ListItem", position: 2, name: "Use cases", item: `${SITE_URL}/use-cases` }, { "@type": "ListItem", position: 3, name: page.seo.title, item: url }] },
  ] };
  return <>
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(structured) }} />
    <a className="skip-link" href="#use-case-article">Skip to guide</a>
    <Header />
    <PublicPageViewTracker path={`/use-cases/${page.slug}`} />
    <main className="container use-cases-main" id="use-case-article">
      <nav className="use-case-breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a><span>/</span><a href="/use-cases">Use cases</a><span>/</span><span>{page.industry}</span></nav>
      <article>
        <header className="use-case-hero"><p className="eyebrow">{page.industry} · {page.audience}</p><h1>{page.seo.title}</h1><p className="use-case-lede">{page.intro}</p><p className="use-case-date">Updated <time dateTime={page.updated_at}>{page.updated_at.slice(0, 10)}</time> · Examples verified with {page.verification.model}</p></header>
        <div className="use-case-prose"><section><h2>The problem</h2><p>{page.problem}</p></section><section><h2>How TypeSafe helps</h2><p>{page.solution}</p><dl><dt>Input</dt><dd>{page.input_description}</dd><dt>Decision</dt><dd>{page.decision}</dd><dt>Next action</dt><dd>{page.action}</dd></dl></section></div>
        <section className="use-case-examples" id="examples"><h2>Three verified examples</h2><p>These responses were returned during a previous API verification. New probabilities can differ.</p>{page.examples.map((example) => <details key={example.kind} open={example.kind === "primary"}><summary>{example.name} <span>({example.kind === "edge" ? "edge case" : example.kind})</span></summary><p><strong>Expected behavior:</strong> {example.expected_description}</p><h3>Input</h3><pre><code>{typeof example.request.state === "string" ? example.request.state : JSON.stringify(example.request.state, null, 2)}</code></pre><h3>Previous verification response</h3><p className="field-help">{example.response.model} · <time dateTime={example.verified_at}>{example.verified_at.slice(0, 10)}</time></p><pre><code>{JSON.stringify(example.response, null, 2)}</code></pre></details>)}</section>
        <UseCasePlayground examples={examples} />
        <section className="use-case-prose"><h2>Limitations and review</h2><ul>{page.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul><p>Set thresholds against your own examples before relying on an automated decision.</p></section>
      </article>
      {related.length ? <section className="use-case-related"><h2>Related use cases</h2><UseCaseCards pages={related} /></section> : null}
      <p className="use-case-back"><a href="/use-cases">← Explore all TypeSafe use cases</a></p>
    </main>
    <Footer />
  </>;
}
