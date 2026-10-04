import { Activity, ChevronDown } from "lucide-react";
import type { Summary, ActivityWindow } from "@/lib/admin";
import { number, Metric } from "./AdminPrimitives";

export function ApiActivity({ summary, window }: { summary?: Summary; window: ActivityWindow }) {
  const totals = summary?.totals;
  return (
    <section className="admin-section" aria-labelledby="activity-heading">
      <div className="admin-section-heading">
        <h2 id="activity-heading">
          <Activity size={18} /> API activity
        </h2>
        <span>{window} window</span>
      </div>
      <div className="admin-totals">
        <Metric
          label="Requests"
          value={number(totals?.requests)}
          detail={
            totals
              ? `${number(totals.avg_duration_ms)} ms average`
              : undefined
          }
        />
        <Metric label="Unique IPs" value={number(totals?.unique_ips)} />
        <Metric
          label="Errors"
          value={number(totals?.errors)}
          detail={
            totals
              ? `${number(totals.requests ? (totals.errors / totals.requests) * 100 : 0)}% of requests`
              : undefined
          }
        />
        <Metric
          label="Rate limited"
          value={number(totals?.rate_limited)}
          detail="HTTP 429"
        />
        <Metric
          label="Upstream requests"
          value={number(totals?.upstream_requests)}
          detail={
            totals
              ? `${number(totals.avg_upstream_ms)} ms average`
              : undefined
          }
        />
        <Metric
          label="Usage tokens"
          value={number(totals?.usage_tokens)}
          detail={
            totals
              ? `${number(totals.estimated_tokens)} estimated / ${number(totals.usage_reported_requests)} reports`
              : undefined
          }
        />
      </div>
      <div className="admin-breakdowns">
        <div>
          <h3>Client tiers</h3>
          {summary?.tiers.length ? (
            summary.tiers.map((row) => (
              <p key={row.name}>
                <span>{row.name}</span>
                <b>{number(row.requests)}</b>
              </p>
            ))
          ) : (
            <p>{summary ? "No activity" : "Unavailable"}</p>
          )}
        </div>
        <div>
          <h3>Response status</h3>
          {summary && Object.keys(summary.status_codes).length ? (
            Object.entries(summary.status_codes).map(([name, count]) => (
              <p key={name}>
                <span>HTTP {name}</span>
                <b>{number(count)}</b>
              </p>
            ))
          ) : (
            <p>{summary ? "No responses" : "Unavailable"}</p>
          )}
        </div>
        <div>
          <h3>Upstream status</h3>
          {summary && Object.keys(summary.upstream_statuses).length ? (
            Object.entries(summary.upstream_statuses).map(
              ([name, count]) => (
                <p key={name}>
                  <span>HTTP {name}</span>
                  <b>{number(count)}</b>
                </p>
              ),
            )
          ) : (
            <p>{summary ? "No responses" : "Unavailable"}</p>
          )}
        </div>
        <div>
          <h3>Master keys</h3>
          {summary?.masters.length ? (
            summary.masters.map((row) => (
              <p key={row.name}>
                <span>
                  Key {row.name}{" "}
                  <small>{number(row.avg_upstream_ms)} ms</small>
                </span>
                <b>{number(row.requests)}</b>
              </p>
            ))
          ) : (
            <p>{summary ? "No activity" : "Unavailable"}</p>
          )}
        </div>
      </div>
      <details className="admin-paths">
        <summary>
          <ChevronDown size={16} /> Top paths
        </summary>
        {summary?.paths.map((row) => (
          <p key={row.name}>
            <code>{row.name}</code>
            <b>{number(row.requests)}</b>
          </p>
        ))}
        {summary?.paths.length === 0 && <p>No activity</p>}
      </details>
    </section>
  );
}
