# Behavior-preserving refactor register

## Boundaries and entrypoints

- The Next.js App Router site runs on the OpenNext Cloudflare Worker. The browser
  calls the public gateway and content API; server rendering also reads content.
- FastAPI `create_app` wires authentication, Redis admission/scheduling, streamed
  upstream transport, Postgres persistence, observability, and public content routes.
- `seo_content` owns local review orchestration. LLM7 generates candidates; Jev
  supplies typed judgments. Only explicit human approval publishes through the
  content API. Tests, builds, and parity checks use fake providers and local fixtures.
- Supported interfaces include `/v1/systemone`, health, analytics, public content
  and OpenAPI, admin cookie routes, content-token write routes, version-1 content,
  `python -m seo_content` commands, `python -m proxy.seo`, npm scripts, factory/helper
  imports, old pagination redirects, legacy tokens, Redis metric namespaces, and demo
  CSS aliases. The injected iframe runtime stays plain JavaScript with its existing
  sandbox, CSP, source-window checks, and fixed questions.
- API/generator content models remain identical independent copies; their existing
  equality test protects deployment isolation. Public generated TypeScript stays.

## Behavior and parity matrix

| Area | Behavior held constant | Evidence |
| --- | --- | --- |
| Gateway | route/validation order, duplicate headers, exact request/response bytes, errors, compression, request IDs, CORS | API proxy, validation, admission and contract tests |
| Capacity | priority/FIFO, bounded upload/body budgets, disconnects, shielded lease release, no automatic upstream retry | admission and endpoint-disconnect tests |
| Content | drafts private, preview expiry, slugs/search/tags/order, byte serialization, ETags, miss-only read budget, immediate invalidation | use-case, OpenAPI, schema and cache tests |
| Playground | authored samples versus saved verification; live failures never substitute samples; landing edit mode versus click-only use cases; cancellation/stale-result text | component, transport and SSR tests |
| Admin | credentialed cookie auth, ten-second non-overlapping eight-endpoint polls, partial results, query/reset rules, private-data clearing | admin lifecycle and presentation tests |
| Generator | exact prompts/context, call order, attempts, thresholds, best quality version, saved answers, current budget scope | recording fake-provider transcripts and serialized fixtures |
| Drafts/import | resume fields/defaults, four feedback scopes, latest revision approval, counters, dates and report sequencing | recording fake API and temporary legacy catalog fixture |
| Presentation | markup/classes, caller-owned code tabs/copy/typing, responsive cascade, themes and iframe brand tokens | web tests; before/after screenshots and computed styles |

## Reviewable passes

Each pass is a separate conventional commit and stacked draft PR. Base each PR on
its predecessor so its diff contains only that pass. Integrate in this order:

| Pass | Structural change | Required check |
| --- | --- | --- |
| 0 | contract fixtures, behavior register, import fixture and lifecycle characterization | fixtures pass against original behavior |
| 1 | delete definition-only symbols and obsolete shard/release types in both schema copies | consumer search; unchanged schemas/OpenAPI; relevant suites |
| 2 | lightweight errors and command-specific generation imports | adapter-unavailable maintenance smoke; exception identity; SEO suite |
| 3 | pure shared highlighted-code lines | SSR, syntax, copy/typing behavior |
| 4 | standalone result presentation, original export retained | answer types, raw/copy, both playgrounds |
| 5 | presentational admin sections; state/effects retained | admin DOM and component suite |
| 6 | auth/poll hooks and named typed snapshots | cadence, non-overlap, abort/stale settlement, private clearing |
| 7 | separate playground config/transport/validation/samples and editor views | facade compatibility, request lifecycle and component suites |
| 8 | dedicated ASGI gateway endpoint; unchanged control flow | full proxy/validation/admission and disconnect cleanup |
| 9 | cache module separated from SQL persistence; old imports retained | fake clock/capacity, ETag, limiter race, invalidation |
| 10 | example verification helper | exact provider transcript, attempts, saved results |
| 11 | quality repair helper and private named best-version record | transcript/final page, localization and best-version tests |
| 12 | candidate filtering/pooling helper | exact ordering, remaining choices, duplicate/retry tests |
| 13 | draft conversion helpers and internal typed records | golden drafts/reports, resume/feedback/approval API sequence |
| 14 | contiguous CSS files in exact original import/declaration order | screenshots, computed styles, brand tokens and reconstructed CSS |

Focused checks run after each pass. Final gates are both Python Ruff lint/format
checks, all API/SEO/web tests, strict TypeScript, Worker build, shell syntax/
ShellCheck, Compose configuration, API Docker build and nginx configuration.
Use only disposable test databases/Redis and mock upstreams. Never load the root
production `.env` for tests or browser fixtures. A gate requiring unavailable tooling
must be recorded as unverified; it is not a passing check.

## Deferred migrations and functional changes

These passes do not upgrade frameworks/dependencies, unify schema packaging,
introduce fetching/state/workflow libraries, distribute the scheduler, change the
injected runtime, or retire supported interfaces. Those require separate tasks.

Known behavior to preserve until a separate explicit fix:

