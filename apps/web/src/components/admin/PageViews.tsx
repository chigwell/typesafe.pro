import { BarChart3 } from "lucide-react";
import type { Page, PageViewRow } from "@/lib/admin";
import { number, date, Pagination } from "./AdminPrimitives";

export function PageViews({ pageViews, viewsFrom, viewsTo, viewPage, loading, onFrom, onTo, onPage }: { pageViews?: Page<PageViewRow>; viewsFrom: string; viewsTo: string; viewPage: number; loading: boolean; onFrom: (value: string) => void; onTo: (value: string) => void; onPage: (value: number) => void }) {
  return (
    <section
      className="admin-section"
      aria-labelledby="page-views-heading"
    >
      <div className="admin-section-heading">
        <h2 id="page-views-heading">
          <BarChart3 size={18} /> Page views
        </h2>
        <div className="admin-filters">
          <label>
            From
            <input
              type="date"
              aria-label="Page views from"
              value={viewsFrom}
              max={viewsTo}
              required
              onChange={(event) => onFrom(event.target.value)}
            />
          </label>
          <label>
            To
            <input
              type="date"
              aria-label="Page views to"
              value={viewsTo}
              min={viewsFrom}
              required
              onChange={(event) => onTo(event.target.value)}
            />
          </label>
        </div>
      </div>
      <div className="admin-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Path</th>
              <th>Unique visitors</th>
              <th>Total hits</th>
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {pageViews?.items.map((row) => (
              <tr key={`${row.date}:${row.path}`}>
                <td>{row.date}</td>
                <td>
                  <code>{row.path}</code>
                </td>
                <td>{number(row.unique_visitors)}</td>
                <td>{number(row.total_hits)}</td>
                <td>
                  {date(row.last_seen_at)}
                  <small>First {date(row.first_seen_at)}</small>
                </td>
              </tr>
            ))}
            {!pageViews?.items.length && (
              <tr>
                <td colSpan={5} className="admin-empty">
                  {pageViews
                    ? "No public page views in this range"
                    : loading
                      ? "Loading page views..."
                      : "Page views unavailable"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        label="page views"
        data={pageViews}
        page={viewPage}
        onPage={onPage}
        disabled={loading || !pageViews}
      />
    </section>
  );
}
