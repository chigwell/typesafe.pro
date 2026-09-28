import brand from "./demo-brand.json";

export const DEMO_BRAND = brand;

const vars = (tokens: Record<string, string>) => Object.entries(tokens).map(([name, value]) => `${name}:${value}`).join(";");

// Legacy aliases used by demos generated before the brand kit existed.
const LEGACY = "--demo-bg:var(--ts-surface);--demo-fg:var(--ts-ink);--demo-muted:var(--ts-muted);--demo-accent:var(--ts-accent);--demo-surface:var(--ts-raised);--demo-border:var(--ts-line);--demo-font:var(--ts-font)";

/**
 * Brand kit CSS injected into every sandboxed demo before the demo's own CSS. It mirrors
 * the site's tokens and component look (pill buttons, result panel, field labels).
 */
export const DEMO_BRAND_CSS = `:root{color-scheme:light;${vars(brand.tokens.light)};--ts-font:${brand.font};--ts-mono:${brand.mono};--ts-radius:8px;--ts-ease:cubic-bezier(0.16,1,0.3,1);${LEGACY}}
:root[data-theme="dark"]{color-scheme:dark;${vars(brand.tokens.dark)}}
html,body{margin:0;padding:0;height:auto!important;min-height:0!important;overflow-x:hidden;background:var(--ts-surface);color:var(--ts-ink);font:15px/1.55 var(--ts-font);-webkit-font-smoothing:antialiased}
#demo{box-sizing:border-box;padding:20px;height:auto!important;min-height:0!important;overflow-wrap:anywhere}
#demo *,#demo *::before,#demo *::after{box-sizing:border-box}
#demo :focus-visible{outline:3px solid var(--ts-accent);outline-offset:2px}
#demo h1,#demo h2,#demo h3,#demo p{margin:0}
#demo input,#demo textarea,#demo select{font:inherit;color:var(--ts-ink);background:var(--ts-raised);border:1px solid var(--ts-line);border-radius:var(--ts-radius);padding:11px 13px;max-width:100%}
#demo button{font:inherit;cursor:pointer}
#demo button:not([class]){display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:10px 20px;border:0;border-radius:999px;background:var(--ts-button);color:var(--ts-button-ink);font-size:14px;font-weight:650}
#demo button:disabled{opacity:.55;cursor:progress}
#demo .ts-stack{display:flex;flex-direction:column;gap:16px}
#demo .ts-row{display:flex;flex-wrap:wrap;align-items:center;gap:12px}
#demo .ts-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
#demo .ts-card{background:var(--ts-raised);border:1px solid var(--ts-line);border-radius:14px;padding:18px}
#demo .ts-panel{background:var(--ts-canvas);border:1px solid var(--ts-line);border-radius:var(--ts-radius);padding:20px 22px}
#demo .ts-eyebrow{color:var(--ts-accent);font:600 12px/1.5 var(--ts-mono);text-transform:uppercase;letter-spacing:.02em}
#demo .ts-title{font-size:20px;font-weight:650;line-height:1.3;letter-spacing:-.01em}
#demo .ts-text{color:var(--ts-body)}
#demo .ts-help{color:var(--ts-muted);font-size:12px;line-height:1.6}
#demo .ts-label{display:flex;flex-direction:column;gap:8px;font-size:13px;font-weight:650;color:var(--ts-ink)}
#demo .ts-input,#demo .ts-textarea{display:block;width:100%;font-weight:400}
#demo .ts-textarea{min-height:88px;resize:vertical;line-height:1.5}
#demo .ts-input:focus,#demo .ts-textarea:focus{border-color:var(--ts-accent);outline:3px solid var(--ts-accent-soft);outline-offset:0}
#demo .ts-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:10px 20px;border:1px solid transparent;border-radius:999px;background:var(--ts-button);color:var(--ts-button-ink);font-size:14px;font-weight:650;line-height:1.3;white-space:nowrap;transition:transform .25s var(--ts-ease),background .2s,color .2s}
#demo .ts-btn:hover:not(:disabled){transform:translateY(-2px)}
#demo .ts-btn-secondary{background:var(--ts-surface);color:var(--ts-ink);border-color:var(--ts-line)}
#demo .ts-chip{display:inline-flex;align-items:center;gap:6px;min-height:34px;padding:6px 14px;border:1px solid var(--ts-line);border-radius:999px;background:var(--ts-surface);color:var(--ts-body);font-size:13px;font-weight:600;transition:background .2s,color .2s,border-color .2s}
#demo .ts-chip:hover{border-color:var(--ts-accent);color:var(--ts-ink)}
#demo .ts-chip.is-active{background:var(--ts-accent-soft);border-color:var(--ts-accent);color:var(--ts-accent)}
#demo .ts-badge{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 10px;background:var(--ts-soft);color:var(--ts-body);font-size:12px;font-weight:600}
#demo .ts-status{min-height:1.6em;color:var(--ts-muted);font-size:13px}
#demo .ts-status.is-error{color:var(--ts-danger)}
#demo .ts-status.is-loading{animation:ts-pulse 1.2s ease-in-out infinite}
#demo .ts-value{color:var(--ts-accent);font-size:36px;font-weight:650;line-height:1.15;letter-spacing:-.02em}
#demo .ts-meter{position:relative;height:10px;border-radius:999px;background:var(--ts-soft);overflow:hidden}
#demo .ts-meter-fill{height:100%;width:0;border-radius:inherit;background:var(--ts-accent);transition:width .6s var(--ts-ease)}
#demo .ts-legend{display:flex;flex-wrap:wrap;gap:8px 16px;color:var(--ts-body);font-size:13px}
#demo .ts-swatch{display:inline-block;width:10px;height:10px;border-radius:999px;background:var(--ts-c1);vertical-align:middle;margin-right:6px}
#demo .ts-spinner{display:inline-block;width:16px;height:16px;border:2px solid currentColor;border-right-color:transparent;border-radius:999px;animation:ts-spin .8s linear infinite}
@keyframes ts-spin{to{transform:rotate(360deg)}}
@keyframes ts-pulse{50%{opacity:.45}}
@media (prefers-reduced-motion:reduce){#demo *,#demo *::before,#demo *::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}`;
