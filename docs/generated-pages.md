# Generated use-case pages

The public site renders `/use-cases` and `/use-cases/<slug>` from a single template
and versioned JSON in `content/use-cases`. Page content is generated only by the
local interactive review command (`npm run content:review`), where a human approves
every page before it is committed. CI, normal Next.js builds, PR checks, and tests
never call an LLM.

## Data and quality

`manifest.json` lists numbered page shards with their byte hashes. Each shard
holds at most 100 pages or 1 MiB. Compact scenario indexes support duplicate
retrieval. `release.json` selects the pages included in one static build; the site
exports the same inventory at `/use-cases-manifest.json`. Run checkpoints preserve
the random seed, completed work, report, and release across retries. Articles and
their slugs are append-only during generation.

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
the real API with predicted expectations before the reviewer ever sees it. On the
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
two in-place prose repairs when a quality check scores below 0.8 (the model sees the
failing rubric; verified examples stay fixed), one
automatic page retry with the failure as feedback, transient provider errors
(timeouts, 429, 5xx, Cloudflare 52x) retried after 10 s and 30 s before asking, 400 external calls and 60 minutes per review
session (time spent waiting for the reviewer is excluded). Corrupt catalog data
fails the build; provider unavailability ends the session with pending drafts kept.

## Setup

Keep these values in the ignored root `.env`: `LLM7_BASE_URL`, `LLM7_TOKEN`,
`LLM7_MODEL`, and `TYPESAFE_ADMIN_API_TOKEN_1`. The last credential authenticates to
the local TypeSafe.pro gateway; upstream master credentials are not used by the
generator and none of these credentials belong in `NEXT_PUBLIC_*` variables.

Validate the local configuration (values are never printed or uploaded):

```sh
python3 scripts/configure-content-secrets.py
```

CI needs none of these credentials: generation happens only on the reviewer's
machine and the production job has read-only repository permissions.

## Local review session

```sh
npm run dev:web          # optional; the session starts it when missing
npm run content:review   # add: -- --max-pages 1 --no-browser --resume --auto-select
```

The session refuses to start while `content/use-cases` has uncommitted changes or a
merge is in progress. Each idea round is seeded by the five newest Hacker News
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
writes a draft to `content/use-cases/drafts/<slug>.json` (ignored by Git) and
opens `http://localhost:3000/use-cases/<slug>` in the dev server, which renders
pending drafts with a visible banner. Drafts never reach the catalog listing,
sitemap, manifest or production builds.

For each draft: `a` approves, `f` regenerates the text, the demo, the demo concept
or both with your written feedback (all feedback accumulates and is passed to the
model), `s` skips the idea, `o` reopens the preview and `q` ends the session.
Approval appends the page to the catalog, rewrites `release.json` to the complete
catalog, stores the run report under `runs/`, and commits only `content/use-cases`
as `chore(content): add use case <slug>` with your Git identity. Skipped ideas are
recorded in `review-skips.json`, excluded from later proposals and committed at
the end of the session. Pending drafts survive quitting; `--resume` reviews them
first without new model calls. `git push` triggers publication.

## Production release and recovery

The workflow serializes the complete production process. After checks pass it
deploys the API (including additive journal migrations), reconciles the live
publication manifest with the private journal, validates the committed catalog,
builds the static output, and publishes that exact artifact to Cloudflare Pages
with the source commit as its identity. It never generates content and never
commits. `npm run deploy:web` dispatches this workflow against committed `main`;
it does not upload uncommitted local files or bypass the journal.

Before publication the workflow checks that `main` has not advanced. Each local
approval has its own release identity (`<session>-<n>`), so consecutive pushes
publish distinct snapshots. A single publication may add at most 50 new pages.
After verification the workflow records the approved session's generation report
(kept in `content/use-cases/runs/`) in the journal.

The journal is written through the existing SSH connection, using private
`python -m proxy.seo` commands in the API container. There is no public write API.
Publication is recorded only after the live manifest matches the build, every
article is in the sitemap, and new URLs return rendered articles. A failed build
or upload does not increase the published count. If publication succeeds but the
final journal write fails, the next run reconciles the live manifest first.
Workflow artifacts retain the baseline and release inventory for diagnosis.

For manual recovery, verify the production artifact before using `proxy.seo
publish --file <manifest>`. Replaying the same snapshot is idempotent. Older or
conflicting snapshots are rejected; an intentional rollback needs a fresh release
identity and time, not replay of an old publication record.

## Admin and monitoring

The admin dashboard's Generated pages section reads protected `/admin/api/seo/`
summary, pages, and runs endpoints. It displays the current published inventory,
the difference in the last successful deployment, the latest attempt, rejection
counts, API calls/token usage when available, and page-level traffic. Totals are
derived from verified publication snapshots, not the number of JSON files in Git.

The existing tracker records visits. `total_hits` counts recorded hits;
`unique_visitors` aggregates the existing IP/page/day identities, so a person
returning on another day is counted again. This is not an all-time unique-person
metric. Page content and sitemap remain static and do not depend on analytics.

## Verification and local use

```sh
uv sync --project tools/seo --frozen
npm run content:validate
npm run content:test
uv run --project apps/api pytest apps/api/tests deploy/tests --basetemp=/private/tmp/typesafe-tests
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
