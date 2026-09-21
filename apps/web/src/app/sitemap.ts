import type { MetadataRoute } from "next";
import { SITE_UPDATED_AT, SITE_URL } from "@/lib/seo";

export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: `${SITE_URL}/`,
      lastModified: new Date(SITE_UPDATED_AT),
      changeFrequency: "weekly",
      priority: 1,
    },
  ];
}
