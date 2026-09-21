export const SITE_URL = "https://typesafe.pro";
export const SITE_NAME = "typesafe.pro";
export const SITE_TITLE = "TypeSafe Jev Playground and API Gateway | typesafe.pro";
export const SITE_DESCRIPTION =
  "Try TypeSafe Jev in a browser playground. Turn messy text into labels, scores, and yes/no probabilities, then copy API examples into your app.";
export const SITE_UPDATED_AT = "2026-09-21T00:00:00.000Z";
export const OG_IMAGE_PATH = "/opengraph-image";
export const OG_IMAGE_URL = `${SITE_URL}${OG_IMAGE_PATH}`;
export const OG_IMAGE_ALT = "typesafe.pro turns messy words into clear decisions with TypeSafe Jev.";

export const siteJsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "WebSite",
      "@id": `${SITE_URL}/#website`,
      name: SITE_NAME,
      url: `${SITE_URL}/`,
      description: SITE_DESCRIPTION,
      inLanguage: "en",
    },
    {
      "@type": ["SoftwareApplication", "WebApplication"],
      "@id": `${SITE_URL}/#application`,
      name: SITE_NAME,
      url: `${SITE_URL}/`,
      applicationCategory: "DeveloperApplication",
      operatingSystem: "Web",
      isAccessibleForFree: true,
      description:
        "An independent learning and testing gateway for trying TypeSafe Jev decisions in the browser and copying API examples into an application.",
      offers: {
        "@type": "Offer",
        price: "0",
        priceCurrency: "USD",
        category: "Free learning and testing access",
      },
    },
  ],
} as const;

export function jsonLd(value: unknown) {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}
