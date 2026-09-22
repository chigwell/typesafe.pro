# Admin observability

The static frontend is served at `https://typesafe.pro/admin`. Data and login live
at `https://api.typesafe.pro/admin/api`. No admin credential is bundled into Next.js.
All data endpoints require a signed, host-only HttpOnly/Secure cookie. Sessions
expire after eight hours; changing the password invalidates existing sessions.
Logout clears the browser cookie. The dashboard has no user-management actions.

## Password and deployment

`python3 scripts/configure-admin-secret.py` generates a 64-character password
with `secrets.token_urlsafe(48)` if one is not already present, writes it to the
ignored root `.env` with mode `0600`, then sends it on stdin to GitHub CLI for
the `ADMIN_PASSWORD` Actions secret in `chigwell/typesafe.pro`. It never prints
the value. Re-running reuses the existing local password. `--local-only` skips
the GitHub write. Read `ADMIN_PASSWORD` in your local `.env` to sign in.

The deploy workflow passes the secret to `deploy/write_env.py`, which requires
32-256 printable ASCII characters and writes the private API runtime environment.
It must never be named `NEXT_PUBLIC_ADMIN_PASSWORD`. Deploy runs the additive
`0002_observability` migration before starting the new API. Existing error rows
remain available with a null real IP.

`ADMIN_PASSWORD` is only for the `/admin` dashboard login. Trusted incoming
programmatic API access uses separate server-only `TYPESAFE_ADMIN_API_TOKEN_N`
values documented in `docs/admission.md`.

| Setting | Default |
| --- | --- |
| `ADMIN_PASSWORD` | Required |
| `ADMIN_SESSION_TTL_SECONDS` | `28800` |
| `ADMIN_LOGIN_MAX_ATTEMPTS` | `5` |
| `ADMIN_LOGIN_WINDOW_SECONDS` | `900` |
| `ADMIN_ALLOWED_ORIGINS` | `https://typesafe.pro` |
| `OBSERVABILITY_RETENTION_SECONDS` | `604800` |

Origins are exact and comma-separated; wildcard origins are rejected. Public
proxy CORS stays unchanged. The admin API rejects foreign browser origins,
including sibling subdomains, and uses SameSite=Strict cookies. Login reserves an
attempt atomically in Redis before checking the password, clears attempts on a
successful login, and returns 429 with Retry-After after the limit. It returns
503 when Redis is unavailable. IPs use the existing trusted-proxy boundary:
nginx overwrites forwarding headers after resolving the Cloudflare client IP.
Keep the API bound to loopback and do not trust forwarded IPs from arbitrary peers.

## Metrics and retention

Windows (`5m`, `1h`, `24h`, `7d`) include the current partial minute and are aligned
to one-minute buckets. Hourly rollups accelerate longer windows without double
counting minute buckets. Counts are best effort, flushed every half second and
cached for ten seconds for admin reads. The UI refreshes every ten seconds.
IP rows sort by descending request count, with Redis's lexical tie-break order.
Pages share a short-lived snapshot; active traffic can change ordering between
refreshes. Error pages use newest-first creation time and ID order.

Counts cover completed public proxy requests, including rejected and disconnected
requests. Health checks and admin requests are excluded. Invalid upstream responses
count as errors even with HTTP 200. Missing upstream token usage is counted
separately from reported usage; estimated tokens are an independent counter.
Master key IDs are shown, never key values. CPU/RAM samples are collected every
five seconds and the last five minutes are held in memory; history restarts on deploy.

Real IP activity expires with the Redis buckets within seven days. Postgres
cleanup deletes old errors in batches; read queries also enforce the retention
cutoff. Request bodies are not stored. Error response excerpts are limited to
8 KiB and redacted before storage and again before display. Path dimensions are
sanitized and bounded to 100 distinct paths per process, with overflow grouped
as `[other paths]`. IP cardinality is not capped across the retention window,
but in-process batches are bounded. When shared Redis reaches 70% of maxmemory,
new activity writes are skipped to preserve admission headroom. Dropped telemetry
is shown in the dashboard; metrics must not be used for billing.

The container receives read-only mounts of host `/proc/stat`, `/proc/meminfo`, and
`/proc/loadavg`. `statvfs` on a read-only bind of host `/etc/hostname` measures the
filesystem holding that host file (normally the VPS root filesystem). No Docker
socket or host root directory is exposed. Missing probes produce null metrics and
partial status, never invented zero values. The Redis/Postgres probes and queue
state are independent of those host measurements.

## Verification

Run the existing API ruff/pytest checks and web vitest/build checks. On macOS,
use a short pytest directory to satisfy Unix socket path limits:

```sh
PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH" uv run --project apps/api pytest apps/api/tests --basetemp=/private/tmp/typesafe-api-tests
npm run test --workspace @typesafe-pro/web
npm run build --workspace @typesafe-pro/web
```

For local full-stack browser testing, use trusted local HTTPS with the frontend
and API on the same site, point `NEXT_PUBLIC_TYPESAFE_API_BASE` at the local API,
and include the frontend origin in `ADMIN_ALLOWED_ORIGINS`. Secure/Strict cookies
are deliberately not relaxed for development. The frontend can be inspected with
`npm run dev:web -- --port 3080` without exposing production credentials.
