#!/usr/bin/env node
// Fast post-deploy check that the Worker serves every kind of route.
// Usage: node scripts/smoke-web.mjs [base-url]   (defaults to WEB_URL or a local preview)
const BASE = (process.argv[2] ?? process.env.WEB_URL ?? "http://localhost:8787").replace(/\/+$/, "");

const checks = [
  { path: "/", status: 200, type: "text/html", includes: "<h1" },
  { path: "/use-cases", status: 200, type: "text/html", includes: "<h1" },
  { path: "/use-cases?q=invoice&page=1", status: 200, type: "text/html" },
  { path: "/use-cases/this-use-case-does-not-exist", status: 404 },
  { path: "/use-cases/page/2", status: 308, location: "/use-cases?page=2" },
  { path: "/sitemap.xml", status: 200, type: "xml", includes: "<sitemapindex" },
  { path: "/sitemaps/0.xml", status: 200, type: "xml", includes: "<urlset" },
  { path: "/sitemaps/not-a-chunk", status: 404 },
  { path: "/robots.txt", status: 200, type: "text/plain", includes: "Sitemap:" },
  { path: "/opengraph-image", status: 200, type: "image/png" },
  { path: "/favicon.ico", status: 200 },
  { path: "/admin", status: 200, header: ["x-robots-tag", "noindex"] },
];

async function run(check) {
  const started = Date.now();
  const response = await fetch(`${BASE}${check.path}`, { redirect: "manual", signal: AbortSignal.timeout(20_000) });
  const problems = [];
  if (response.status !== check.status) problems.push(`status ${response.status}, expected ${check.status}`);
  if (check.type && !(response.headers.get("content-type") ?? "").includes(check.type)) problems.push(`content-type ${response.headers.get("content-type")}`);
  if (check.location && !(response.headers.get("location") ?? "").endsWith(check.location)) problems.push(`location ${response.headers.get("location")}`);
  if (check.header && !(response.headers.get(check.header[0]) ?? "").includes(check.header[1])) problems.push(`${check.header[0]} lacks ${check.header[1]}`);
  if (check.includes && !(await response.text()).includes(check.includes)) problems.push(`body lacks ${check.includes}`);
  return { ...check, problems, ms: Date.now() - started };
}

async function main() {
  // Next.js assets referenced by the homepage must come from the static assets binding.
  const home = await (await fetch(`${BASE}/`, { signal: AbortSignal.timeout(20_000) })).text();
  const asset = /\/_next\/static\/[^"']+\.js/.exec(home)?.[0];
  const all = asset ? [...checks, { path: asset, status: 200, type: "javascript" }] : checks;

  const results = await Promise.all(all.map((check) => run(check).catch((error) => ({ ...check, problems: [String(error)], ms: 0 }))));
  if (!asset) results.push({ path: "/_next/static/*", problems: ["homepage references no Next.js script"], ms: 0 });
  for (const result of results) console.log(`${result.problems.length ? "FAIL" : "ok  "} ${String(result.ms).padStart(5)}ms ${result.path}${result.problems.length ? ` — ${result.problems.join("; ")}` : ""}`);
  const failed = results.filter((result) => result.problems.length);
  if (failed.length) {
    console.error(`Smoke test failed for ${BASE}: ${failed.length} of ${results.length} checks.`);
    process.exitCode = 1;
  } else {
    console.log(`Smoke test passed for ${BASE}: ${results.length} checks.`);
  }
}

main().catch((error) => {
  console.error(`Smoke test failed: ${error instanceof Error ? error.stack ?? error.message : String(error)}`);
  process.exitCode = 1;
});
