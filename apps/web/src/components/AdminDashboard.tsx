"use client";

import { useState } from "react";
import {
  KeyRound,
  LogOut,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { date, number } from "./admin/AdminPrimitives";
import { SystemHealth } from "./admin/SystemHealth";
import { ApiActivity } from "./admin/ApiActivity";
import { PageViews } from "./admin/PageViews";
import { IpActivitySection } from "./admin/IpActivitySection";
import { ErrorHistory } from "./admin/ErrorHistory";
import GeneratedPages from "./GeneratedPages";
import type { ActivityWindow } from "@/lib/admin";
import { dayInput } from "./admin/admin-lifecycle";
import { useAdminAuth } from "./admin/useAdminAuth";
import { useAdminPolling } from "./admin/useAdminPolling";

export default function AdminDashboard() {
  const session = useAdminAuth({
    onLogout: () => data.clearPrivateData(),
    onLogoutFailure: (failure) => data.setFailures([failure]),
  });
  const { auth, password, setPassword, authError, busy, cooldown, login, logout } = session;
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
  const [seoPage, setSeoPage] = useState(1);
  const [seoRunPage, setSeoRunPage] = useState(1);
  const data = useAdminPolling({
    auth, window, ipPage, viewPage, viewsFrom, viewsTo, errorPage,
    seoPage, seoRunPage, status, errorCode, refresh, onUnauthorized: session.expireSession,
  });
  const { system, summary, ips, pageViews, errors, seoSummary, seoPages, seoRuns } = data.snapshot;
  const { loading, updated, failures, clearFields } = data;
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
                      clearFields("summary");
                      clearFields("ips");
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
            onPage={(page) => { setSeoPage(page); clearFields("seoPages"); }}
            onRunPage={(page) => { setSeoRunPage(page); clearFields("seoRuns"); }}
          />

          <PageViews pageViews={pageViews} viewsFrom={viewsFrom} viewsTo={viewsTo} viewPage={viewPage} loading={loading}
            onFrom={(value) => { setViewsFrom(value); setViewPage(1); clearFields("pageViews"); }}
            onTo={(value) => { setViewsTo(value); setViewPage(1); clearFields("pageViews"); }}
            onPage={(page) => { setViewPage(page); clearFields("pageViews"); }} />

          <IpActivitySection ips={ips} window={window} ipPage={ipPage} loading={loading}
            onPage={(page) => { setIpPage(page); clearFields("ips"); }} />

          <ErrorHistory errors={errors} status={status} errorCode={errorCode} expandedError={expandedError} errorPage={errorPage} loading={loading}
            onStatus={(value) => { setStatus(value); setErrorPage(1); clearFields("errors"); }}
            onErrorCode={(value) => { setErrorCode(value); setErrorPage(1); clearFields("errors"); }}
            onExpandedError={setExpandedError}
            onPage={(page) => { setErrorPage(page); clearFields("errors"); }} />
        </div>
      )}
    </main>
  );
}
