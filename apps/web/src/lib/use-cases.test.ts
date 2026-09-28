import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { afterEach, describe, expect, it } from "vitest";
import { canonical } from "./playground";
import { catalogPageCount, catalogUrl, readDrafts, readUseCaseCatalog, sitemapChunks, validateUseCase } from "./use-cases";
import { useCaseDemoFixture, useCaseFixture } from "@/test/use-case-fixture";

const directories: string[] = [];
const hash = (value: string) => createHash("sha256").update(value).digest("hex");
function catalog(count = 2) {
  const dir = mkdtempSync(join(tmpdir(), "typesafe-use-cases-"));
  directories.push(dir);
  mkdirSync(join(dir, "drafts"));
  const pages = Array.from({ length: count }, (_, index) => useCaseFixture(`case-${index}`));
  const data = JSON.stringify({ schema_version: 1, pages });
  const shards = count ? [{ file: "pages-0001.json", count, sha256: hash(data) }] : [];
  writeFileSync(join(dir, "pages-0001.json"), data);
  writeFileSync(join(dir, "manifest.json"), JSON.stringify({ schema_version: 1, total: count, shards, catalog_hash: hash(canonical(shards)) }));
  writeFileSync(join(dir, "release.json"), JSON.stringify({
    schema_version: 1, run_id: "test-release", source_sha: "test-source", catalog_hash: hash(canonical(shards)), generated_at: "2026-09-25T12:00:00Z",
    pages: pages.map((page) => ({ slug: page.slug, title: page.seo.title, created_at: page.created_at, updated_at: page.updated_at })),
  }));
  return dir;
}
afterEach(() => directories.splice(0).forEach((dir) => rmSync(dir, { recursive: true, force: true })));

