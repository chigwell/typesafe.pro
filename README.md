# typesafe.pro

Cloudflare Pages hosts `typesafe.pro`. The API runs on the VPS at `87.106.199.191`:

```text
client -> api.typesafe.pro -> Cloudflare -> nginx -> FastAPI -> api.typesafe.ai
```

GitHub Actions connects directly to the VPS over SSH. Cloudflare is only DNS/TLS
proxying for the API, not the API host or deployment transport.

## Structure

- `apps/web` contains a static hello-world landing page deployed with Cloudflare Pages Direct Upload.
- `apps/api` contains the Python proxy, its dependency lockfile, tests and Dockerfile.
- `deploy` contains nginx, Docker Compose, deployment, rollback and smoke checks.
- `scripts/cf-env.sh` maps the local `.env` keys to the environment variables expected by Wrangler.

## Local Setup

Create `.env` from `.env.example` and fill in the server-side credentials:

```sh
cp .env.example .env
```

Wrangler expects `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`; this project keeps the shorter local names and maps them at command time:

- `CF_ACCOUNT_ID`
- `CF_API_TOKEN`
- `CF_ACCESS_KEY_ID`
- `CF_SECRET_ACCESS_KEY`
- `CF_S3_API_ENDPOINT`

Install dependencies:

```sh
npm install
```

## Development

Run the static Pages app:

```sh
npm run dev:web
```

Install Python 3.12 and uv 0.6.8, then install the locked API dependencies:

```sh
uv sync --project apps/api --frozen
```

Run the API at `http://127.0.0.1:8010` using the token pairs from `.env`:

```sh
npm run dev:api
```

Check and test the proxy (tests use a mock upstream and incur no API charges):

```sh
npm run check
npm test
```

## Proxy Contract

Use `https://api.typesafe.pro` as your TypeSafe base URL and send your client key
in `Authorization: Bearer <TYPESAFE_TEST_API_TOKEN_1>`. A valid key is replaced
server-side with `TYPESAFE_MASTER_API_TOKEN_1`. Neither key belongs in public web
assets, request URLs, git history, or Docker images.

- Missing, invalid or duplicate Authorization: `401`, without an upstream request.
- Rate limit: per client key, 60 requests/minute refill, bucket capacity 10;
  excess requests return `429` with `Retry-After`. One ASGI worker is intentional:
  in-memory counters reset on restart. Use shared storage before adding workers.
- Method, raw path/query, body, response status, repeated end-to-end headers and
  compressed response bytes are forwarded. Hop-by-hop headers are removed;
  upstream Host and Authorization are replaced. No automatic retries, redirects
  or shared client cookies are sent upstream.
- Only `GET /health` bypasses authentication. It returns `ok`, `service` and the
  deployed commit in `release`; no upstream call is made.
- Requests are limited to 10 MiB. Connect timeout is 5 seconds; upstream read and
  write timeouts are 60 seconds. Transport errors return `502`, timeouts `504`.
  Errors after streaming response headers are sent terminate the stream.
- Access logs contain method, status and timing only. nginx request error logs
  and Uvicorn access logs are disabled to avoid logging URLs or credentials.
- Additional pairs use matching `_2`, `_3`, etc. Client keys must be unique and
  different from all master keys; incomplete pairs prevent startup. To deploy a
  new pair, add both GitHub secrets and map them into the deploy job environment.
- Browser CORS preflights are not bypassed; this v1 is a server-to-server API.

