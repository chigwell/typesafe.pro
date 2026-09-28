import { useCaseSitemap } from "@/lib/content-api";
import { SITE_UPDATED_AT, SITE_URL } from "@/lib/seo";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const match = /^(\d{1,4})\.xml$/.exec(id);
  if (!match) return new Response("Not found", { status: 404 });
  const chunk = Number(match[1]);
  let sitemap;
  try {
    sitemap = await useCaseSitemap(chunk);
  } catch {
    return new Response("Sitemap temporarily unavailable", { status: 503, headers: { "Retry-After": "300" } });
  }
  if (chunk >= sitemap.chunks) return new Response("Not found", { status: 404 });
  const newest = sitemap.items.map((item) => item.updated_at).sort().at(-1) ?? SITE_UPDATED_AT;
  const urls = [
    ...(chunk === 0 ? [{ url: `${SITE_URL}/`, updated: SITE_UPDATED_AT }, { url: `${SITE_URL}/use-cases`, updated: newest }] : []),
    ...sitemap.items.map((item) => ({ url: `${SITE_URL}/use-cases/${item.slug}`, updated: item.updated_at })),
  ].map(({ url, updated }) => `<url><loc>${url}</loc><lastmod>${updated}</lastmod><changefreq>weekly</changefreq></url>`).join("");
  return new Response(`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`, {
    headers: { "Content-Type": "application/xml", "Cache-Control": "public, max-age=900" },
  });
}
