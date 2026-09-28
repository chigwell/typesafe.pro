#!/usr/bin/env node
// Validates the rendered site over HTTP: a local `npm run preview` or a deployed Worker.
// Usage: node scripts/validate-seo-output.mjs [base-url] [--all]
// Use-case pages come from the content API; without --all a sample of them is checked.
const args = process.argv.slice(2);
const BASE = (args.find((arg) => !arg.startsWith("--")) ?? process.env.WEB_URL ?? "http://localhost:8787").replace(/\/+$/, "");
const API = (process.env.TYPESAFE_API_BASE ?? "https://api.typesafe.pro").replace(/\/+$/, "");
const SAMPLE = args.includes("--all") ? Infinity : 25;
const SITE_URL = "https://typesafe.pro";
const GOOGLE_ADS_ID = "AW-18465939418";
const errors = [];

function assert(condition, message) {
  if (!condition) errors.push(message);
}

function parseAttrs(source) {
  return Object.fromEntries([...source.matchAll(/([:\w-]+)="([^"]*)"/g)].map((match) => [match[1], match[2]]));
}

function metaTags(source) {
  return [...source.matchAll(/<meta\s+([^>]+)>/g)].map((match) => parseAttrs(match[1]));
}

function linkTags(source) {
  return [...source.matchAll(/<link\s+([^>]+)>/g)].map((match) => parseAttrs(match[1]));
}

function findMeta(source, key, value) {
  return metaTags(source).find((tag) => tag[key] === value);
}

function htmlDecode(value) {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

async function get(url, { redirect = "follow" } = {}) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      const response = await fetch(url, { redirect, headers: { "User-Agent": "typesafe-seo-validator" }, signal: AbortSignal.timeout(20_000) });
      if (response.status >= 500 && attempt < 3) throw new Error(`HTTP ${response.status}`);
      return response;
    } catch (error) {
      if (attempt >= 3) throw new Error(`${url}: ${error instanceof Error ? error.message : error}`);
      await new Promise((done) => setTimeout(done, attempt * 2000));
    }
  }
}

async function text(path) {
  const response = await get(`${BASE}${path}`);
  assert(response.ok, `${path}: HTTP ${response.status}`);
  return { body: await response.text(), response };
}

async function apiJson(path) {
  const response = await get(`${API}${path}`);
  if (!response.ok) throw new Error(`Content API ${path}: HTTP ${response.status}`);
  return response.json();
}

/** Site URLs are absolute on typesafe.pro; fetch the same path from the site under test. */
const local = (url) => new URL(htmlDecode(url), SITE_URL).pathname;

function assertJsonLd(source) {
  const scripts = [...source.matchAll(/<script\s+type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)];
  assert(scripts.length > 0, "Homepage lacks JSON-LD");

  const nodes = [];
  for (const [, raw] of scripts) {
    try {
      const parsed = JSON.parse(raw);
      nodes.push(...(Array.isArray(parsed["@graph"]) ? parsed["@graph"] : [parsed]));
    } catch {
      errors.push("Homepage has invalid JSON-LD");
    }
  }

  const types = new Set();
  for (const node of nodes) {
    const type = node?.["@type"];
    if (Array.isArray(type)) type.forEach((item) => types.add(item));
    else if (type) types.add(type);
  }

  assert(types.has("WebSite"), "JSON-LD lacks WebSite");
  assert(types.has("SoftwareApplication") || types.has("WebApplication"), "JSON-LD lacks application schema");
}

function assertGoogleTag(source) {
  const encodedId = GOOGLE_ADS_ID.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  assert(
    new RegExp(`<script\\s+[^>]*src="https://www\\.googletagmanager\\.com/gtag/js\\?id=${encodedId}"`).test(source),
    `Homepage lacks Google tag script for ${GOOGLE_ADS_ID}`,
  );
  assert(
    source.includes(`gtag('config', '${GOOGLE_ADS_ID}')`),
    `Homepage lacks Google tag config for ${GOOGLE_ADS_ID}`,
  );
}

