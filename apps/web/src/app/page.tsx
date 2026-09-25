import { LandingPage } from "@/components/LandingPage";
import { PublicPageViewTracker } from "@/components/PublicPageViewTracker";
import { jsonLd, siteJsonLd } from "@/lib/seo";

export default function Page() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(siteJsonLd) }} />
      <PublicPageViewTracker path="/" />
      <LandingPage />
    </>
  );
}
