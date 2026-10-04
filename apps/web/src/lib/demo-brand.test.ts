import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { readStylesheet } from "@/test/styles";
import { DEMO_BRAND, DEMO_BRAND_CSS } from "./demo-brand";
import { buildDemoDocument } from "./demo-document";
import { useCaseDemoFixture } from "@/test/use-case-fixture";

const globals = readStylesheet(resolve(__dirname, "../app/globals.css"));

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
    // Demos made before the kit style their own buttons by class and rely on this base look.
    expect(DEMO_BRAND_CSS).toMatch(/(^|\n)#demo button\{[^}]*background:var\(--ts-button\)/);
    expect(DEMO_BRAND_CSS).not.toContain("button:not([class])");
  });
});
