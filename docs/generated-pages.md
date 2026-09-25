# Generated use-case pages

The public site renders `/use-cases` and `/use-cases/<slug>` from a single template
and versioned JSON in `content/use-cases`. Page content is generated only by the
production workflow or an explicit local generator command. Normal Next.js builds,
PR checks, and tests never call an LLM.

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
consistency checks must each reach 0.8. Generated provider text is data and is
never executed as source code or rendered as raw HTML.

Defaults: five newly published pages per deployment, ten ideas per round, five
rounds, three total attempts per stage, 200 external calls including retries, and
15 minutes of generation. Fully verified partial results survive budget or
provider failures. Corrupt catalog data fails the build; provider unavailability
does not prevent a release with the prior catalog.

## Setup

Keep these values in the ignored root `.env`: `LLM7_BASE_URL`, `LLM7_TOKEN`,
`LLM7_MODEL`, and `TYPESAFE_ADMIN_API_TOKEN_1`. The last credential authenticates to
the local TypeSafe.pro gateway; upstream master credentials are not used by the
generator and none of these credentials belong in `NEXT_PUBLIC_*` variables.

Validate configuration, then copy only those named values to repository secrets:

```sh
python3 scripts/configure-content-secrets.py --check
python3 scripts/configure-content-secrets.py
```

The uploader sends values to `gh secret set` on stdin and never prints them.
GitHub Actions needs `contents: write` on the production job and permission for its
bot to push generated content to `main`. Repository protection must permit this
workflow; the implementation never force-pushes or bypasses repository rules.

## Production release and recovery

The workflow serializes the complete production process. After checks pass it
deploys the API (including additive journal migrations), reconciles the live
publication manifest with the private journal, generates content, builds and
validates the static output, commits only the content directory, and publishes
that exact artifact to Cloudflare Pages. The original source SHA and content
commit are kept distinct. A `GITHUB_TOKEN` push does not trigger another workflow.
`npm run deploy:web` now dispatches this workflow against committed `main`, so a
manual release follows the same generation and publication checks. It does not
upload uncommitted local files or bypass the journal with a direct Pages upload.

Before a mutation or web publication, the workflow checks that `main` has not
advanced. An outdated source run stops rather than replacing a newer release.
Retries may adopt intervening content-only commits to reuse their checkpoints.
Already approved but unpublished pages consume the next five-page allowance
before any new inference occurs.

The journal is written through the existing SSH connection, using private
`python -m proxy.seo` commands in the API container. There is no public write API.
Publication is recorded only after the live manifest matches the build, every
article is in the sitemap, and new URLs return rendered articles. A failed build
or upload does not increase the published count. If publication succeeds but the
final journal write fails, the next run reconciles the live manifest first.
Workflow artifacts retain the baseline and generation report for diagnosis.

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
`docs/admin.md`). Local generation uses `uv run --project tools/seo --env-file .env
python -m seo_content generate --run-id <unique-id> --source-sha <git-sha>
--baseline <verified-publication.json> --report <local-report.json>`. Fetch the
current production manifest as the baseline; only an initial empty installation
uses an empty inventory. Do not treat a network error as an empty baseline.

Review an initial small generated batch in the browser and inspect its examples
and rendered HTML before shipping. Search performance is monitored independently;
passing structural and model checks does not promise indexing or rankings.

The initial two-page batch has also received manual editorial review. All six
examples were executed again after corrections, with fresh quality checks and a
new novelty comparison for the revised procurement scenario. The
[initial review record](initial-content-review.json) records the actual scores
and reviewed catalog hash. These local pilot runs are not production publications;
the production journal records a release only after deployment verification.
