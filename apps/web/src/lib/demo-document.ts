import { DEMO_BRAND_CSS } from "./demo-brand";
import { DEMO_RUNTIME } from "./demo-runtime";
import type { UseCaseDemo } from "./use-case-types";



/** Escape text for an inline <script> or <style>: it must never terminate its element. */
function inline(text: string) {
  return text.replace(/<\//g, "<\\/").replace(/<!-{2}/g, "<\\!--");
}

function jsonForScript(value: unknown) {
  return JSON.stringify(value).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

export function demoCsp(apiBase: string) {
  return `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src ${apiBase}; img-src data:; form-action 'none'; base-uri 'none'`;
}

/** The complete srcdoc of a sandboxed demo iframe. */
export function buildDemoDocument(demo: UseCaseDemo, apiBase: string) {
  const config = {
    apiBase,
    questions: demo.questions,
    samples: demo.samples.map((sample) => ({ state: sample.request.state, description: sample.description, answers: sample.response.answers })),
  };
  return [
    "<!doctype html>",
    '<html lang="en"><head><meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${demoCsp(apiBase)}">`,
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<title>${demo.title.replace(/[<>&]/g, (char) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[char] ?? char)}</title>`,
    `<style>${DEMO_BRAND_CSS}</style>`,
    `<style>${inline(demo.css)}</style></head>`,
    `<body><div id="demo">${demo.html}</div>`,
    `<script>window.__DEMO=${jsonForScript(config)};</script>`,
    `<script>${inline(DEMO_RUNTIME)}</script>`,
    `<script>${inline(demo.js)}</script>`,
    "</body></html>",
  ].join("\n");
}