- A superseded landing request may clear a newer request's timeout if its abort
  settles late. Moving code must not silently correct timeout ownership.
- Existing redaction secret lists omit configured content tokens.
- `added_last_deploy` currently counts pages published in seven days.
- Provider POSTs consume the shared budget; content/inspiration HTTP calls do not.
- Missing Node/jsdom/permission-harness support warns and continues today.
- Article examples all must pass; demos may drop failed samples when two remain.

Production consumers, live model accuracy, and deployment rollback are outside the
parity evidence. Do not refactor deployment until a disposable rollback harness
proves previous-release restoration and preservation of database/Redis volumes.

## Final validation record

Completed on 2026-10-04 using isolated worktrees, fake providers and the local
synthetic API. The original checkout's existing `next-env.d.ts` and `.idea/`
changes were left untouched.

| Gate | Result |
| --- | --- |
| Full API suite | 240 passed, disposable PostgreSQL/Redis and mocked upstreams |
| Full SEO suite | 163 passed, deterministic provider/content fixtures |
| Full web suite | 72 passed in 14 suites, no unhandled teardown errors |
| Python lint/format | API/deploy and SEO passed; 39 and 29 files already formatted |
| Strict TypeScript | Passed with `--noUnusedLocals --noUnusedParameters` |
| Next.js/OpenNext Worker build | Passed after final CSS extraction |
| CSS source/cascade | Nine contiguous slices reconstruct all 37,367 original bytes |
| Browser comparisons | All 20 computed-style cases match, including iframe tokens |
| Deployment shell syntax / Compose config | Passed |
| ShellCheck | Unverified locally: executable unavailable |
| API image build | Unverified locally: Docker/buildx failed with EOF |
| Nginx configuration | Unverified locally: Docker daemon timed out |

The full web run initially caught height-report timers firing after test teardown.
Only the fixture now owns/clears fake timers; production runtime behavior is unchanged.
An initial final Worker attempt ran out of local disk space; removing task-created
regenerable artifacts allowed the unchanged dependency build to pass.

Independent review found no P0–P3 regressions in the integrated source. Gateway,
cache and moved presentation helpers were compared structurally; generator prompts,
provider calls, retry rules, ordering, draft defaults and aliases were inspected.
CSS concatenation was independently verified against the preceding commit.

### Browser reproduction and evidence

Run `python3 apps/web/scripts/parity-api.py`, then start the existing web dev script
with `TYPESAFE_API_BASE=http://127.0.0.1:4310` and
`NEXT_PUBLIC_TYPESAFE_API_BASE=http://127.0.0.1:4310` on port 3084.
Use light and dark themes at 1440×900 and 390×844 on `/`, `/use-cases`,
`/use-cases/playlist-mood-palette`, `/admin`, and the guide's iframe demo.
Do not click live evaluation controls; the fixture never forwards provider requests.

[The portable comparison record](refactor-visual-parity.json) records each route,
viewport and matching computed-style digests. Forty before/after screenshots and
the full style records are saved locally in the task's `refactor-parity` artifact
directory. Screenshot comparisons allow existing typing/cursor animation, hover
states, selection highlights, dev indicators and admin update timestamps; they are
not a claim of frozen pixel identity. Representative guide and iframe comparisons
were visually inspected alongside exact style and stylesheet-source parity.

### Review and merge sequence

All passes are stacked draft PRs. Review in numerical order and require the full CI
checks before merging. Preserve the stack through merge commits, or rebase later
branches after a squash merge; retarget each successor to main once its base lands.
The existing main-branch workflow deploys merged changes, so no PR was merged and
no production deployment or content publication was performed here.

Local Docker/nginx/ShellCheck gaps still need CI confirmation. Live accuracy,
external consumers and deployment rollback remain unverified. The deferred
functional fixes and migrations above require separate tasks.

| Pass | Draft PR |
| --- | --- |
| 0 | [00-parity](https://github.com/chigwell/typesafe.pro/pull/2) |
| 1 | [01-dead-code](https://github.com/chigwell/typesafe.pro/pull/3) |
| 2 | [02-maintenance](https://github.com/chigwell/typesafe.pro/pull/4) |
| 3 | [03-code-lines](https://github.com/chigwell/typesafe.pro/pull/5) |
| 4 | [04-results](https://github.com/chigwell/typesafe.pro/pull/6) |
| 5 | [05-admin-views](https://github.com/chigwell/typesafe.pro/pull/7) |
| 6 | [06-admin-lifecycle](https://github.com/chigwell/typesafe.pro/pull/8) |
| 7 | [07-playground](https://github.com/chigwell/typesafe.pro/pull/9) |
| 8 | [08-gateway](https://github.com/chigwell/typesafe.pro/pull/10) |
| 9 | [09-content-cache](https://github.com/chigwell/typesafe.pro/pull/11) |
| 10 | [10-examples](https://github.com/chigwell/typesafe.pro/pull/12) |
| 11 | [11-quality](https://github.com/chigwell/typesafe.pro/pull/13) |
| 12 | [12-candidates](https://github.com/chigwell/typesafe.pro/pull/14) |
| 13 | [13-drafts](https://github.com/chigwell/typesafe.pro/pull/15) |
