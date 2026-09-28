import { defineCloudflareConfig } from "@opennextjs/cloudflare";

// Pages render per request from the cached content API; no incremental cache binding yet.
export default defineCloudflareConfig({});
