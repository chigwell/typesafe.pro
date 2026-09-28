"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { UseCaseCardSkeletons, UseCaseCards } from "./UseCaseCatalog";
import { type Facets, type ListQuery, type UseCaseList, listUseCases, PAGE_SIZE } from "@/lib/content-api";

export type BrowserQuery = { q: string; category: string; tag: string; page: number };

export function queryHref(query: BrowserQuery) {
  const params = new URLSearchParams();
  if (query.q.trim()) params.set("q", query.q.trim());
  if (query.category) params.set("category", query.category);
  if (query.tag) params.set("tag", query.tag);
  if (query.page > 1) params.set("page", String(query.page));
  const text = params.toString();
  return text ? `/use-cases?${text}` : "/use-cases";
}

type Props = { initial: UseCaseList | null; facets: Facets | null; query: BrowserQuery; debounceMs?: number };

export function UseCaseBrowser({ initial, facets, query: initialQuery, debounceMs = 300 }: Props) {
  const [query, setQuery] = useState(initialQuery);
  const [text, setText] = useState(initialQuery.q);
  const [result, setResult] = useState<UseCaseList | null>(initial);
  const [loading, setLoading] = useState(!initial);
  const [error, setError] = useState(initial ? "" : "The use cases could not be loaded.");
  const [attempt, setAttempt] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const first = useRef(true);

  // Debounce typing into the committed query.
  useEffect(() => {
    if (text === query.q) return;
    const timer = setTimeout(() => setQuery((current) => ({ ...current, q: text, page: 1 })), debounceMs);
    return () => clearTimeout(timer);
  }, [text, query.q, debounceMs]);

  useEffect(() => {
    if (first.current && initial) {
      first.current = false;
      return;
    }
    first.current = false;
    window.history.replaceState(null, "", queryHref(query));
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setLoading(true);
    setError("");
    const request: ListQuery = { q: query.q, category: query.category, tag: query.tag, page: query.page, page_size: PAGE_SIZE };
    listUseCases(request, { signal: current.signal })
      .then((data) => {
        if (current.signal.aborted) return;
        setResult(data);
        setLoading(false);
      })
      .catch(() => {
        if (current.signal.aborted) return;
        setError("The use cases could not be loaded. Check your connection and try again.");
        setLoading(false);
      });
    return () => current.abort();
  }, [query, attempt, initial]);

  const pages = useMemo(() => (result ? Math.max(1, Math.ceil(result.total / result.page_size)) : 1), [result]);
  const update = (patch: Partial<BrowserQuery>) => setQuery((current) => ({ ...current, ...patch, page: patch.page ?? 1 }));
  const filtered = Boolean(query.q.trim() || query.category || query.tag);

  return <section className="use-case-browser" aria-label="Browse use cases">
    <form className="use-case-filters" role="search" onSubmit={(event) => { event.preventDefault(); update({ q: text }); }}>
      <label className="use-case-search">
        <span className="visually-hidden">Search use cases</span>
        <input type="search" value={text} maxLength={200} placeholder="Search use cases, e.g. support, reviews, tone" onChange={(event) => setText(event.target.value)} />
      </label>
      <label>
        <span className="visually-hidden">Category</span>
        <select value={query.category} onChange={(event) => update({ category: event.target.value })}>
          <option value="">All categories</option>
          {facets?.categories.map((category) => <option key={category.slug} value={category.slug} disabled={!category.count && category.slug !== query.category}>{category.name} ({category.count})</option>)}
        </select>
      </label>
    </form>
    {facets?.tags.length ? <div className="use-case-tags" aria-label="Filter by tag">
      {facets.tags.slice(0, 16).map((tag) => <button type="button" key={tag.slug} className={`use-case-chip ${query.tag === tag.slug ? "is-active" : ""}`} aria-pressed={query.tag === tag.slug} onClick={() => update({ tag: query.tag === tag.slug ? "" : tag.slug })}>{tag.name}</button>)}
    </div> : null}
    <p className="use-case-count" aria-live="polite">
      {loading ? "Loading use cases…" : error ? "" : `${result?.total ?? 0} use case${result?.total === 1 ? "" : "s"}${filtered ? " found" : ""}`}
      {filtered && !loading ? <button type="button" className="use-case-clear" onClick={() => { setText(""); setQuery({ q: "", category: "", tag: "", page: 1 }); }}>Clear filters</button> : null}
    </p>
    {error ? <div className="use-case-empty" role="alert"><h2>Something went wrong.</h2><p>{error}</p><button type="button" className="btn btn-secondary btn-small" onClick={() => setAttempt((value) => value + 1)}>Try again</button></div>
      : loading ? <UseCaseCardSkeletons count={Math.min(result?.items.length || 6, 9)} />
      : result && result.items.length ? <UseCaseCards items={result.items} />
      : <div className="use-case-empty"><h2>No use cases match.</h2><p>Try another word, or clear the filters.</p></div>}
    {!error && pages > 1 ? <nav className="use-case-pagination" aria-label="Use case pagination">
      {query.page > 1 ? <a href={queryHref({ ...query, page: query.page - 1 })} rel="prev" onClick={(event) => { event.preventDefault(); update({ page: query.page - 1 }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>← Previous</a> : <span />}
      <span>Page {query.page} of {pages}</span>
      {query.page < pages ? <a href={queryHref({ ...query, page: query.page + 1 })} rel="next" onClick={(event) => { event.preventDefault(); update({ page: query.page + 1 }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Next →</a> : <span />}
    </nav> : null}
  </section>;
}
