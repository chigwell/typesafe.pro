"use client";

import { useEffect } from "react";
import { DEFAULT_API_BASE } from "@/lib/typesafe";

const API_BASE = (
  process.env.NEXT_PUBLIC_TYPESAFE_API_BASE || DEFAULT_API_BASE
).replace(/\/$/, "");

export function PublicPageViewTracker({ path }: { path: string }) {
  useEffect(() => {
    const body = JSON.stringify({ path });
    const url = `${API_BASE}/analytics/view`;
    if (navigator.sendBeacon) {
      const sent = navigator.sendBeacon(
        url,
        new Blob([body], { type: "application/json" }),
      );
      if (sent) return;
    }
    void fetch(url, {
      method: "POST",
      body,
      headers: { "Content-Type": "application/json" },
      keepalive: true,
      cache: "no-store",
    }).catch(() => {});
  }, [path]);

  return null;
}
