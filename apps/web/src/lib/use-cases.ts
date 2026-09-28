// Build/server only. Never import this module from a client component.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { canonical, isRecord, validateRequest, validateResponse } from "./playground";
import { SITE_UPDATED_AT, SITE_URL } from "./seo";
import type { EvaluationRequest, EvaluationResponse } from "./typesafe";
import { DEMO_LIMITS, SITEMAP_CHUNK_SIZE, USE_CASES_PAGE_SIZE, type UseCasePage, type UseCaseRelease } from "./use-case-types";

type Shard = { file: string; count: number; sha256: string };
type Catalog = { pages: UseCasePage[]; release: UseCaseRelease };
const buildCache = new Map<string, { manifest: string; release: string; catalog: Catalog }>();
const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const slugPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const validDate = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value));

function check(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`Invalid use-case catalog: ${message}`);
}

/** Drafts are previews for the local review session; production builds never see them. */
export const DRAFTS_ENABLED = process.env.NODE_ENV === "development" || process.env.TYPESAFE_CONTENT_DRAFTS === "1";

function checkExpectations(expected: unknown, request: EvaluationRequest, response: EvaluationResponse) {
  check(isRecord(expected) && Object.keys(expected).length === Object.keys(request.questions).length, "expected results must cover every question");
  for (const [id, question] of Object.entries(request.questions)) {
    const item = expected[id];
    const answer = response.answers[id];
    check(isRecord(item) && item.type === question.type, "expected result type mismatch");
    if (question.type === "choice" && answer.type === "choice") {
      check(item.choice === answer.choice, "stored choice fails expectation");
    } else {
      const actual = answer.type === "noul" ? answer.noul : answer.type === "score" ? answer.score : NaN;
      check(typeof item.min === "number" && typeof item.max === "number" && item.min <= actual && actual <= item.max, "stored result outside expected range");
    }
  }
}

