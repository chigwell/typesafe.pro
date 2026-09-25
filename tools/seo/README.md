# Verified use-case content

This isolated Python project prepares English use-case pages for the static website.
Content lives in `content/use-cases`; neither ordinary builds nor validation call a model.
The site publishes only the records listed in `release.json`.

## Commands

From the repository root:

```sh
uv sync --project tools/seo --frozen
uv run --project tools/seo python -m seo_content validate
uv run --project tools/seo pytest tools/seo/tests
uv run --project tools/seo ruff check tools/seo
uv run --project tools/seo ruff format --check tools/seo
```

Generation needs `LLM7_BASE_URL`, `LLM7_TOKEN`, `LLM7_MODEL`, and
`TYPESAFE_ADMIN_API_TOKEN_1`. Load local secrets with uv, never add them to content:

```sh
uv run --project tools/seo --env-file .env python -m seo_content generate \
  --run-id local-pilot-001 --source-sha FULL_GIT_COMMIT_SHA \
  --baseline /tmp/published-manifest.json --report /tmp/content-report.json
```

Use a fresh run ID for a new attempt. A completed run with the same run ID and source SHA
replays its original release and report without provider calls. A reused run ID with a
different source SHA fails. The baseline must be the last confirmed public release
manifest, reconciled with the deployment journal. For the first publication only:

```json
{"schema_version":1,"run_id":"","source_sha":"","catalog_hash":"","generated_at":null,"pages":[]}
```

`--max-new-pages 1` can tighten the pilot limit; the hard maximum is five.
To use a disposable catalog, put `--content-dir /tmp/catalog` before the subcommand.

## Pipeline and bounds

- Each idea round requests ten scenarios; at most five rounds are attempted.
- The complete run has a 15 minute and 200 external-call budget, including retries.
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
  all must be >=0.8. Only these complete pages enter the catalog.

## Data and recovery

Page shards contain at most 100 pages or 1 MiB. `manifest.json` hashes the exact shard
bytes; its catalog hash is SHA-256 of sorted-key compact JSON for the ordered shard
list. Matching `index-*.json` files hold only compact scenario descriptions. Existing
records remain unchanged when appending new records. Page appends use a validated write-ahead journal, fsynced before shard/index/manifest
replacement. Loading the catalog replays an interrupted append idempotently; the
original records must remain unchanged and all checksums must match. CI validates
and commits the complete changed set before publishing the artifact.

The release is the previously published set plus at most five approved pending/new
records. Unpublished records from failed deploys take priority over new generation.
Generation checkpoints in `runs/` contain safe counters, error codes, baseline slugs,
and the final release. The run budget is checkpointed at HTTP boundaries; interruption
during an unapproved draft can discard that draft, but not approved pending records.
Catalog, index, baseline and release corruption are hard errors; they must never be
silently treated as provider outages. Deploy publication/accounting is owned by the
repository's release scripts, not this generator.

`generated_count` reports records generated in that run. It does not report the
publication delta: reused pending pages can be published with `generated_count=0`.
The admin deployment journal computes added pages from consecutive published snapshots.

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