describe("use-case publication catalog", () => {
  it("supports deterministic empty offline builds with an explicit release", () => {
    const dir = catalog(0);
    expect(readUseCaseCatalog(dir)).toEqual(readUseCaseCatalog(dir));
    expect(readUseCaseCatalog(dir).pages).toEqual([]);
    expect(catalogPageCount([])).toBe(1);
  });
  it.each([0, 2])("requires a release whitelist even when the catalog has %i records", (count) => {
    const dir = catalog(count);
    rmSync(join(dir, "release.json"));
    expect(() => readUseCaseCatalog(dir)).toThrow(/missing release manifest/);
  });
  it("publishes only release-whitelisted records", () => {
    const dir = catalog();
    const { release } = readUseCaseCatalog(dir);
    writeFileSync(join(dir, "release.json"), JSON.stringify({ ...release, pages: release.pages.slice(0, 1) }));
    expect(readUseCaseCatalog(dir).pages.map((page) => page.slug)).toEqual(["case-0"]);
  });
  it("blocks corrupted shards before rendering", () => {
    const dir = catalog();
    writeFileSync(join(dir, "pages-0001.json"), "{}");
    expect(() => readUseCaseCatalog(dir)).toThrow(/checksum mismatch/);
  });
  it("blocks release entries whose dates or title differ", () => {
    const dir = catalog();
    const { release } = readUseCaseCatalog(dir);
    release.pages[0].title = "A different article";
    writeFileSync(join(dir, "release.json"), JSON.stringify(release));
    expect(() => readUseCaseCatalog(dir)).toThrow(/missing or changed page/);
  });
  it("rejects path traversal even with a valid manifest checksum", () => {
    const dir = catalog();
    const manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
    manifest.shards[0].file = "../secret.json";
    manifest.catalog_hash = hash(canonical(manifest.shards));
    writeFileSync(join(dir, "manifest.json"), JSON.stringify(manifest));
    expect(() => readUseCaseCatalog(dir)).toThrow(/filename/);
  });
  it("rejects failed stored expectations and duplicate example kinds", () => {
    const page = useCaseFixture();
    page.examples[0].expected.queue.choice = "review";
    expect(() => validateUseCase(page)).toThrow(/fails expectation/);
    page.examples[0].expected.queue.choice = "plumbing";
    page.examples[1].kind = "primary";
    expect(() => validateUseCase(page)).toThrow(/example kinds/);
  });
  it.each([undefined, null, "0.9", 0.2, 0.1, 1.01, NaN, Infinity, -Infinity])("rejects invalid novelty probability %s", (novelty) => {
    const page = useCaseFixture();
    const value = { ...page, verification: { ...page.verification, novelty_probability: novelty } };
    expect(() => validateUseCase(value)).toThrow(/novelty verification/);
  });
  it.each([0.21, 0.8, 1])("accepts reviewer-approved and automatic novelty %s", (novelty) => {
    const page = useCaseFixture();
    page.verification.novelty_probability = novelty;
    expect(validateUseCase(page)).toEqual(page);
  });
  it("paginates at 24 records using stable canonical paths", () => {
    expect(catalogPageCount(Array.from({ length: 25 }, () => useCaseFixture()))).toBe(2);
    expect(catalogUrl(1)).toBe("/use-cases");
    expect(catalogUrl(2)).toBe("/use-cases/page/2");
  });
  it("splits sitemaps at exactly 10,000 URLs without losing entries", () => {
    const entries = Array.from({ length: 10_001 }, (_, index) => ({ url: `https://typesafe.pro/use-cases/case-${index}`, updated: "2026-09-25T12:00:00Z" }));
    const chunks = sitemapChunks(entries);
    expect(chunks.map((chunk) => chunk.length)).toEqual([10_000, 1]);
    expect(chunks.flat()).toEqual(entries);
  });
  it("validates an optional sandboxed demo", () => {
    const page = { ...useCaseFixture(), demo: useCaseDemoFixture() };
    expect(validateUseCase(page)).toEqual(page);
    expect(validateUseCase(useCaseFixture())).not.toHaveProperty("demo");
    const broken = (patch: (demo: ReturnType<typeof useCaseDemoFixture>) => void) => {
      const demo = useCaseDemoFixture();
      patch(demo);
      return { ...useCaseFixture(), demo };
    };
    expect(() => validateUseCase(broken((demo) => { demo.js = "fetch('https://x')"; }))).toThrow(/forbidden API/);
    expect(() => validateUseCase(broken((demo) => { demo.html = "<script>1</script>"; }))).toThrow(/forbidden markup/);
    expect(() => validateUseCase(broken((demo) => { demo.js = "a </script> b"; }))).toThrow(/forbidden markup/);
    expect(() => validateUseCase(broken((demo) => { demo.samples = demo.samples.slice(0, 1); }))).toThrow(/two to four/);
    expect(() => validateUseCase(broken((demo) => { demo.samples[0].response.answers.mood = { type: "noul", noul: 0.2 }; }))).toThrow(/expected range/);
    expect(() => validateUseCase(broken((demo) => { demo.samples[0].request.questions = { other: { type: "noul", instructions: "Other?" } }; }))).toThrow(/questions differ/);
    expect(() => validateUseCase(broken((demo) => { demo.html = "x".repeat(12_001); }))).toThrow(/size limits/);
  });
  it("loads pending drafts only when asked and keeps them out of the release", () => {
    const dir = catalog(1);
    const draft = { ...useCaseFixture("draft-case"), demo: useCaseDemoFixture() };
    writeFileSync(join(dir, "drafts", "draft-case.json"), JSON.stringify({ schema_version: 1, status: "pending", page: draft }), { flag: "w" });
    expect(readUseCaseCatalog(dir).pages.map((page) => page.slug)).toEqual(["case-0"]);
    const withDrafts = readUseCaseCatalog(dir, { drafts: true });
    expect(withDrafts.pages.map((page) => [page.slug, page.draft])).toEqual([["case-0", undefined], ["draft-case", true]]);
    expect(withDrafts.release.pages.map((page) => page.slug)).toEqual(["case-0"]);
    writeFileSync(join(dir, "drafts", "draft-case.json"), JSON.stringify({ schema_version: 1, status: "skipped", page: draft }));
    expect(readDrafts(dir, new Set())).toEqual([]);
    writeFileSync(join(dir, "drafts", "draft-case.json"), JSON.stringify({ schema_version: 1, status: "pending", page: { ...draft, slug: "case-0" } }));
    expect(() => readDrafts(dir, new Set(["case-0"]))).toThrow(/does not match its slug/);
  });
});
