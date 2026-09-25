import { sitemapChunks } from "@/lib/use-cases";
import { SITE_URL } from "@/lib/seo";

export const dynamic = "force-static";
export function GET() {
  const entries = sitemapChunks().map((chunk, index) => `<sitemap><loc>${SITE_URL}/sitemaps/${index}.xml</loc><lastmod>${chunk.map((entry) => entry.updated).sort().at(-1)}</lastmod></sitemap>`).join("");
  return new Response(`<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${entries}</sitemapindex>`, { headers: { "Content-Type": "application/xml" } });
}
