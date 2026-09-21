import { ImageResponse } from "next/og";
import { OG_IMAGE_ALT, SITE_DESCRIPTION, SITE_NAME } from "@/lib/seo";

export const dynamic = "force-static";
export const alt = OG_IMAGE_ALT;
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px",
          color: "#f8fbff",
          background: "linear-gradient(135deg, #0e1b2a 0%, #174b6f 46%, #f0c875 100%)",
          fontFamily: "Inter, Arial, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "18px", fontSize: 34, fontWeight: 800 }}>
          <div
            style={{
              width: 58,
              height: 58,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "3px solid rgba(248,251,255,0.82)",
              borderRadius: 16,
              color: "#f8fbff",
            }}
          >
            T
          </div>
          {SITE_NAME}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "22px" }}>
          <div style={{ display: "flex", color: "#d8f2ff", fontSize: 28, fontWeight: 700, letterSpacing: 0 }}>
            TypeSafe Jev playground and API gateway
          </div>
          <div style={{ display: "flex", maxWidth: 900, fontSize: 76, fontWeight: 900, lineHeight: 1.02, letterSpacing: 0 }}>
            Messy words. Clear decisions.
          </div>
          <div style={{ display: "flex", maxWidth: 860, color: "#eef8ff", fontSize: 30, lineHeight: 1.32 }}>{SITE_DESCRIPTION}</div>
        </div>
        <div style={{ display: "flex", gap: "18px", color: "#0e1b2a", fontSize: 26, fontWeight: 800 }}>
          <div style={{ display: "flex", padding: "14px 20px", borderRadius: 999, background: "#f8fbff" }}>Choice</div>
          <div style={{ display: "flex", padding: "14px 20px", borderRadius: 999, background: "#f8fbff" }}>Noul</div>
          <div style={{ display: "flex", padding: "14px 20px", borderRadius: 999, background: "#f8fbff" }}>Score</div>
        </div>
      </div>
    ),
    size,
  );
}
