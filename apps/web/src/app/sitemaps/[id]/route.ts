import { sitemapChunks } from "@/lib/use-cases";

export const dynamic = "force-static";
export const dynamicParams = false;
export function generateStaticParams() { return sitemapChunks().map((_, index) => ({ id: `${index}.xml` })); }
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const match = /^(\d+)\.xml$/.exec(id);
  const chunk = match ? sitemapChunks()[Number(match[1])] : undefined;
  if (!chunk) return new Response("Not found", { status: 404 });
  const urls = chunk.map(({ url, updated }) => `<url><loc>${url}</loc><lastmod>${updated}</lastmod><changefreq>weekly</changefreq></url>`).join("");
  return new Response(`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`, { headers: { "Content-Type": "application/xml" } });
}
