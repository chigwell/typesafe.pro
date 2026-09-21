#!/usr/bin/env node
import { readdir, readFile, stat } from "node:fs/promises";
import { join, resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const OUT = resolve(ROOT, "out");
const SITE_URL = "https://typesafe.pro";
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

  const sitemap = await readFile(resolve(OUT, "sitemap.xml"), "utf8");
  assert(sitemap.includes(`<loc>${SITE_URL}/</loc>`), "Sitemap lacks homepage URL");
  assert(/<lastmod>[^<]+<\/lastmod>/.test(sitemap), "Sitemap lacks lastmod");
  assert(/<changefreq>weekly<\/changefreq>/.test(sitemap), "Sitemap should mark weekly change frequency");

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

  console.log("SEO validation passed for homepage metadata, JSON-LD, sitemap, robots, and OG image.");
}

main().catch((error) => {
  console.error(`SEO validation failed: ${error instanceof Error ? error.stack ?? error.message : String(error)}`);
  process.exitCode = 1;
});
