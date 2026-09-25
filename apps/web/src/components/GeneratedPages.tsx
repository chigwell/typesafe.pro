"use client";

import { ArrowLeft, ArrowRight, FileText } from "lucide-react";
import type { Page, SeoPage, SeoRun, SeoSummary } from "@/lib/admin";

const number = (value?: number | null) =>
  value == null ? "Unavailable" : new Intl.NumberFormat("en").format(value);
const date = (value?: string | null) =>
  value == null ? "Not yet published" : new Date(value).toLocaleString();

function Pagination({ label, data, page, onPage, loading }: {
  label: string;
  data?: Page<unknown>;
  page: number;
  onPage: (page: number) => void;
  loading: boolean;
}) {
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / (data?.page_size ?? 25)));
  return <div className="admin-pagination">
    <span>{data ? `${number(data.total)} records` : "Unavailable"}</span>
    <div>
      <button className="admin-icon" aria-label={`Previous ${label} page`}
        disabled={loading || !data || page <= 1} onClick={() => onPage(page - 1)}>
        <ArrowLeft size={16} />
      </button>
      <span>Page {page} of {pages}</span>
      <button className="admin-icon" aria-label={`Next ${label} page`}
        disabled={loading || !data || page >= pages} onClick={() => onPage(page + 1)}>
        <ArrowRight size={16} />
      </button>
    </div>
  </div>;
}

function Attempt({ run }: { run: SeoRun }) {
  return <>
    <strong>{run.status}</strong>
    {run.status === "published" && run.generation_status !== "prepared" && (
      <small>Generation {run.generation_status}; deployment confirmed.</small>
    )}
    <small>{number(run.generated_count)} generated · {number(run.rejected_count)} rejected · {number(run.duration_seconds)}s</small>
    {run.reason && <small>{run.reason}</small>}
    {Object.keys(run.rejections).length > 0 && <small>
      {Object.entries(run.rejections).map(([reason, count]) => `${reason}: ${number(count)}`).join(" · ")}
    </small>}
  </>;
}

export default function GeneratedPages({ summary, pages, runs, page, runPage, onPage, onRunPage, loading }: {
  summary?: SeoSummary;
  pages?: Page<SeoPage>;
  runs?: Page<SeoRun>;
  page: number;
  runPage: number;
  onPage: (page: number) => void;
  onRunPage: (page: number) => void;
  loading: boolean;
}) {
  return <section className="admin-section" aria-labelledby="generated-pages-heading">
    <div className="admin-section-heading">
      <h2 id="generated-pages-heading"><FileText size={18} /> Generated pages</h2>
      <span>Verified production publications</span>
    </div>
    <div className="admin-totals">
      <div className="admin-metric"><span>Published pages</span><strong>{number(summary?.total_pages)}</strong></div>
      <div className="admin-metric"><span>Added in last successful deploy</span><strong>{number(summary?.added_last_deploy)}</strong><small>{date(summary?.latest_publication?.published_at)}</small></div>
      <div className="admin-metric"><span>Last generation attempt</span>
        {summary?.latest_attempt ? <Attempt run={summary.latest_attempt} /> : <strong>{summary ? "No runs yet" : "Unavailable"}</strong>}
      </div>
      <div className="admin-metric"><span>Generation API calls</span><strong>{number(summary?.totals.api_calls)}</strong><small>{number(summary?.totals.runs)} runs</small></div>
      <div className="admin-metric"><span>Reported generation tokens</span><strong>{number(summary?.totals.input_tokens)} in / {number(summary?.totals.output_tokens)} out</strong><small>Only provider-reported token usage</small></div>
    </div>
    <p className="admin-notice">Views cover all recorded dates. Daily unique visitors count one visitor per IP, page and day.</p>
    <div className="admin-table-wrap"><table>
      <thead><tr><th>Page</th><th>Published</th><th>Updated</th><th>Daily unique visitors</th><th>Page hits</th></tr></thead>
      <tbody>
        {pages?.items.map(row => <tr key={row.slug}>
          <td><a href={row.path}>{row.title}</a><small>{row.path}</small></td>
          <td>{date(row.published_at)}</td><td>{date(row.updated_at)}</td>
          <td>{number(row.unique_visitors)}</td><td>{number(row.total_hits)}</td>
        </tr>)}
        {!pages?.items.length && <tr><td colSpan={5} className="admin-empty">{pages ? "No generated pages published yet" : loading ? "Loading generated pages..." : "Generated pages unavailable"}</td></tr>}
      </tbody>
    </table></div>
    <Pagination label="generated pages" data={pages} page={page} onPage={onPage} loading={loading} />
    <div className="admin-section-heading"><h3>Generation history</h3><span>Publication is confirmed after deployment</span></div>
    <div className="admin-table-wrap"><table>
      <thead><tr><th>Started / Run</th><th>Result</th><th>API calls</th><th>Tokens in / out</th><th>Published</th></tr></thead>
      <tbody>
        {runs?.items.map(run => <tr key={run.run_id}>
          <td>{date(run.started_at)}<small><code>{run.run_id}</code></small></td>
          <td><Attempt run={run} /></td><td>{number(run.api_calls)}</td>
          <td>{number(run.input_tokens)} / {number(run.output_tokens)}</td><td>{date(run.published_at)}</td>
        </tr>)}
        {!runs?.items.length && <tr><td colSpan={5} className="admin-empty">{runs ? "No generation runs yet" : loading ? "Loading generation history..." : "Generation history unavailable"}</td></tr>}
      </tbody>
    </table></div>
    <Pagination label="generation history" data={runs} page={runPage} onPage={onRunPage} loading={loading} />
  </section>;
}
