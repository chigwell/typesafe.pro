# API Admission Operations

The path is Cloudflare -> nginx -> one FastAPI worker -> TypeSafe. nginx trusts
`CF-Connecting-IP` only from the published Cloudflare networks and overwrites
`X-Real-IP` / `X-Forwarded-For`. FastAPI trusts these headers from loopback and
Docker's private `172.16.0.0/12` bridge range. Direct callers cannot select their
identity with forwarding headers because port 8010 remains bound to loopback. For a
local non-Docker nginx, `TRUSTED_PROXY_CIDRS` defaults to loopback; do not set it
to `0.0.0.0/0`.

Cloudflare ranges were checked on 2026-09-21 against
[IPv4](https://www.cloudflare.com/ips-v4) and [IPv6](https://www.cloudflare.com/ips-v6).
Review these when maintaining the nginx configuration. Disable Cloudflare's
Pseudo IPv4 overwrite mode so anonymous IPv6 addresses remain distinct.

## Policies and Tokens

| Tier | Refill / minute | Burst | Queue deadline | Queue slots |
| --- | ---: | ---: | ---: | ---: |
| anonymous | 30 / IP | 5 | 3 s | 64 |
| free | 120 / token | 10 | 10 s | 128 |
| paid | 1000 / token | 20 | 30 s | 256 |

Change `rate_limit_policies` with SQL; changes apply within 30 seconds:

```sql
UPDATE rate_limit_policies SET rpm=60, burst=10 WHERE tier='anonymous';
```

Policies are refill rates, not strict rolling minute ceilings. Master limits
add strict rolling ceilings to their buckets. Each master must be dedicated to
this proxy; traffic using the same credential elsewhere is invisible to Redis.

Client credentials are HMAC-SHA256(`TOKEN_HASH_SECRET`, `token:<credential>`).
Only the digest is stored in `api_client_tokens`. Issue tokens on the server:

```sh
python -m proxy.tokens issue --tier paid --label customer-reference
python -m proxy.tokens revoke 123
```

Use the API virtualenv/container with its runtime environment. `issue` displays
the newly generated token once: do not capture its stdout in logs. Revocation,
tier changes and expiry take effect within 30 seconds (positive auth cache).
Unknown tokens are not cached, to avoid unbounded negative-cache cardinality.
`expires_at` and `revoked_at` are optional timestamptz columns. Legacy env tokens
are always free and are removed by changing env and restarting. Rotating
`TOKEN_HASH_SECRET` invalidates database tokens and changes hashed identities.

## Capacity and Memory

Upstream constants live in `proxy/config.py`: 1200 requests/minute/master,
250,000 tokens/second/master, 64,000 context and 32,000 state + longest question.
The upstream tokenizer is not published here. Input byte length plus 1024 is
recorded as a conservative estimate, but does not guarantee upstream token
counts. Scheduling reserves the full 64k documented per-request context in a
sliding one-second window. This intentionally permits three starts/second/key
(192k reserved tokens), even for small requests. Usage is recorded after the
response and never refunded into an already elapsed window. Context validation
remains upstream; the constants are not a substitute for its tokenizer.

Master selection and reservation are one Redis Lua operation, scored by in-flight
work and recent request/token utilization. Leases expire after the total upstream
timeout plus 10 seconds, so a process crash cannot hold capacity indefinitely.
Redis quotas persist across API restarts. Redis uses AOF every second and
`noeviction`: running out of memory returns 503 rather than evicting active quota
keys. A Redis data loss can reset recent quotas; stop traffic for a minute before
reopening after a restore that lost quota data. Upstream 429/529 and auth failures
temporarily cool down the selected master. Requests are not automatically retried.

Default API bounds:

- 512 admitted requests, including uploads, pending and active requests.
- 64 MiB request-body budget, charging twice the body size for conversion copies.
- 32 total upstream requests and 8 per master, held through stream completion.
- 10 MiB body limit; 60-second total upload timeout and 90-second total upstream timeout.
- 64 KiB response inspection capture per active request; bounded gzip/deflate decoding.
- 512 queued error events; batches of up to 64; five PostgreSQL connections.

Tune `QUEUE_MEMORY_BYTES`, `MAX_PENDING_REQUESTS`, `MAX_INFLIGHT_REQUESTS`,
`MASTER_MAX_INFLIGHT`, `REQUEST_TIMEOUT_SECONDS` in the runtime environment.
Changing concurrency does not change upstream quotas. Queues are strict priority,
FIFO within a tier; lower tiers can time out under sustained higher-tier load.
Pending disconnects are removed, active disconnects close upstream, and shutdown
does not replay queued requests. Redis contains metadata, not request bodies.

Container memory limits are API 512 MiB, PostgreSQL 256 MiB and Redis 192 MiB
(Redis data maxmemory 96 MiB). Budget additional RAM for the host/nginx and Docker.
Do not scale workers or replicas until the local body queues and priority scheduler
have a distributed design. Redis already makes quota reservations atomic.

## Diagnostics

Every API response includes a request ID. Accepted IDs contain 1-128 ASCII
letters, digits, underscores or hyphens; other IDs are replaced. Error rows
include hashed client/IP identity, method and path without query values, tier,
queue/upstream/total timings, selected master index, statuses, exception type,
sanitized message and stack function/line locations, estimated and actual usage,
and up to 8 KiB of sanitized response text. Request bodies, authorization headers
and raw credentials are not stored. Error responses can contain user content;
restrict database access accordingly.

`upstream_valid` is false for upstream HTTP errors or an invalid basic System One
response contract, true for a checked successful contract, and NULL when it was
not assessable (no response, unsupported encoding, capture limit or other route).
The original upstream status/body is returned even if validation finds a problem.
Compressed bytes remain unchanged in transit. Failures after headers terminate
the stream and are logged separately; a second HTTP status cannot be sent then.

Cleanup runs at startup and every minute, deleting expired events in batches of
2000. Retention is three days plus cleanup lag, not a PostgreSQL native TTL.
The job runs with the API, so cleanup resumes on restart after downtime. Size
database storage for the expected error rate and its bounded response captures.

If PostgreSQL is unavailable or the bounded event queue overflows, sanitized events
fall back to bounded Docker logs with `error_log_unavailable` / `error_log_overflow`.
They are not backfilled automatically. An in-memory queue cannot promise durable
delivery on process kill; use a durable external log sink if that becomes required.

Redis hashes `ts:metrics:<unix-minute>:all`, `:tier:<tier>` and `:master:<id>` contain
requests, upstream_requests, estimated_tokens, usage_tokens and status families.
Counters flush every 500 ms and expire after three days. Cardinality depends on
tiers/masters, never client IDs or IPs. Redis failures can lose the current metric
batch; they are reported with `metrics_unavailable` without retaining an unbounded
backlog. Query by known minute keys or `SCAN`, not production `KEYS`.

## Deploy and Verify

Configure GitHub secrets `POSTGRES_PASSWORD`, `TOKEN_HASH_SECRET` and
`TYPESAFE_MASTER_API_TOKEN_1`; the legacy test token is optional. Deployment
derives the internal PostgreSQL URL and URL-encodes the password. Keep the password
and hash secret stable across releases. The deployment creates separate mode-600 API
and Postgres env files so PostgreSQL does not receive master keys. Redis/Postgres
have no published host ports; named volumes survive API replacement and rollback.

Deployment starts data services, runs Alembic, then replaces the API. Migrations
must stay backward-compatible with the preceding API; rollback never downgrades
or deletes database contents. A failed initial migration can leave healthy data
services running, but does not replace the current API. Changing a password in
env does not rotate an existing PostgreSQL volume's role password.

CI uses disposable PostgreSQL/Redis services and mock upstream responses. Locally,
`pytest` starts isolated temporary instances when their binaries are available.
External `TEST_DATABASE_URL` / `TEST_REDIS_URL` must be dedicated test databases:
tests truncate tables and flush the selected Redis database. Public deployment
smoke makes up to three small billable calls (anonymous, unknown Bearer, legacy).