// Mirrors the generator's static screening; the sandboxed iframe and its CSP are the boundary.
// Viewport units size content from the auto-sized frame and would grow it forever.
const viewportUnits = /\d\s*(?:[dsl]?v[hw]|vmin|vmax)\b/i;
const forbiddenMarkup = /<\/script|<\/style|<script|<link|<i?frame|<object|<embed|<base|<meta|<form|javascript:|\bsrc\s*=|@import/i;
const forbiddenScript = /<!-{2}|\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bimport\b|\beval\s*\(|\bFunction\s*\(|\bpostMessage\b|(?:\bwindow|\bdocument|\bself|\bglobalThis)\s*\.\s*location\b|(?<![.\w$])location\s*(?:\.|=[^=]|\[)|\blocalStorage\b|\bsessionStorage\b|document\s*\.\s*cookie/;

function validateDemo(value: unknown, slug: string) {
  check(isRecord(value), `${slug}: invalid demo`);
  for (const key of ["title", "concept", "interaction", "visual", "html", "js"]) {
    check(typeof value[key] === "string" && value[key].trim(), `${slug}: demo missing ${key}`);
  }
  const { html, css, js } = value;
  check(typeof html === "string" && typeof js === "string" && typeof css === "string", `${slug}: demo code must be strings`);
  check(html.length <= DEMO_LIMITS.html && css.length <= DEMO_LIMITS.css && js.length <= DEMO_LIMITS.js, `${slug}: demo code exceeds size limits`);
  check(!forbiddenMarkup.test(html) && !forbiddenMarkup.test(css) && !forbiddenMarkup.test(js), `${slug}: demo contains forbidden markup`);
  check(!forbiddenScript.test(js), `${slug}: demo script uses a forbidden API`);
  check(!viewportUnits.test(css) && !viewportUnits.test(js), `${slug}: demo uses viewport units`);
  check(validDate(value.verified_at), `${slug}: invalid demo verification date`);
  const probe = validateRequest({ model: "jev-latest", state: "probe", questions: value.questions });
  check(Array.isArray(value.samples) && value.samples.length >= DEMO_LIMITS.samples[0] && value.samples.length <= DEMO_LIMITS.samples[1], `${slug}: demo needs two to four verified samples`);
  for (const sample of value.samples) {
    check(isRecord(sample) && typeof sample.description === "string" && sample.description.trim() && validDate(sample.verified_at), `${slug}: invalid demo sample`);
    const request = validateRequest(sample.request);
    check(canonical(request.questions) === canonical(probe.questions), `${slug}: demo sample questions differ from the demo`);
    checkExpectations(sample.expected, request, validateResponse(sample.response, request));
  }
}

export function validateUseCase(value: unknown): UseCasePage {
  check(isRecord(value) && value.schema_version === 1, "unsupported page schema");
  check(typeof value.slug === "string" && slugPattern.test(value.slug), "invalid slug");
  for (const key of ["industry", "audience", "task_type", "search_intent", "summary", "problem", "input_description", "decision", "action", "intro", "solution"]) {
    check(typeof value[key] === "string" && value[key].trim(), `${value.slug}: missing ${key}`);
  }
  check(isRecord(value.seo) && typeof value.seo.title === "string" && value.seo.title.trim() && typeof value.seo.description === "string" && value.seo.description.trim(), "missing SEO metadata");
  check(Array.isArray(value.limitations) && value.limitations.length && value.limitations.every((item) => typeof item === "string" && item.trim()), "missing limitations");
  check(validDate(value.created_at) && validDate(value.updated_at), "invalid page dates");
  check(Array.isArray(value.examples) && value.examples.length === 3, "exactly three examples required");
  check(new Set(value.examples.map((item) => item.kind)).size === 3 && value.examples.every((item) => ["primary", "alternative", "edge"].includes(item.kind)), "invalid example kinds");
  for (const example of value.examples) {
    check(typeof example.name === "string" && example.name.trim() && typeof example.expected_description === "string" && example.expected_description.trim() && validDate(example.verified_at), "invalid example metadata");
    const request = validateRequest(example.request);
    checkExpectations(example.expected, request, validateResponse(example.response, request));
  }
  if (value.demo !== undefined && value.demo !== null) validateDemo(value.demo, value.slug);
  check(isRecord(value.verification) && typeof value.verification.model === "string" && validDate(value.verification.verified_at) && isRecord(value.verification.quality), "missing verification");
  for (const key of ["useful", "supported", "consistent"]) {
    const score = value.verification.quality[key];
    check(typeof score === "number" && score >= 0.8 && score <= 1, "page failed quality verification");
  }
  const novelty = value.verification.novelty_probability;
  check(typeof novelty === "number" && Number.isFinite(novelty) && novelty > 0.2 && novelty <= 1, "page failed novelty verification");
  return value as UseCasePage;
}

export function readDrafts(directory: string, published: Set<string>): UseCasePage[] {
  const dir = resolve(directory, "drafts");
  if (!existsSync(dir)) return [];
  const drafts: UseCasePage[] = [];
  for (const file of readdirSync(dir).filter((name) => name.endsWith(".json")).sort()) {
    let data: unknown;
    try { data = JSON.parse(readFileSync(resolve(dir, file), "utf8")); } catch { continue; }
    if (!isRecord(data) || data.status !== "pending" || !isRecord(data.page)) continue;
    const page = validateUseCase(data.page);
    check(page.slug === file.slice(0, -5), `draft ${file} does not match its slug`);
    check(!published.has(page.slug), `draft ${page.slug} collides with a published page`);
    drafts.push({ ...page, draft: true });
  }
  return drafts;
}

export function readUseCaseCatalog(directory = resolve(process.cwd(), "../../content/use-cases"), { drafts = DRAFTS_ENABLED } = {}): Catalog {
  const catalog = readPublishedCatalog(directory);
  if (!drafts) return catalog;
  const extra = readDrafts(directory, new Set(catalog.pages.map((page) => page.slug)));
  return extra.length ? { pages: [...catalog.pages, ...extra], release: catalog.release } : catalog;
}

function readPublishedCatalog(directory: string): Catalog {
  const manifestText = readFileSync(resolve(directory, "manifest.json"), "utf8");
  const releasePath = resolve(directory, "release.json");
  check(existsSync(releasePath), "missing release manifest");
  const releaseText = readFileSync(releasePath, "utf8");
  // Build workers share a verified immutable catalog snapshot, rather than parsing
  // every shard again for every article. A changed manifest/release invalidates it.
  const cached = process.env.NODE_ENV === "production" ? buildCache.get(directory) : undefined;
  if (cached?.manifest === manifestText && cached.release === releaseText) return cached.catalog;
  const manifest = JSON.parse(manifestText);
  check(manifest.schema_version === 1 && Array.isArray(manifest.shards), "unsupported manifest schema");
  check(manifest.catalog_hash === digest(canonical(manifest.shards)), "catalog checksum mismatch");
  const pages: UseCasePage[] = [];
  const files = new Set<string>();
  for (const shard of manifest.shards as Shard[]) {
    check(/^[a-zA-Z0-9_-]+\.json$/.test(shard.file) && !files.has(shard.file), "invalid or repeated shard filename");
    files.add(shard.file);
    const bytes = readFileSync(resolve(directory, shard.file));
    check(digest(bytes) === shard.sha256, `${shard.file}: checksum mismatch`);
    check(bytes.length <= 1_048_576, `${shard.file}: exceeds 1 MiB`);
    const data = JSON.parse(bytes.toString("utf8"));
    check(data.schema_version === 1 && Array.isArray(data.pages) && data.pages.length === shard.count && data.pages.length <= 100, `${shard.file}: invalid count or schema`);
    pages.push(...data.pages.map(validateUseCase));
  }
  check(manifest.total === pages.length && new Set(pages.map((page) => page.slug)).size === pages.length, "incorrect total or duplicate slug");
  const release: UseCaseRelease = JSON.parse(releaseText);
  check(release.schema_version === 1 && release.catalog_hash === manifest.catalog_hash && Array.isArray(release.pages) && validDate(release.generated_at), "invalid release manifest");
  check(typeof release.run_id === "string" && typeof release.source_sha === "string", "invalid release identity");
  check(new Set(release.pages.map((page) => page.slug)).size === release.pages.length, "repeated release slug");
  const bySlug = new Map(pages.map((page) => [page.slug, page]));
  const published = release.pages.map((entry) => {
    const page = bySlug.get(entry.slug);
    check(page && entry.title === page.seo.title && entry.created_at === page.created_at && entry.updated_at === page.updated_at, "release references missing or changed page");
    return page;
  });
  const catalog = { pages: published, release };
  if (process.env.NODE_ENV === "production") buildCache.set(directory, { manifest: manifestText, release: releaseText, catalog });
  return catalog;
}

export function catalogPageCount(pages: UseCasePage[]) {
  return Math.max(1, Math.ceil(pages.length / USE_CASES_PAGE_SIZE));
}

export function catalogUrl(page: number) {
  return page === 1 ? "/use-cases" : `/use-cases/page/${page}`;
}

export function publishedPages() {
  return readUseCaseCatalog().pages.filter((page) => !page.draft);
}

export function sitemapEntries() {
  const pages = publishedPages();
  const updated = pages.map((page) => page.updated_at).sort().at(-1) ?? SITE_UPDATED_AT;
  return [
    { url: `${SITE_URL}/`, updated: SITE_UPDATED_AT },
    ...Array.from({ length: catalogPageCount(pages) }, (_, index) => ({ url: `${SITE_URL}${catalogUrl(index + 1)}`, updated })),
    ...pages.map((page) => ({ url: `${SITE_URL}/use-cases/${page.slug}`, updated: page.updated_at })),
  ];
}

export function sitemapChunks(entries = sitemapEntries()) {
  return Array.from({ length: Math.ceil(entries.length / SITEMAP_CHUNK_SIZE) }, (_, index) => entries.slice(index * SITEMAP_CHUNK_SIZE, (index + 1) * SITEMAP_CHUNK_SIZE));
}