async function main() {
  const { body: index } = await text("/");

  assert(/<title>TypeSafe Jev Playground and API Gateway \| typesafe\.pro<\/title>/.test(index), "Homepage title is missing or unexpected");
  const description = findMeta(index, "name", "description")?.content;
  assert(Boolean(description), "Homepage lacks meta description");
  assert(description && description.length >= 120 && description.length <= 170, "Homepage description should be concise and search-friendly");

  const canonical = linkTags(index).find((tag) => tag.rel === "canonical")?.href;
  assert(canonical === SITE_URL || canonical === `${SITE_URL}/`, `Homepage canonical should be ${SITE_URL}`);

  const robots = findMeta(index, "name", "robots")?.content;
  assert(robots?.includes("index") && robots?.includes("follow"), "Homepage robots meta should allow indexing and following");

  const googleBot = findMeta(index, "name", "googlebot")?.content;
  assert(googleBot?.includes("max-image-preview:large"), "Homepage googlebot meta should allow large image previews");

  const ogImage = findMeta(index, "property", "og:image")?.content;
  const twitterImage = findMeta(index, "name", "twitter:image")?.content;
  assert(Boolean(ogImage), "Homepage lacks og:image");
  assert(Boolean(twitterImage), "Homepage lacks twitter:image");

  if (ogImage) {
    const response = await get(`${BASE}${local(ogImage)}`);
    const bytes = response.ok ? (await response.arrayBuffer()).byteLength : 0;
    assert(response.ok, `og:image does not resolve: ${ogImage} (HTTP ${response.status})`);
    assert(/^image\/png/.test(response.headers.get("content-type") ?? ""), "og:image should be served as image/png");
    assert(bytes > 1_000, "og:image is unexpectedly small");
  }

  assertJsonLd(index);
  assertGoogleTag(index);

  // The API is the source of truth for what is published.
  const first = await apiJson("/v1/use-cases-sitemap?chunk=0");
  const published = [...first.items];
  for (let chunk = 1; chunk < first.chunks; chunk += 1) published.push(...(await apiJson(`/v1/use-cases-sitemap?chunk=${chunk}`)).items);
  assert(published.length === first.total, "Content API sitemap chunks do not add up to its total");

  const { body: sitemapIndex, response: sitemapResponse } = await text("/sitemap.xml");
  assert(/xml/.test(sitemapResponse.headers.get("content-type") ?? ""), "sitemap.xml should be served as XML");
  assert(sitemapIndex.includes("<sitemapindex"), "Sitemap must be a chunked sitemap index");
  const chunks = [...sitemapIndex.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
  assert(chunks.length === first.chunks, `Sitemap index lists ${chunks.length} chunks, the API has ${first.chunks}`);
  const sitemapUrls = [];
  for (const chunk of chunks) {
    assert(new RegExp(`^${SITE_URL.replaceAll(".", "\\.")}/sitemaps/\\d+\\.xml$`).test(chunk), `Unexpected sitemap chunk URL: ${chunk}`);
    if (!chunk.startsWith(`${SITE_URL}/sitemaps/`)) continue;
    const { body: xml } = await text(local(chunk));
    const urls = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
    assert(urls.length <= 10_002, "Sitemap chunk exceeds 10,000 use-case URLs");
    assert(/<lastmod>[^<]+<\/lastmod>/.test(xml), "Sitemap lacks lastmod");
    sitemapUrls.push(...urls);
  }
  const expectedUrls = new Set([`${SITE_URL}/`, `${SITE_URL}/use-cases`, ...published.map((entry) => `${SITE_URL}/use-cases/${entry.slug}`)]);
  assert(new Set(sitemapUrls).size === sitemapUrls.length, "Sitemap contains duplicate URLs");
  assert(sitemapUrls.length === expectedUrls.size && sitemapUrls.every((url) => expectedUrls.has(url)), "Sitemap differs from the published use cases");

  const { body: catalog } = await text("/use-cases");
  assert(catalog.includes("<h1"), "/use-cases: missing rendered heading");
  assert(linkTags(catalog).some((tag) => tag.rel === "canonical" && tag.href === `${SITE_URL}/use-cases`), "/use-cases: missing canonical");

  const legacy = await get(`${BASE}/use-cases/page/2`, { redirect: "manual" });
  assert([301, 308].includes(legacy.status) && legacy.headers.get("location")?.endsWith("/use-cases?page=2"), "/use-cases/page/2 should permanently redirect to /use-cases?page=2");

  const sample = SAMPLE >= published.length ? published : [...published].sort(() => Math.random() - 0.5).slice(0, SAMPLE);
  for (const entry of sample) {
    const url = `${SITE_URL}/use-cases/${entry.slug}`;
    const detail = await apiJson(`/v1/use-cases/${entry.slug}`);
    const { body: html } = await text(`/use-cases/${entry.slug}`);
    assert(linkTags(html).some((tag) => tag.rel === "canonical" && tag.href === url), `${entry.slug}: missing canonical`);
    assert(htmlDecode(/<title>([^<]+)<\/title>/.exec(html)?.[1] ?? "").startsWith(detail.page.seo.title), `${entry.slug}: title differs from the content API`);
    assert(Boolean(findMeta(html, "name", "description")?.content), `${entry.slug}: missing description`);
    assert(findMeta(html, "property", "og:url")?.content === url, `${entry.slug}: missing Open Graph URL`);
    const structured = [...html.matchAll(/<script\s+type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)].flatMap((match) => {
      try { const value = JSON.parse(match[1]); return value["@graph"] ?? [value]; }
      catch { errors.push(`${entry.slug}: invalid JSON-LD`); return []; }
    });
    assert(structured.some((node) => node["@type"] === "TechArticle" && node.dateModified === detail.page.updated_at), `${entry.slug}: missing TechArticle or wrong date`);
    assert(structured.some((node) => node["@type"] === "BreadcrumbList"), `${entry.slug}: missing breadcrumbs`);
    const body = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "");
    assert(body.includes("The problem") && body.includes("Previous verification response"), `${entry.slug}: article and responses must render without JavaScript`);
    assert(body.includes('class="code-line"') && body.includes("urllib") && body.includes('id="use-case-request"'), `${entry.slug}: request and complete Python example must render without JavaScript`);
    assert(!findMeta(html, "name", "robots")?.content?.includes("noindex"), `${entry.slug}: published page disallows indexing`);
    assert(!html.includes("use-case-draft-banner"), `${entry.slug}: a published page renders as a draft preview`);
    if (html.includes('id="use-case-demo"')) {
      const frame = /<iframe\s+([^>]*)>/.exec(html);
      // HTML attribute names are case-insensitive; React serializes srcDoc in camelCase.
      const attrs = Object.fromEntries(Object.entries(frame ? parseAttrs(frame[1]) : {}).map(([key, value]) => [key.toLowerCase(), value]));
      assert(attrs.sandbox === "allow-scripts", `${entry.slug}: demo iframe must be sandboxed with exactly allow-scripts`);
      const srcdoc = htmlDecode(attrs.srcdoc ?? "");
      assert(srcdoc.includes('http-equiv="Content-Security-Policy"') && srcdoc.includes("default-src 'none'"), `${entry.slug}: demo document lacks its Content-Security-Policy`);
      assert(srcdoc.includes("window.TypeSafeDemo"), `${entry.slug}: demo document lacks the host runtime`);
      assert(body.includes("Verified sample results"), `${entry.slug}: demo sample results must render without JavaScript`);
    }
  }

  const missing = await get(`${BASE}/use-cases/this-use-case-does-not-exist`);
  assert(missing.status === 404, `Unknown use case should return 404, got ${missing.status}`);

  const { body: robotsTxt } = await text("/robots.txt");
  assert(/User-Agent: \*/i.test(robotsTxt), "robots.txt lacks wildcard user-agent");
  assert(/Allow: \//i.test(robotsTxt), "robots.txt should allow crawling");
  assert(robotsTxt.includes(`Sitemap: ${SITE_URL}/sitemap.xml`), "robots.txt lacks sitemap reference");

  const admin = await get(`${BASE}/admin`);
  assert(/noindex/.test(admin.headers.get("x-robots-tag") ?? ""), "/admin should send X-Robots-Tag: noindex");

  if (errors.length) {
    console.error(`SEO validation failed for ${BASE} (${errors.length} errors):\n${errors.map((error) => `- ${error}`).join("\n")}`);
    process.exitCode = 1;
    return;
  }

  console.log(`SEO validation passed for ${BASE}: homepage, ${sample.length}/${published.length} use-case pages, sitemap chunks, robots, admin headers and OG image.`);
}

main().catch((error) => {
  console.error(`SEO validation failed: ${error instanceof Error ? error.stack ?? error.message : String(error)}`);
  process.exitCode = 1;
});
