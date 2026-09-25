import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UseCaseCatalog } from "@/components/UseCaseCatalog";
import { catalogPageCount, catalogUrl, readUseCaseCatalog } from "@/lib/use-cases";
import { SITE_URL } from "@/lib/seo";

export const dynamicParams = false;
export function generateStaticParams() {
  const count = catalogPageCount(readUseCaseCatalog().pages);
  // The first catalog page lives at /use-cases. The unused sentinel lets an empty static export build.
  return count > 1 ? Array.from({ length: count - 1 }, (_, index) => ({ page: String(index + 2) })) : [{ page: "0" }];
}
export async function generateMetadata({ params }: { params: Promise<{ page: string }> }): Promise<Metadata> {
  const { page } = await params;
  const url = `${SITE_URL}${catalogUrl(Number(page))}`;
  return { title: `TypeSafe Use Cases — Page ${page}`, description: "Practical TypeSafe Jev API examples with verified inputs and outputs, code in seven languages, and a live playground.", alternates: { canonical: url }, openGraph: { title: `TypeSafe Use Cases — Page ${page}`, url } };
}
export default async function Page({ params }: { params: Promise<{ page: string }> }) {
  const { page } = await params;
  const number = Number(page);
  if (!/^\d+$/.test(page) || number < 2 || number > catalogPageCount(readUseCaseCatalog().pages)) notFound();
  return <UseCaseCatalog page={number} />;
}
