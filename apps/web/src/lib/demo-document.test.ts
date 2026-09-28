import { Script } from "node:vm";
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildDemoDocument, demoCsp } from "./demo-document";
import { DEMO_RUNTIME } from "./demo-runtime";
import { useCaseDemoFixture } from "@/test/use-case-fixture";

describe("sandboxed demo document", () => {
  it("is a complete document with a restrictive CSP, the runtime and the demo code", () => {
    const demo = useCaseDemoFixture();
    const document = buildDemoDocument(demo, "https://api.typesafe.pro");
    expect(document.startsWith("<!doctype html>")).toBe(true);
    expect(document).toContain(`<meta http-equiv="Content-Security-Policy" content="${demoCsp("https://api.typesafe.pro")}">`);
    expect(demoCsp("https://api.typesafe.pro")).toContain("default-src 'none'");
    expect(demoCsp("http://localhost:8010")).toContain("connect-src http://localhost:8010");
    expect(document.indexOf("Content-Security-Policy")).toBeLessThan(document.indexOf("<script>"));
    expect(document).toContain(demo.html);
    expect(document).toContain(demo.css);
    expect(document).toContain("window.TypeSafeDemo");
    expect(document).toContain(demo.js);
    expect(document).toContain('"apiBase":"https://api.typesafe.pro"');
    expect(document).toContain('"answers":{"mood":{"type":"noul","noul":0.93}}');
  });
  it("never lets generated text terminate an inline element", () => {
    const demo = useCaseDemoFixture();
    demo.js = 'const html = "<\\/b>"; const tag = "</b>"; const text = "x";';
    demo.css = "p::after{content:'</b>'}";
    demo.samples[0].description = "</script><script>alert(1)</script>";
    demo.title = "<b>Bold</b> & co";
    const document = buildDemoDocument(demo, "https://api.typesafe.pro");
    const scripts = document.match(/<script>/g)?.length;
    const closers = document.match(/<\/script>/g)?.length;
    expect(scripts).toBe(3);
    expect(closers).toBe(3);
    expect(document).not.toContain("</script><script>alert");
    expect(document).toContain("<title>&lt;b&gt;Bold&lt;/b&gt; &amp; co</title>");
    expect(document).toContain("\\u003c/script");
  });
  it("ships a runtime that parses as plain JavaScript", () => {
    expect(() => new Script(DEMO_RUNTIME)).not.toThrow();
    expect(DEMO_RUNTIME).toContain("/v1/systemone");
    expect(DEMO_RUNTIME).toContain('credentials: "omit"');
    expect(DEMO_RUNTIME).toContain("typesafe-demo:height");
  });

  describe("runtime error messages", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
      delete (window as { TypeSafeDemo?: unknown }).TypeSafeDemo;
    });
    const runtime = () => {
      new Function(DEMO_RUNTIME)();
      return (window as unknown as { TypeSafeDemo: { evaluate(state: unknown): Promise<unknown>; describeError(error: unknown): string } }).TypeSafeDemo;
    };

    it("reports a rejected fetch as unreachable", async () => {
      vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));
      const demo = runtime();
      const error = await demo.evaluate({ text: "hi" }).catch((failure) => failure);
      expect(demo.describeError(error)).toBe("The API could not be reached. Check your connection and try again.");
    });

    it("does not blame the network for a bug in the demo's own code", () => {
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
      const demo = runtime();
      let bug: unknown;
      try {
        Math.max(...({ 0: 0.2, 1: 0.8 } as unknown as number[]));
      } catch (error) {
        bug = error;
      }
      expect(demo.describeError(bug)).toBe("The demo could not display this result.");
      expect(consoleError).toHaveBeenCalledWith(bug);
      expect(demo.describeError(new Error("The free rate limit was reached. Try again in a minute."))).toContain("rate limit");
      consoleError.mockRestore();
    });
  });
});
