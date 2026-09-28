import type { UseCaseCard } from "@/lib/content-api";

const QUESTION_LABEL = { choice: "Choice", noul: "Yes / no", score: "Score" } as const;

export function UseCaseCards({ items }: { items: UseCaseCard[] }) {
  return <div className="use-case-grid">{items.map((item) => <a className="use-case-card" key={item.slug} href={`/use-cases/${item.slug}`}>
    <p className="eyebrow">{item.category?.name ?? item.industry}</p>
    <h2>{item.title}</h2>
    <p>{item.summary}</p>
    <div className="use-case-card-meta">
      {item.question_types.map((type) => <span className="use-case-chip" key={type}>{QUESTION_LABEL[type]}</span>)}
      {item.has_demo ? <span className="use-case-chip is-demo">Interactive demo</span> : null}
    </div>
    <span className="use-case-card-link">Read the example →</span>
  </a>)}</div>;
}

export function UseCaseCardSkeletons({ count = 6 }: { count?: number }) {
  return <div className="use-case-grid" aria-hidden="true">{Array.from({ length: count }, (_, index) => <div className="use-case-card is-skeleton" key={index}>
    <span className="skeleton skeleton-line is-short" />
    <span className="skeleton skeleton-title" />
    <span className="skeleton skeleton-line" />
    <span className="skeleton skeleton-line" />
    <span className="skeleton skeleton-line is-short" />
  </div>)}</div>;
}