The request payload follows the [TypeSafe API reference](https://docs.typesafe.ai/api).

## Deploy

Create the Pages project once:

```sh
npm run cf:pages:create
```

Or let CI create it idempotently:

```sh
npm run cf:pages:ensure
```

Deploy the web app:

```sh
npm run deploy:web
```

After the first Pages deployment, add `typesafe.pro` as a custom domain in Cloudflare Pages:

1. Open Workers & Pages in the Cloudflare dashboard.
2. Select the `typesafe-pro` Pages project.
3. Go to Custom domains.
4. Add `typesafe.pro`.

The API deploys through the main-branch workflow described below.

## CI Deploys

PRs run lint, tests, shell checks and a Docker build. Pushes to `main` and manual
runs on `main` deploy after those checks. Web and API deploy in independent jobs;
API deploys are serialized and are never cancelled by a newer push.

The API job archives the exact commit, uploads it and a separate `600` env file
over SSH, builds a SHA-tagged image on the VPS, tests nginx, starts the container,
checks health, reloads nginx, then verifies public authentication and one small
real TypeSafe request. That final check uses a small amount of upstream quota.

Releases live in `/opt/typesafe-proxy/releases/<sha>.<deployment-id>`; the `current`
symlink is promoted only after successful verification. Each release retains its
own private `runtime.env` for rollback. Failed activation restores the preceding
image, environment and nginx config. Builds happen before the old container is
replaced; container restarts cause a brief interruption. Releases and backups are
retained, so monitor disk usage and prune old releases deliberately.

GitHub Actions secrets in [repository settings](https://github.com/chigwell/typesafe.pro/settings/secrets/actions):

- `CF_ACCOUNT_ID`
- `CF_API_TOKEN`
- `SSH_HOST`: `87.106.199.191`
- `SSH_USER`: deployment SSH account (`root` for this VPS)
- `SSH_PRIVATE_KEY`: dedicated Ed25519 private key; public half in VPS authorized_keys
- `SSH_KNOWN_HOSTS`: pinned VPS SSH host public key, verified through existing access
- `TYPESAFE_TEST_API_TOKEN_1`
- `TYPESAFE_MASTER_API_TOKEN_1`

`SSH_PASS` is only for one-time bootstrap and is not stored in GitHub. The deploy
job does not need Cloudflare credentials. Repository variables
`RATE_LIMIT_PER_MINUTE` and `RATE_LIMIT_BURST` override the defaults of 60 and 10
on the next deploy without a Python change.

The workflow also accepts `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` if you prefer Cloudflare's standard names.

## One-Time VPS Setup

The server needs nginx, Docker with Compose supporting raw env files (2.30+),
Python 3, curl and certbot. Copy the repository's `deploy` directory to the VPS
and run `bash deploy/bootstrap.sh` as root. This backs up nginx, installs the
HTTP ACME challenge site, obtains a certificate and enables the renewal timer.
The normal CI deployment then installs the HTTPS site and starts the API.

Keep the proxied DNS A record for `api.typesafe.pro` pointing at the VPS. Remove
any Worker custom domain/routes for this hostname, use Full (strict) TLS after
the HTTPS site is active, and bypass edge caching for this API hostname.

After the first successful deployment, run
`bash /opt/typesafe-proxy/current/deploy/retire-legacy.sh` on the VPS. It verifies
the new API, backs up legacy config, stops Hermes and disables its Docker restart
policy, disables Ollama, and unlinks the Hermes nginx site. Data/volumes remain.

To exercise a real failed deployment and rollback, prepare a fresh incoming
archive/env using the normal upload layout, then run its `deploy/deploy.sh <sha>`
with `DEPLOY_TEST_FAIL_AFTER_START=1`. It must exit nonzero, print `Rollback
complete`, and leave `/health` and `current` on the previous healthy release.
This check deliberately restarts the container; do not schedule it routinely.

## Smoke Checks

```sh
curl https://typesafe.pro/
curl https://api.typesafe.pro/health
curl --resolve api.typesafe.pro:443:87.106.199.191 https://api.typesafe.pro/health
```

Expected health response:

```json
{
  "ok": true,
  "service": "typesafe-proxy",
  "release": "<commit-sha>"
}
```

`python3 deploy/smoke.py --base-url https://api.typesafe.pro --release <sha>`
checks health and rejection of missing/wrong keys without a paid upstream call.
On the VPS, add `--env-file /opt/typesafe-proxy/current/runtime.env` for the small
live upstream check. The command never prints keys or upstream response bodies.
