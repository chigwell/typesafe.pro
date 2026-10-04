# Generated use-case pages

The public site renders `/use-cases` and `/use-cases/<slug>` from a single template
per request, reading the public use-case API (`/v1/use-cases`, `/v1/use-cases/{slug}`,
`/v1/use-case-facets`, `/v1/use-cases-sitemap`; documented in `/openapi.json`). Pages
are stored in Postgres. Page content is generated only by the local interactive review
command (`npm run content:review`), where a human approves every page before it is
published. CI, Next.js builds, PR checks, and tests never call an LLM.

## Data and quality

Each page has a status (`draft`, `published`, `archived`), one of the seeded
categories, 2–5 tags, denormalised card fields for the listing, the full validated page
JSON, and a weighted full-text vector for search. Only published pages appear in the
listing, search, facets and sitemap; drafts are reachable only through a signed,
expiring preview link. The generator reads a compact list of every non-archived page
for duplicate retrieval. Slugs are never reused.

The Python generator in `tools/seo` has its own frozen environment. LLM7 supplies
English ideas, prose, API requests, and qualitative expected outcomes. A bounded
llmatch-messages extraction loop and Pydantic validate each response without
requiring provider-native structured output. Code snippets are rendered from the
validated request by the existing seven-language code generator.

Jev compares scenarios by their problem, input, decision, and resulting action,
including other accepted candidates in the same run. A changed industry alone is
not new content. Up to 200 existing scenarios are compared exhaustively; beyond
that, BM25 retrieves 30 candidates and adds matching task types. Duplicate
probability must be at most 0.2 for every comparison; values at least 0.8 reject a
duplicate, and intermediate values are skipped. These are conservative initial
thresholds, not guarantees of semantic uniqueness.

The initial five-pair live calibration passed these thresholds with Jev 1.13.0:
paraphrased and industry-swapped duplicates scored 0.98 and 0.95; three distinct
tasks scored 0.02–0.05. See [the recorded calibration](novelty-calibration.json).
This small smoke check is not a general accuracy benchmark.

All three examples (primary, alternative, edge) must pass a real request to
`https://api.typesafe.pro/v1/systemone`. Choice labels and probability/score ranges
are checked rather than exact floating-point answers. Stored answers identify the
model and verification time. Jev's independent usefulness, supported-claims, and
consistency checks must each reach 0.8. Generated prose is data and is never
rendered as raw HTML.

Every new page also carries an interactive visual demo: LLM7 proposes three demo
concepts (the visitor enters a small input, presses a button, one to three fixed
TypeSafe questions are sent, and the answers drive an animation such as floating
emoji or colour areas proportional to probabilities); the reviewer picks one, and
LLM7 writes plain HTML, CSS and vanilla JavaScript against a small host runtime.
The code is screened statically (no scripts, styles, links, frames, forms, `src`,
`fetch`, `eval`, `import`, storage, `location`, `postMessage` and similar), syntax
checked with `node --check`, and its two to four sample inputs are executed against
the real API with predicted expectations. The demo itself is then run in jsdom on each
sample's real answers (and on a failed request); a runtime error, or a button that never
calls the API, is fed back to the model, all before the reviewer ever sees it. On the
site the demo runs in an `<iframe sandbox="allow-scripts">` with an opaque origin
and a `Content-Security-Policy` of `default-src 'none'` plus `connect-src` for the
API only; the host runtime `window.TypeSafeDemo` is the only way to call the API,
and the demo supplies just the `state` for the page's fixed questions. Verified
sample results are rendered statically for crawlers and readers without JavaScript.

Demos are styled by a compact brand kit, `apps/web/src/lib/demo-brand.json` (the
single source): site colour tokens for light and dark themes, a categorical palette
`--ts-c1…6`, and `ts-*` classes for inputs, buttons, chips, cards, panels, status,
meters and legends. The site injects the kit's CSS (`demo-brand.ts`) into every demo
document before the demo's own CSS, so previews and production look identical; the
generator sends the model only the class list, token names and guidelines, and the
model writes custom CSS just for the scenario's visual. A test keeps the tokens equal
to `globals.css`.

The frame height follows the content: the runtime measures the body (which is
`height:auto`), reports changes from resize, DOM mutations, transitions, animations
and font loading, and the host re-requests a measurement after hydration. Heights are
clamped to 120–4000 px (beyond that the frame scrolls). Viewport units are rejected,
and the runtime stops reporting if the height keeps changing, so content sized from
the frame cannot grow it forever.

Defaults: ten ideas per round, three attempts per model stage, 240 s per LLM7 call,
two automatic repairs of examples and of the demo using the live API answers, up to
two in-place prose repairs when a quality check scores below 0.8 (a consistency
failure is first localised with one Jev request per page part: each example, framing,
solution, limitations; the model sees the failing rubric and weak parts and may realign
the input description, decision and action with the verified example questions, which
stay fixed; the best-scoring version is kept), one
automatic page retry with the failure as feedback, transient provider errors
(timeouts, 429, 5xx, Cloudflare 52x) retried after 10 s and 30 s before asking, 400 provider POSTs and 60 minutes per review
session. Content API and inspiration requests do not consume the call budget;
time spent waiting for the reviewer is excluded. A stored page that fails
the schema fails `npm run content:check`; provider unavailability ends the session with pending drafts kept.

## Setup

