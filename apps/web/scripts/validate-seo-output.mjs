#!/usr/bin/env node
import { readdir, readFile, stat } from "node:fs/promises";
import { join, resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const OUT = resolve(ROOT, "out");
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

async function exists(path) {
  try {
    const info = await stat(path);
    return info.isFile() ? info : null;
  } catch {
    return null;
  }
}

async function walkFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walkFiles(path)));
    else files.push(path);
  }
  return files;
}

async function exportedFileForUrl(urlValue) {
  const url = new URL(htmlDecode(urlValue), SITE_URL);
  const pathname = decodeURIComponent(url.pathname).replace(/^\//, "");
  const candidates = [
    resolve(OUT, pathname),
    resolve(OUT, `${pathname}.png`),
    resolve(OUT, pathname, "index.html"),
    resolve(OUT, pathname, "index.png"),
  ];

  for (const candidate of candidates) {
    const info = await exists(candidate);
    if (info) return { path: candidate, info };
  }

  const base = pathname.split("/").pop();
  if (!base) return null;
  const files = await walkFiles(OUT);
  for (const file of files) {
    if (file.split("/").pop()?.startsWith(base)) {
      const info = await exists(file);
      if (info) return { path: file, info };
    }
  }

  return null;
}

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
  const index = await readFile(resolve(OUT, "index.html"), "utf8");

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
    const exported = await exportedFileForUrl(ogImage);
    assert(Boolean(exported), `og:image does not resolve to an exported file: ${ogImage}`);
    assert(!exported || exported.info.size > 1_000, "og:image export is unexpectedly small");
  }

  assertJsonLd(index);
  assertGoogleTag(index);

  const sitemapIndex = await readFile(resolve(OUT, "sitemap.xml"), "utf8");
  assert(sitemapIndex.includes("<sitemapindex"), "Sitemap must be a chunked sitemap index");
  const chunks = [...sitemapIndex.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
  const sitemapUrls = [];
  for (const chunk of chunks) {
    assert(new RegExp(`^${SITE_URL.replaceAll(".", "\\.")}/sitemaps/\\d+\\.xml$`).test(chunk), "Unexpected sitemap chunk URL");
    if (!chunk.startsWith(`${SITE_URL}/sitemaps/`)) continue;
    const xml = await readFile(resolve(OUT, new URL(chunk).pathname.slice(1)), "utf8");
    const urls = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
    assert(urls.length <= 10_000, "Sitemap chunk exceeds 10,000 URLs");
    assert(/<lastmod>[^<]+<\/lastmod>/.test(xml), "Sitemap lacks lastmod");
    sitemapUrls.push(...urls);
  }
  assert(sitemapUrls.includes(`${SITE_URL}/`), "Sitemap lacks homepage URL");
  assert(sitemapUrls.includes(`${SITE_URL}/use-cases`), "Sitemap lacks use-case catalog");
  assert(new Set(sitemapUrls).size === sitemapUrls.length, "Sitemap contains duplicate URLs");

  const release = JSON.parse(await readFile(resolve(OUT, "use-cases-manifest.json"), "utf8"));
  assert(release.schema_version === 1 && Array.isArray(release.pages), "Invalid public release manifest");
  const expectedUrls = new Set([`${SITE_URL}/`, `${SITE_URL}/use-cases`]);
  const catalogPages = Math.max(1, Math.ceil(release.pages.length / 24));
  for (let page = 2; page <= catalogPages; page += 1) expectedUrls.add(`${SITE_URL}/use-cases/page/${page}`);
  for (const entry of release.pages) {
    const url = `${SITE_URL}/use-cases/${entry.slug}`;
    expectedUrls.add(url);
    const html = await readFile(resolve(OUT, "use-cases", `${entry.slug}.html`), "utf8");
    assert(linkTags(html).some((tag) => tag.rel === "canonical" && tag.href === url), `${entry.slug}: missing canonical`);
    assert(htmlDecode(/<title>([^<]+)<\/title>/.exec(html)?.[1] ?? "") === entry.title, `${entry.slug}: title differs from manifest`);
    assert(Boolean(findMeta(html, "name", "description")?.content), `${entry.slug}: missing description`);
    assert(findMeta(html, "property", "og:url")?.content === url, `${entry.slug}: missing Open Graph URL`);
    const structured = [...html.matchAll(/<script\s+type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)].flatMap((match) => {
      try { const value = JSON.parse(match[1]); return value["@graph"] ?? [value]; }
      catch { errors.push(`${entry.slug}: invalid JSON-LD`); return []; }
    });
    assert(structured.some((node) => node["@type"] === "TechArticle" && node.dateModified === entry.updated_at), `${entry.slug}: missing TechArticle or wrong date`);
    assert(structured.some((node) => node["@type"] === "BreadcrumbList"), `${entry.slug}: missing breadcrumbs`);
    const body = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "");
    assert(body.includes("The problem") && body.includes("Previous verification response"), `${entry.slug}: article and responses must render without JavaScript`);
    assert(body.includes('class="code-line"') && body.includes("urllib") && body.includes('id="use-case-request"'), `${entry.slug}: request and complete Python example must render without JavaScript`);
    assert(!findMeta(html, "name", "robots")?.content?.includes("noindex"), `${entry.slug}: published page disallows indexing`);
  }
  assert(sitemapUrls.length === expectedUrls.size && sitemapUrls.every((url) => expectedUrls.has(url)), "Sitemap differs from published release");
  for (const url of expectedUrls) {
    if (url === `${SITE_URL}/`) continue;
    const html = await readFile(resolve(OUT, `${new URL(url).pathname.slice(1)}.html`), "utf8");
    assert(html.includes("<h1"), `${url}: missing rendered heading`);
  }
  const allFiles = await walkFiles(OUT);
  assert(!allFiles.some((file) => /\/(?:novelty-index|checkpoints?|pages-\d+)\.json$/.test(file)), "Private generation data leaked into static output");
  assert(!allFiles.some((file) => /\/use-cases\/(?:_empty|page\/0)\.(?:html|txt)$/.test(file)), "Empty export sentinels must not be public routes");

  const robotsTxt = await readFile(resolve(OUT, "robots.txt"), "utf8");
  assert(/User-Agent: \*/i.test(robotsTxt), "robots.txt lacks wildcard user-agent");
  assert(/Allow: \//i.test(robotsTxt), "robots.txt should allow crawling");
  assert(robotsTxt.includes(`Sitemap: ${SITE_URL}/sitemap.xml`), "robots.txt lacks sitemap reference");

  const headers = await readFile(resolve(OUT, "_headers"), "utf8");
  assert(headers.includes("/opengraph-image"), "_headers lacks opengraph-image rule");
  assert(/Content-Type:\s*image\/png/i.test(headers), "_headers should serve opengraph-image as image/png");

  if (errors.length) {
    console.error(`SEO validation failed (${errors.length} errors):\n${errors.map((error) => `- ${error}`).join("\n")}`);
    process.exitCode = 1;
    return;
  }

  console.log(`SEO validation passed: homepage, ${release.pages.length} use-case pages, release whitelist, sitemap chunks, robots, and OG image.`);
}

main().catch((error) => {
  console.error(`SEO validation failed: ${error instanceof Error ? error.stack ?? error.message : String(error)}`);
  process.exitCode = 1;
});
