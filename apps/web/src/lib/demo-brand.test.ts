import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DEMO_BRAND, DEMO_BRAND_CSS } from "./demo-brand";
import { buildDemoDocument } from "./demo-document";
import { validateUseCase } from "./use-cases";
import { useCaseDemoFixture, useCaseFixture } from "@/test/use-case-fixture";

const globals = readFileSync(resolve(__dirname, "../app/globals.css"), "utf8");

function block(selector: string) {
  const start = globals.indexOf(`${selector} {`);
  expect(start, `${selector} block in globals.css`).toBeGreaterThanOrEqual(0);
  const body = globals.slice(start, globals.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()]));
}

describe("demo brand kit", () => {
  it.each([["light", ":root"], ["dark", ':root[data-theme="dark"]']] as const)("mirrors the site %s tokens", (theme, selector) => {
    const site = block(selector);
    const tokens = DEMO_BRAND.tokens[theme] as Record<string, string>;
    for (const [demoToken, siteToken] of Object.entries(DEMO_BRAND.site_tokens)) {
      expect(tokens[demoToken], `${demoToken} = ${siteToken}`).toBe(site[siteToken]);
    }
  });
  it("defines both themes with the same tokens and a categorical palette", () => {
    expect(Object.keys(DEMO_BRAND.tokens.dark).sort()).toEqual(Object.keys(DEMO_BRAND.tokens.light).sort());
    for (let index = 1; index <= 6; index += 1) expect(DEMO_BRAND.tokens.light).toHaveProperty(`--ts-c${index}`);
  });
  it("ships CSS for every documented class", () => {
    for (const name of Object.keys(DEMO_BRAND.classes)) {
      expect(DEMO_BRAND_CSS, name).toMatch(new RegExp(`\\.${name}[{:.,\\s]`));
    }
  });
  it("loads the kit before the demo's own styles and keeps legacy variables", () => {
    const document = buildDemoDocument(useCaseDemoFixture(), "https://api.typesafe.pro");
    const kit = document.indexOf(".ts-btn{");
    expect(kit).toBeGreaterThan(0);
    expect(kit).toBeLessThan(document.indexOf("#demo-visual{"));
    expect(DEMO_BRAND_CSS).toContain("--demo-accent:var(--ts-accent)");
    expect(DEMO_BRAND_CSS).toContain("height:auto!important");
  });
  it("rejects demos sized with viewport units", () => {
    const demo = useCaseDemoFixture();
    demo.css = "#demo-visual{min-height:60vh}";
    expect(() => validateUseCase({ ...useCaseFixture(), demo })).toThrow(/viewport units/);
    demo.css = "#demo-visual{height:40px}";
    demo.js = "el.style.height = 50 + 'dvh';";
    expect(() => validateUseCase({ ...useCaseFixture(), demo })).not.toThrow();
    demo.js = "el.style.height = '50dvh';";
    expect(() => validateUseCase({ ...useCaseFixture(), demo })).toThrow(/viewport units/);
  });
  it("accepts ordinary functions and the word location, but not navigation", () => {
    const demo = useCaseDemoFixture();
    demo.js = "button.addEventListener('click', function () { label.textContent = 'Enter a location'; dialog.open(); });";
    expect(() => validateUseCase({ ...useCaseFixture(), demo })).not.toThrow();
    for (const js of ["window.location = 'x'", "location.href = 'x'", "new Function('x')"]) {
      demo.js = js;
      expect(() => validateUseCase({ ...useCaseFixture(), demo }), js).toThrow(/forbidden API/);
    }
  });
});
