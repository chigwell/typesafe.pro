import { Database, ChevronDown } from "lucide-react";
import { Fragment } from "react";
import type { Page, ErrorEvent } from "@/lib/admin";
import { number, date, Pagination } from "./AdminPrimitives";

export function ErrorHistory({ errors, status, errorCode, expandedError, errorPage, loading, onStatus, onErrorCode, onExpandedError, onPage }: { errors?: Page<ErrorEvent>; status: string; errorCode: string; expandedError: string | null; errorPage: number; loading: boolean; onStatus: (value: string) => void; onErrorCode: (value: string) => void; onExpandedError: (value: string | null) => void; onPage: (value: number) => void }) {
  return (
    <section className="admin-section" aria-labelledby="errors-heading">
      <div className="admin-section-heading">
        <h2 id="errors-heading">
          <Database size={18} /> Errors
        </h2>
        <div className="admin-filters">
          <label>
            Status
            <select
              aria-label="Error status"
              value={status}
              onChange={(event) => onStatus(event.target.value)}
            >
              <option value="">All</option>
              {[
                200, 400, 401, 403, 404, 413, 422, 429, 499, 500, 502,
                503, 504, 529,
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Error
            <select
              aria-label="Error code"
              value={errorCode}
              onChange={(event) => onErrorCode(event.target.value)}
            >
              <option value="">All</option>
              {[
                "endpoint_not_found",
                "method_not_allowed",
                "unsupported_media_type",
                "invalid_json",
                "invalid_request",
                "upstream_error",
                "invalid_upstream_response",
                "rate_limit_exceeded",
                "queue_timeout",
                "queue_full",
                "client_disconnected",
                "upstream_timeout",
                "upstream_unavailable",
                "request_timeout",
                "request_too_large",
                "limiter_unavailable",
                "internal_error",
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="admin-table-wrap">
        <table className="admin-error-table">
          <thead>
            <tr>
              <th>Time / Request</th>
              <th>Status</th>
              <th>Error / Path</th>
              <th>Client</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {errors?.items.map((row) => (
              <Fragment key={row.id}>
                <tr>
                  <td>
                    <span>{date(row.created_at)}</span>
                    <button
                      className="admin-row-toggle"
                      aria-expanded={expandedError === row.id}
                      aria-label={`Details for ${row.request_id}`}
                      onClick={() =>
                        onExpandedError(
                          expandedError === row.id ? null : row.id,
                        )
                      }
                    >
                      <ChevronDown size={14} />
                      <code>{row.request_id}</code>
                    </button>
                  </td>
                  <td>
                    <span className="admin-status-code">
                      {row.status}
                    </span>
                  </td>
                  <td>
                    <b>{row.error_code}</b>
                    <small>
                      {row.method} {row.path}
                    </small>
                  </td>
                  <td>
                    <code>{row.client_ip ?? "Unknown"}</code>
                    <small>{row.client_tier}</small>
                  </td>
                  <td>{number(row.duration_ms)} ms</td>
                </tr>
                {expandedError === row.id && (
                  <tr>
                    <td colSpan={5} className="admin-error-detail">
                      <pre>{JSON.stringify(row, null, 2)}</pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {!errors?.items.length && (
              <tr>
                <td colSpan={5} className="admin-empty">
                  {errors
                    ? "No errors match these filters"
                    : loading
                      ? "Loading errors..."
                      : "Error history unavailable"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        label="errors"
        data={errors}
        page={errorPage}
        onPage={onPage}
        disabled={loading || !errors}
      />
    </section>
  );
}
