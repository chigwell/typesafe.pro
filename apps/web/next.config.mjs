import { dirname, join } from "node:path";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "../..");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  outputFileTracingRoot: repoRoot,
  images: {
    unoptimized: true,
  },
  poweredByHeader: false,
  reactStrictMode: true,
};

// `next dev` gets its own directory so a concurrent `next build` (tests, CI checks, the
// review session's validation) cannot overwrite the files a running dev server uses.
export default function config(phase) {
  return phase === PHASE_DEVELOPMENT_SERVER ? { ...nextConfig, distDir: ".next-dev" } : nextConfig;
}
