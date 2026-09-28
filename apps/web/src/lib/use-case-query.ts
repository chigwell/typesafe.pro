import type { BrowserQuery } from "@/components/UseCaseBrowser";

export type Search = Promise<Record<string, string | string[] | undefined>>;

const one = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value) ?? "";
const slug = (value: string) => (/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) ? value : "");

/** Normalise listing URL parameters; anything unexpected falls back to the default view. */
export async function readQuery(searchParams: Search): Promise<BrowserQuery> {
  const params = await searchParams;
  const page = Number.parseInt(one(params.page), 10);
  return {
    q: one(params.q).slice(0, 200),
    category: slug(one(params.category)),
    tag: slug(one(params.tag)),
    page: Number.isFinite(page) && page > 1 ? Math.min(page, 500) : 1,
  };
}