Keep these values in the ignored root `.env`: `LLM7_BASE_URL`, `LLM7_TOKEN`,
`LLM7_MODEL`, `TYPESAFE_ADMIN_API_TOKEN_1` and `TYPESAFE_CONTENT_TOKEN_1`. The admin
API token authenticates Jev requests to the TypeSafe.pro gateway; the content token
(at least 32 characters, the same value as the production secret) is the only credential
the content write API accepts, and the admin cookie is not. Upstream master credentials
are not used by the generator and none of these credentials belong in `NEXT_PUBLIC_*`
variables.

Validate the local configuration (values are never printed or uploaded):

```sh
python3 scripts/configure-content-secrets.py
```

CI never generates content; it only needs `TYPESAFE_CONTENT_TOKEN_1` to configure the
deployed API.

## Local review session

```sh
npm run content:review   # add: -- --max-pages 1 --no-browser --resume --auto-select
```

Each idea round is seeded by the five newest Hacker News
story titles (Algolia API, Firebase API as a fallback; a title is never used twice in
a session). Every idea must grow out of one title's domain, audience or situation,
without mentioning the news, Hacker News, companies or people from it; titles are
cleaned, truncated and passed as untrusted data, and they are stored only in the
draft (`inspiration`) and as `inspiration_source` in the run report — never on a
published page. The idea stage runs at temperature 1.0, asks for a rotating mix of
Choice/Noul/Score decisions, and avoids the catalog's most frequent task types. If
Hacker News is unreachable the session falls back to random words. Near-identical
ideas (repeated task type or ≥ 0.5 word overlap with the catalog or earlier proposals)
are hidden before any API call. Headlines are loose themes only: ideas must be one
focused, everyday judgment on a sentence any visitor can type. One Jev request then
scores how focused and relatable each idea is (below 0.5 is hidden; the best are listed
first). When fewer than five clearly new ideas remain, the session asks again up to
twice, telling the model which earlier ideas were too close to which existing page.
It proposes ten ideas and checks each against the catalog
before showing them: clear duplicates (probability ≥ 0.8) are hidden and a new round
is requested automatically when none remain; partly similar ideas (0.2–0.8) are shown
with the most similar page so you can decide. Unused ideas stay available after you
pick one. It then offers three demo concepts, generates and verifies the page and demo,
picks a category and tags, stores the draft in the API and opens a signed preview link
(`https://typesafe.pro/use-cases/<slug>?preview=<token>`, or the site given by
`--preview-base`), which renders the draft with a visible banner and `noindex`.
Drafts never reach the listing, search, sitemap or facets.

For each draft: `a` approves, `f` regenerates the text, the demo, the demo concept
or both with your written feedback (all feedback accumulates and is passed to the
model), `s` skips the idea, `o` reopens the preview and `q` ends the session.
Approval publishes the page — it is live on the site immediately, without a deploy —
and records the session's run report. Skipped ideas are stored and excluded from later
proposals. Pending drafts survive quitting; `--resume` reviews them first without new
model calls.

## Production deployment

Content and code ship separately. Publishing a page is a content API write and needs no
deploy. A push to `main` runs the workflow, which after all checks deploys the API
(including migrations), then builds the web app with OpenNext and deploys it as the
Cloudflare Worker `typesafe-pro-web`, and finally runs `npm run smoke` and
`npm run validate:seo -- --all` against the deployed Worker. The SEO validation compares
the sitemap with the API's published pages and checks every article's canonical,
metadata, structured data and server-rendered content.

Both scripts take a base URL, so the same checks run locally:

```sh
npm run build:web && npm run preview --workspace @typesafe-pro/web
npm run smoke --workspace @typesafe-pro/web            # http://localhost:8787 by default
npm run validate:seo --workspace @typesafe-pro/web -- http://localhost:8787 --all
```

`TYPESAFE_API_BASE` (in `apps/web/.dev.vars` for the Worker, in the environment for the
scripts) points both at a local API.

## Admin and monitoring

The admin dashboard's Generated pages section reads protected `/admin/api/seo/`
summary, pages, and runs endpoints. It displays the current published inventory,
the difference in the last successful deployment, the latest attempt, rejection
counts, API calls/token usage when available, and page-level traffic. Totals are
derived from the recorded runs and the pages stored in the API.

The existing tracker records visits. `total_hits` counts recorded hits;
`unique_visitors` aggregates the existing IP/page/day identities, so a person
returning on another day is counted again. This is not an all-time unique-person
metric. Page content and sitemap do not depend on analytics.

## Verification and local use

```sh
uv sync --project tools/seo --frozen
npm run content:check
npm run content:test
uv run --project apps/api pytest apps/api/tests --basetemp=/private/tmp/typesafe-tests
npm run test:web
npm run build:web
```

The API tests need dedicated disposable PostgreSQL/Redis instances (see
`docs/admin.md`). Generation is the interactive session described above; there is
no unattended batch mode. Before approving, exercise the demo in the preview,
switch the site theme, and check the examples and rendered HTML. Search
performance is monitored independently; passing structural and model checks does
not promise indexing or rankings.

The initial two-page batch has also received manual editorial review. All six
examples were executed again after corrections, with fresh quality checks and a
new novelty comparison for the revised procurement scenario. The
[initial review record](initial-content-review.json) records the actual scores
and reviewed catalog hash. These local pilot runs are not production publications;
the production journal records a release only after deployment verification.
