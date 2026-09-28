import { dirname, join } from "node:path";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "../..");

/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot: repoRoot,
  images: {
    unoptimized: true,
  },
  poweredByHeader: false,
  reactStrictMode: true,
  // Pages are rendered by the Worker, so response headers live here rather than in a
  // static-assets `_headers` file (which only applies to files under `public/`).
  async headers() {
    return [
      {
        source: "/admin/:path*",
        headers: [
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
          { key: "Cache-Control", value: "no-store" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

// `next dev` gets its own directory so a concurrent `next build` (tests, CI checks, the
// review session's validation) cannot overwrite the files a running dev server uses.
export default function config(phase) {
  return phase === PHASE_DEVELOPMENT_SERVER ? { ...nextConfig, distDir: ".next-dev" } : nextConfig;
}
