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
