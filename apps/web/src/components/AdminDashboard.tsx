"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  KeyRound,
  LogOut,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { adminFetch, AdminError } from "@/lib/admin";
import { date, number } from "./admin/AdminPrimitives";
import { SystemHealth } from "./admin/SystemHealth";
import { ApiActivity } from "./admin/ApiActivity";
import { PageViews } from "./admin/PageViews";
import { IpActivitySection } from "./admin/IpActivitySection";
import { ErrorHistory } from "./admin/ErrorHistory";
import GeneratedPages from "./GeneratedPages";
import type {
  ActivityWindow,
  ErrorEvent,
  IpActivity,
  Page,
  PageViewRow,
  SeoSummary,
  SeoPage,
  SeoRun,
  Summary,
  SystemStatus,
} from "@/lib/admin";

const dayInput = (offsetDays = 0) => {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + offsetDays);
  return value.toISOString().slice(0, 10);
};
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Connection unavailable";


export default function AdminDashboard() {
  const [auth, setAuth] = useState<"checking" | "login" | "ready">("checking");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [clock, setClock] = useState(Date.now());
  const [window, setWindow] = useState<ActivityWindow>("24h");
  const [ipPage, setIpPage] = useState(1);
  const [viewPage, setViewPage] = useState(1);
  const [viewsFrom, setViewsFrom] = useState(() => dayInput(-6));
  const [viewsTo, setViewsTo] = useState(() => dayInput());
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
  const [pageViews, setPageViews] = useState<Page<PageViewRow>>();
  const [errors, setErrors] = useState<Page<ErrorEvent>>();
  const [seoSummary, setSeoSummary] = useState<SeoSummary>();
  const [seoPages, setSeoPages] = useState<Page<SeoPage>>();
  const [seoRuns, setSeoRuns] = useState<Page<SeoRun>>();
  const [seoPage, setSeoPage] = useState(1);
  const [seoRunPage, setSeoRunPage] = useState(1);
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
        adminFetch<Page<PageViewRow>>(
          `/page-views?from=${viewsFrom}&to=${viewsTo}&page=${viewPage}&page_size=25`,
          opts,
        ),
        adminFetch<Page<ErrorEvent>>(`/errors?${query}`, opts),
        adminFetch<SeoSummary>("/seo/summary", opts),
        adminFetch<Page<SeoPage>>(`/seo/pages?page=${seoPage}&page_size=25`, opts),
        adminFetch<Page<SeoRun>>(`/seo/runs?page=${seoRunPage}&page_size=25`, opts),
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
        setPageViews(undefined);
        setErrors(undefined);
        setSeoSummary(undefined);
        setSeoPages(undefined);
        setSeoRuns(undefined);
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
          results[4].status === "fulfilled" ? results[4].value : undefined,
        );
        setPageViews(
          results[3].status === "fulfilled" ? results[3].value : undefined,
        );
        setSeoSummary(results[5].status === "fulfilled" ? results[5].value : undefined);
        setSeoPages(results[6].status === "fulfilled" ? results[6].value : undefined);
        setSeoRuns(results[7].status === "fulfilled" ? results[7].value : undefined);
        const labels = [
          "System",
          "Activity",
          "IP activity",
          "Page views",
          "Errors",
          "Generated pages",
          "Generated page list",
          "Generation history",
        ];
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
  }, [
    auth,
    window,
    ipPage,
    viewPage,
    viewsFrom,
    viewsTo,
    errorPage,
    seoPage,
    seoRunPage,
    status,
    errorCode,
    refresh,
  ]);

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
      setPageViews(undefined);
      setErrors(undefined);
      setSeoSummary(undefined);
      setSeoPages(undefined);
      setSeoRuns(undefined);
      setAuth("login");
    } catch (error) {
      setFailures([`Sign out: ${message(error)}`]);
    } finally {
      setBusy(false);
    }
  }

  const cooldown = Math.max(0, Math.ceil((retryAt - clock) / 1000));
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

          <SystemHealth system={system} />

          <ApiActivity summary={summary} window={window} />

          <GeneratedPages
            summary={seoSummary} pages={seoPages} runs={seoRuns}
            page={seoPage} runPage={seoRunPage} loading={loading}
            onPage={(page) => { setSeoPage(page); setSeoPages(undefined); }}
            onRunPage={(page) => { setSeoRunPage(page); setSeoRuns(undefined); }}
          />

          <PageViews pageViews={pageViews} viewsFrom={viewsFrom} viewsTo={viewsTo} viewPage={viewPage} loading={loading}
            onFrom={(value) => { setViewsFrom(value); setViewPage(1); setPageViews(undefined); }}
            onTo={(value) => { setViewsTo(value); setViewPage(1); setPageViews(undefined); }}
            onPage={(page) => { setViewPage(page); setPageViews(undefined); }} />

          <IpActivitySection ips={ips} window={window} ipPage={ipPage} loading={loading}
            onPage={(page) => { setIpPage(page); setIps(undefined); }} />

          <ErrorHistory errors={errors} status={status} errorCode={errorCode} expandedError={expandedError} errorPage={errorPage} loading={loading}
            onStatus={(value) => { setStatus(value); setErrorPage(1); setErrors(undefined); }}
            onErrorCode={(value) => { setErrorCode(value); setErrorPage(1); setErrors(undefined); }}
            onExpandedError={setExpandedError}
            onPage={(page) => { setErrorPage(page); setErrors(undefined); }} />
        </div>
      )}
    </main>
  );
}
