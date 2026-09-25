"use client";

import { useEffect } from "react";
import { DEFAULT_API_BASE } from "@/lib/typesafe";

const API_BASE = (
  process.env.NEXT_PUBLIC_TYPESAFE_API_BASE || DEFAULT_API_BASE
).replace(/\/$/, "");

export function PublicPageViewTracker({ path }: { path: string }) {
  useEffect(() => {
    const body = JSON.stringify({ path });
    void fetch(`${API_BASE}/analytics/view`, {
      method: "POST",
      body,
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      credentials: "omit",
      keepalive: true,
      cache: "no-store",
    }).catch(() => {});
  }, [path]);

  return null;
}
