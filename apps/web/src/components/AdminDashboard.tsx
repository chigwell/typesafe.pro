"use client";

import { Fragment, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  Cpu,
  Database,
  HardDrive,
  KeyRound,
  LogOut,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { adminFetch, AdminError } from "@/lib/admin";
import type {
  ActivityWindow,
  ErrorEvent,
  IpActivity,
  Page,
  Sample,
  Summary,
  SystemStatus,
} from "@/lib/admin";

const number = (value?: number | null) =>
  value == null
    ? "Unavailable"
    : new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);
const percent = (value?: number | null) =>
  value == null ? "Unavailable" : `${number(value)}%`;
const bytes = (value?: number | null) =>
  value == null
    ? "Unavailable"
    : value >= 1073741824
      ? `${number(value / 1073741824)} GB`
      : `${number(value / 1048576)} MB`;
const date = (value?: number | string | null) =>
  value == null
    ? "Unavailable"
    : new Date(
        typeof value === "number" ? value * 1000 : value,
      ).toLocaleString();
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Connection unavailable";

function Metric({
  label,
  value,
  detail,
  children,
}: {
  label: string;
  value: string;
  detail?: string;
  children?: ReactNode;
}) {
  return (
    <div className="admin-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
      {children}
    </div>
  );
}

function History({
  samples,
  kind,
}: {
  samples: Sample[];
  kind: "cpu" | "memory";
}) {
  const end = samples.at(-1)?.at ?? Date.now() / 1000;
  const segments: string[] = [];
  let segment: string[] = [];
  for (const sample of samples) {
    const value = kind === "cpu" ? sample.cpu_percent : sample.memory?.percent;
    if (value == null) {
      if (segment.length) segments.push(segment.join(" "));
      segment = [];
      continue;
    }
    segment.push(
      `${Math.max(0, Math.min(600, (sample.at - end + 300) * 2))},${100 - value}`,
    );
  }
  if (segment.length) segments.push(segment.join(" "));
  return (
    <div className={`admin-history ${kind}`}>
      <svg
        viewBox="0 0 600 100"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${kind === "cpu" ? "CPU" : "Memory"} usage over the last five minutes`}
      >
        {[0, 50, 100].map((y) => (
          <line
            key={y}
            x1="0"
            x2="600"
            y1={y}
            y2={y}
            className="admin-gridline"
          />
        ))}
        {segments.map((points, index) => (
          <polyline
            key={index}
            points={points}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      {segments.length === 0 && (
        <span className="admin-chart-empty">Awaiting samples</span>
      )}
      <div className="admin-chart-axis">
        <span>5 min ago</span>
        <span>Now</span>
      </div>
    </div>
  );
}

function Pagination({
  label,
  data,
  page,
  onPage,
  disabled,
}: {
  label: string;
  data?: Page<unknown>;
  page: number;
  onPage: (page: number) => void;
  disabled: boolean;
}) {
  const pages = Math.max(
    1,
    Math.ceil((data?.total ?? 0) / (data?.page_size ?? 25)),
  );
  return (
    <div className="admin-pagination">
      <span>{data ? `${number(data.total)} records` : "Loading"}</span>
      <div>
        <button
          className="admin-icon"
          title={`Previous ${label} page`}
          aria-label={`Previous ${label} page`}
          disabled={disabled || page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <ArrowLeft size={16} />
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button
          className="admin-icon"
          title={`Next ${label} page`}
          aria-label={`Next ${label} page`}
          disabled={disabled || page >= pages}
          onClick={() => onPage(page + 1)}
        >
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [auth, setAuth] = useState<"checking" | "login" | "ready">("checking");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [clock, setClock] = useState(Date.now());
  const [window, setWindow] = useState<ActivityWindow>("24h");
  const [ipPage, setIpPage] = useState(1);
  const [errorPage, setErrorPage] = useState(1);
  const [expandedError, setExpandedError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false);
  const [updated, setUpdated] = useState<number>();
  const [system, setSystem] = useState<SystemStatus>();
  const [summary, setSummary] = useState<Summary>();
  const [ips, setIps] = useState<Page<IpActivity>>();
  const [errors, setErrors] = useState<Page<ErrorEvent>>();
  const [failures, setFailures] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    adminFetch("/auth/session", { signal: controller.signal })
      .then(() => setAuth("ready"))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setAuth("login");
        if (!(error instanceof AdminError && error.status === 401))
          setAuthError(message(error));
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (retryAt <= Date.now()) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [retryAt]);

  useEffect(() => {
    if (auth !== "ready") return;
    const controller = new AbortController();
    let inFlight = false;
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      setLoading(true);
      const opts = { signal: controller.signal };
      const query = new URLSearchParams({
        page: String(errorPage),
        page_size: "25",
      });
      if (status) query.set("status", status);
      if (errorCode) query.set("error_code", errorCode);
      const results = await Promise.allSettled([
        adminFetch<SystemStatus>("/system", opts),
        adminFetch<Summary>(`/summary?window=${window}`, opts),
        adminFetch<Page<IpActivity>>(
          `/ip-activity?window=${window}&page=${ipPage}&page_size=25`,
          opts,
        ),
        adminFetch<Page<ErrorEvent>>(`/errors?${query}`, opts),
      ] as const);
      if (controller.signal.aborted) return;
      if (
        results.some(
          (result) =>
            result.status === "rejected" &&
            result.reason instanceof AdminError &&
            result.reason.status === 401,
        )
      ) {
        setSystem(undefined);
        setSummary(undefined);
        setIps(undefined);
        setErrors(undefined);
        setAuthError("Session expired. Sign in again.");
        setAuth("login");
      } else {
        setSystem(
          results[0].status === "fulfilled" ? results[0].value : undefined,
        );
        setSummary(
          results[1].status === "fulfilled" ? results[1].value : undefined,
        );
        setIps(
          results[2].status === "fulfilled" ? results[2].value : undefined,
        );
        setErrors(
          results[3].status === "fulfilled" ? results[3].value : undefined,
        );
        const labels = ["System", "Activity", "IP activity", "Errors"];
        setFailures(
          results.flatMap((result, index) =>
            result.status === "rejected"
              ? [`${labels[index]}: ${message(result.reason)}`]
              : [],
          ),
        );
        setUpdated(Date.now() / 1000);
      }
      setLoading(false);
      inFlight = false;
    };
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [auth, window, ipPage, errorPage, status, errorCode, refresh]);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setAuthError("");
    try {
      await adminFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setPassword("");
      setRetryAt(0);
      setAuth("ready");
    } catch (error) {
      setAuthError(message(error));
      if (error instanceof AdminError && error.retryAfter) {
        setRetryAt(Date.now() + error.retryAfter * 1000);
        setClock(Date.now());
      }
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
    try {
      await adminFetch("/auth/logout", { method: "POST" });
      setAuthError("");
      setPassword("");
      setSystem(undefined);
      setSummary(undefined);
      setIps(undefined);
      setErrors(undefined);
      setAuth("login");
    } catch (error) {
      setFailures([`Sign out: ${message(error)}`]);
    } finally {
      setBusy(false);
    }
  }

  const cooldown = Math.max(0, Math.ceil((retryAt - clock) / 1000));
  const current = system?.current;
  const totals = summary?.totals;
  return (
    <main className="admin-root">
      <header className="admin-header">
        <a href="/" className="admin-brand">
          <img src="/favicon-32x32.png" width="24" height="24" alt="" />
          TypeSafe.pro <span>Admin</span>
        </a>
        {auth === "ready" && (
          <div className="admin-header-actions">
            <span>
              <ShieldCheck size={15} /> Superadmin
            </span>
            <button
              className="admin-icon"
              aria-label="Sign out"
              title="Sign out"
              disabled={busy}
              onClick={logout}
            >
              <LogOut size={18} />
            </button>
          </div>
        )}
      </header>
      {auth !== "ready" ? (
        <div className="admin-login-wrap">
          {auth === "checking" ? (
            <p role="status">Checking session...</p>
          ) : (
            <form className="admin-login" onSubmit={login}>
              <KeyRound size={26} />
              <h1>Admin sign in</h1>
              <label htmlFor="admin-password">Password</label>
              <input
                id="admin-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                maxLength={256}
                autoFocus
              />
              {authError && (
                <p className="admin-alert" role="alert">
                  {authError}
                </p>
              )}
              {cooldown > 0 && <p role="status">Try again in {cooldown}s</p>}
              <button
                className="admin-primary"
                type="submit"
                disabled={busy || cooldown > 0}
              >
                {busy ? "Signing in..." : "Sign in"}
              </button>
            </form>
          )}
        </div>
      ) : (
        <div className="admin-content">
          <div className="admin-title">
            <div>
              <h1>Overview</h1>
              <p>
                {updated ? `Updated ${date(updated)}` : "Loading metrics..."}
              </p>
            </div>
            <div className="admin-toolbar">
              <div
                className="admin-segments"
                role="group"
                aria-label="Activity window"
              >
                {(["5m", "1h", "24h", "7d"] as const).map((value) => (
                  <button
                    key={value}
                    aria-pressed={window === value}
                    onClick={() => {
                      setWindow(value);
                      setIpPage(1);
                      setSummary(undefined);
                      setIps(undefined);
                    }}
                  >
                    {value}
                  </button>
                ))}
              </div>
              <button
                className="admin-icon"
                title="Refresh"
                aria-label="Refresh"
                disabled={loading}
                onClick={() => setRefresh((value) => value + 1)}
              >
                <RefreshCw size={18} className={loading ? "spinner" : ""} />
              </button>
            </div>
          </div>
          {failures.map((failure) => (
            <p key={failure} role="alert" className="admin-alert">
              {failure}
            </p>
          ))}
          {system?.status === "partial" && (
            <p className="admin-notice" role="status">
              Some system metrics are unavailable.
            </p>
          )}
          {Boolean(
            (system?.telemetry.dropped_errors ?? 0) +
              (system?.telemetry.dropped_activity ?? 0),
          ) && (
            <p className="admin-alert" role="alert">
              Telemetry is incomplete:{" "}
              {number(system?.telemetry.dropped_activity)} activity events and{" "}
              {number(system?.telemetry.dropped_errors)} error events dropped
              since restart.
            </p>
          )}

          <section className="admin-section" aria-labelledby="system-heading">
            <div className="admin-section-heading">
              <h2 id="system-heading">
                <Cpu size={18} /> VPS health
              </h2>
              <span>Last 5 minutes</span>
            </div>
            <div className="admin-health-grid">
              <Metric
                label="CPU"
                value={percent(current?.cpu_percent)}
                detail={
                  current?.load
                    ? `Load ${current.load.map((value) => number(value)).join(" / ")}`
                    : "Load unavailable"
                }
              >
                <History samples={system?.history ?? []} kind="cpu" />
              </Metric>
              <Metric
                label="Memory"
                value={percent(current?.memory?.percent)}
                detail={
                  current?.memory
                    ? `${bytes(current.memory.used_bytes)} / ${bytes(current.memory.total_bytes)}`
                    : undefined
                }
              >
                <History samples={system?.history ?? []} kind="memory" />
              </Metric>
              <Metric
                label="Disk"
                value={percent(current?.disk?.percent)}
                detail={
                  current?.disk
                    ? `${bytes(current.disk.used_bytes)} / ${bytes(current.disk.total_bytes)}`
                    : undefined
                }
              >
                <div className="admin-disk">
                  <HardDrive size={22} />
                  <meter
                    aria-label="Disk usage"
                    min="0"
                    max="100"
                    value={current?.disk?.percent ?? 0}
                  />
                </div>
              </Metric>
            </div>
            <div className="admin-service-row">
              {(["redis", "postgres"] as const).map((name) => (
                <span key={name}>
                  <i className={system?.[name].ok ? "ok" : "unknown"} />
                  {name === "redis" ? "Redis" : "Postgres"}{" "}
                  <b>
                    {system?.[name].ok
                      ? `${number(system[name].latency_ms)} ms`
                      : "Unavailable"}
                  </b>
                </span>
              ))}
              <span>
                In flight{" "}
                <b>
                  {system
                    ? `${system.queue.inflight} / ${system.queue.max_inflight}`
                    : "Unavailable"}
                </b>
              </span>
              <span>
                Queued{" "}
                <b>
                  {system
                    ? number(
                        Object.values(system.queue.pending).reduce(
                          (sum, value) => sum + value,
                          0,
                        ),
                      )
                    : "Unavailable"}
                </b>
              </span>
              <span className="admin-release">
                Release{" "}
                <code>{system?.release.slice(0, 12) ?? "Unavailable"}</code>
              </span>
            </div>
          </section>

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

          <section className="admin-section" aria-labelledby="ips-heading">
            <div className="admin-section-heading">
              <h2 id="ips-heading">IP activity</h2>
              <span>{window} window</span>
            </div>
            <div className="admin-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>IP address</th>
                    <th>Requests</th>
                    <th>Errors</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {ips?.items.map((row) => (
                    <tr key={row.ip}>
                      <td>
                        <code>{row.ip}</code>
                      </td>
                      <td>{number(row.requests)}</td>
                      <td>{number(row.errors)}</td>
                      <td>{date(row.last_seen)}</td>
                    </tr>
                  ))}
                  {!ips?.items.length && (
                    <tr>
                      <td colSpan={4} className="admin-empty">
                        {ips
                          ? "No requests in this window"
                          : loading
                            ? "Loading IP activity..."
                            : "IP activity unavailable"}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <Pagination
              label="IP"
              data={ips}
              page={ipPage}
              onPage={(page) => {
                setIpPage(page);
                setIps(undefined);
              }}
              disabled={loading || !ips}
            />
          </section>

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
                    onChange={(event) => {
                      setStatus(event.target.value);
                      setErrorPage(1);
                      setErrors(undefined);
                    }}
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
                    onChange={(event) => {
                      setErrorCode(event.target.value);
                      setErrorPage(1);
                      setErrors(undefined);
                    }}
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
                              setExpandedError(
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
              onPage={(page) => {
                setErrorPage(page);
                setErrors(undefined);
              }}
              disabled={loading || !errors}
            />
          </section>
        </div>
      )}
    </main>
  );
}
