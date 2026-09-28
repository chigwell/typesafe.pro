# Verified use-case content

This isolated Python project prepares English use-case pages, each with a sandboxed
interactive demo, for the website. Pages live in the API's Postgres database and are
written only through the content API (`/admin/api/content`, bearer
`TYPESAFE_CONTENT_TOKEN_1`); the site renders them per request from the public, cached
read API. Neither builds nor validation call a model, and every page is approved by a
human in the local review session before it is published.

## Commands

From the repository root:

```sh
uv sync --project tools/seo --frozen
npm run content:check             # validate every stored page against the schema
uv run --project tools/seo pytest tools/seo/tests
uv run --project tools/seo ruff check tools/seo
uv run --project tools/seo ruff format --check tools/seo
```

Generation needs `LLM7_BASE_URL`, `LLM7_TOKEN`, `LLM7_MODEL`,
`TYPESAFE_ADMIN_API_TOKEN_1` and `TYPESAFE_CONTENT_TOKEN_1` in the ignored root `.env`
(`python3 scripts/configure-content-secrets.py` checks them). `TYPESAFE_API_BASE`
selects another API, e.g. a local one. Load them with uv, never add them to content:

```sh
npm run content:review            # = uv run --project tools/seo --env-file .env python -m seo_content review
npm run content:review -- --max-pages 1 --no-browser
npm run content:review -- --resume
```

Options: `--max-pages` (approvals per session, 1–20, default 5), `--resume` (review
pending drafts first), `--auto-select` (take every idea and the first demo concept),
`--preview-base` (site that renders previews; default `https://typesafe.pro`, e.g.
`http://localhost:8787` for `npm run preview --workspace @typesafe-pro/web`),
`--no-browser`, `--max-calls`, `--max-minutes`, `--inspiration hn|words|none` (idea
seeds; default: the 5 newest Hacker News titles per round), `--headlines N`,
`--session-id` (must match `^[A-Za-z0-9_.-]+$`; each approval gets `<session>-<n>`).

The session: preflight (credentials, content API, categories, known pages) → ten ideas →
pick → novelty → three demo concepts → pick → page + demo generation and verification →
category and 2–5 tags → draft stored in the API with its review state → signed preview
link on the site → `a`pprove / `f`eedback (`t`ext, `d`emo, `c`oncept, `b`oth) / `s`kip /
`o`pen / `q`uit. Approval publishes the page (it is live immediately, no deploy) and
records the run report. See `docs/generated-pages.md` for the full flow.

Other commands: `npm run content:check` validates every stored page;
`npm run content:import` is the one-time import of the former `content/use-cases` file
catalog (pages keep their dates, drafts their review state; `--taxonomy heuristic`
assigns categories without a model).

## Pipeline and bounds

- Each idea round requests ten scenarios; at most ten rounds per session.
- A session has a 60 minute and 400 external-call budget by default, including retries;
  time spent waiting for the reviewer is paused.
- Each model stage makes at most three HTTP attempts. `llmatch-messages` extracts
  `<json>` contents with `max_retries=0`; the outer loop owns all retries. This avoids
  multiplying retries in llmatch, LangChain or the HTTP transport.
- JSON decoding and Pydantic enforce the schema. Invalid candidates are rejected;
  network/provider failures finish the run with the pages already fully verified.
  Retryable HTTP errors back off and respect `Retry-After` within the remaining budget;
  authentication errors are not retried.
- Exact normalized duplicates are rejected before semantic comparisons. Up to 200
  records are compared exhaustively; larger catalogs use 30 BM25 results plus all
  matching normalized task types. Noul comparisons use at most 20 questions per call.
  Duplicate probabilities <=0.2 pass; >=0.8 are duplicates; intermediate values are
  excluded from automatic publication. These initial thresholds need evaluation on
  domain-specific labeled data, not a claim of guaranteed uniqueness.
- Three examples are executed against the actual public TypeSafe.pro API using the
  server-side admin credential. Expected Choice labels or meaningful Noul/Score ranges
  must match. Score uses the level index range `0..len(criteria)-1`, not a probability.
- Three separate Noul judgments check usefulness, factual support and consistency;
  all must be >=0.8.
- The demo code (`Demo` in `models.py`) is screened with word-boundary patterns against
  scripts, styles, links, frames, forms, `src`, remote CSS URLs, `fetch`, `XMLHttpRequest`,
  `import`, `eval`, `Function`, storage, cookies, `location`, `postMessage`, parent-window
  access and `document.write`; `node --check` verifies syntax; each of its 2–4 sample
  states is executed with the demo's fixed questions and must meet its expectation. A
  failure is fed back to the model up to twice. The reviewer then inspects the demo in
  the sandboxed iframe before approval; only approved pages enter the catalog.

## Data and recovery

Pages, drafts, skips and run reports are rows in the API database; nothing is written to
the repository. A draft carries its review state (idea, concept, feedback, attempt), so
`--resume` continues on any machine. Skipped ideas are stored with their fingerprint and
any draft of them is archived; later rounds never propose them again. Content API failures
(429, 5xx, network) reuse the session's retries; a 401 stops the session before any model
call. Stored pages are revalidated with `npm run content:check`.

`generated_count` reports records generated in that session, including regenerated
attempts; `approved_count` is the number of pages published. Each approval records the
session report (mode, counters, rejection codes, approved/skipped counts) in the journal
that the admin dashboard reads.

## Novelty calibration

`tests/fixtures/novelty-pairs.json` contains independently labeled paraphrases,
industry-only substitutions and genuinely different decisions. To calibrate against
a live Jev model, validate each pair with `Idea.model_validate`, build its request with
`novelty_request(candidate, [existing])`, and record the resulting duplicate probability
alongside `expected_duplicate`. A duplicate should meet 0.8; a distinct task should be
at or below 0.2. Failures inform prompt/threshold review. Unit tests intentionally use
fake providers; they cannot establish model accuracy.

Provider bodies, authentication headers and tokens are never stored in reports or
printed. The checked-in API reference is supplied as trusted context to generation and
quality evaluation; generated drafts are treated as data. Update the reference when
the public API changes, then rerun both offline tests and a small live pilot.
