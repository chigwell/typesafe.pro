"use client";

import { useEffect } from "react";

export const DEMO_FRAME_ID = "use-case-demo-frame";
/** Beyond MAX_HEIGHT the frame scrolls internally rather than pushing the article away. */
export const MIN_HEIGHT = 120;
export const MAX_HEIGHT = 4000;

/**
 * Connects the host page with the sandboxed demo iframe: forwards the site theme and
 * follows the frame's reported content height. The frame has an opaque origin, so
 * messages are matched by source window rather than origin.
 */
export function DemoFrameBridge({ frameId = DEMO_FRAME_ID }: { frameId?: string }) {
  useEffect(() => {
    const frame = document.getElementById(frameId);
    if (!(frame instanceof HTMLIFrameElement)) return;
    const sendTheme = () => {
      const value = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
      frame.contentWindow?.postMessage({ type: "typesafe-demo:theme", value }, "*");
    };
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frame.contentWindow) return;
      const data: unknown = event.data;
      if (!data || typeof data !== "object") return;
      const message = data as { type?: unknown; height?: unknown };
      if (message.type === "typesafe-demo:height" && typeof message.height === "number" && Number.isFinite(message.height)) {
        frame.style.height = `${Math.min(Math.max(Math.ceil(message.height), MIN_HEIGHT), MAX_HEIGHT)}px`;
      } else if (message.type === "typesafe-demo:ready") {
        sendTheme();
      }
    };
    const sync = () => {
      sendTheme();
      frame.contentWindow?.postMessage({ type: "typesafe-demo:measure" }, "*");
    };
    window.addEventListener("message", onMessage);
    frame.addEventListener("load", sync);
    const observer = typeof MutationObserver === "function" ? new MutationObserver(sendTheme) : null;
    observer?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    sync();
    return () => {
      window.removeEventListener("message", onMessage);
      frame.removeEventListener("load", sync);
      observer?.disconnect();
    };
  }, [frameId]);
  return null;
}
