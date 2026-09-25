import type { Metadata } from "next";
import { UseCaseCatalog } from "@/components/UseCaseCatalog";
import { OG_IMAGE_URL, SITE_URL } from "@/lib/seo";

export const metadata: Metadata = {
  title: "TypeSafe Use Cases — Practical Jev API Examples",
  description: "Explore TypeSafe Jev use cases with verified API examples, editable requests, and code in seven languages. Build typed choices, probabilities, and scores.",
  alternates: { canonical: `${SITE_URL}/use-cases` },
  openGraph: { title: "TypeSafe Use Cases", description: "Practical Jev API examples you can edit and try.", url: `${SITE_URL}/use-cases`, images: [OG_IMAGE_URL] },
};

export default function Page() { return <UseCaseCatalog />; }
