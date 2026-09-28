import { useCaseSitemap } from "@/lib/content-api";
import { SITE_UPDATED_AT, SITE_URL } from "@/lib/seo";

export const dynamic = "force-dynamic";

// Chunk 0 also carries the homepage and the catalog next to its 10,000 use cases.
export async function GET() {
  let chunks = 1;
  let updated = SITE_UPDATED_AT;
  try {
    const first = await useCaseSitemap(0);
    chunks = first.chunks;
    updated = first.items.map((item) => item.updated_at).sort().at(-1) ?? SITE_UPDATED_AT;
  } catch {
    // Still publish the index; the chunk handler reports its own failures.
  }
  const entries = Array.from({ length: chunks }, (_, index) => `<sitemap><loc>${SITE_URL}/sitemaps/${index}.xml</loc><lastmod>${updated}</lastmod></sitemap>`).join("");
  return new Response(`<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${entries}</sitemapindex>`, {
    headers: { "Content-Type": "application/xml", "Cache-Control": "public, max-age=900" },
  });
}
