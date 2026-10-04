import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { adminFetch, AdminError } from "@/lib/admin";
import { message } from "./admin-lifecycle";

export type AdminAuthState = "checking" | "login" | "ready";

export function useAdminAuth({ onLogout, onLogoutFailure }: {
  onLogout: () => void;
  onLogoutFailure: (message: string) => void;
}) {
  const [auth, setAuth] = useState<AdminAuthState>("checking");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [clock, setClock] = useState(Date.now());
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
      onLogout();
      setAuth("login");
    } catch (error) {
      onLogoutFailure(`Sign out: ${message(error)}`);
    } finally {
      setBusy(false);
    }
  }

  const expireSession = useCallback(() => {
    setAuthError("Session expired. Sign in again.");
    setAuth("login");
  }, []);
  const cooldown = Math.max(0, Math.ceil((retryAt - clock) / 1000));
  return { auth, password, setPassword, authError, busy, cooldown, login, logout, expireSession };
}
