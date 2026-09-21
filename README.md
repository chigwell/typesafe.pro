# typesafe.pro

Cloudflare Pages landing page for `typesafe.pro` plus a small Cloudflare Worker API for `api.typesafe.pro`.

## Structure

- `apps/web` contains a static hello-world landing page deployed with Cloudflare Pages Direct Upload.
- `apps/api` contains the `typesafe-pro-api` Worker deployed to the `api.typesafe.pro` custom domain.
- `scripts/cf-env.sh` maps the local `.env` keys to the environment variables expected by Wrangler.

## Local Setup

Create `.env` from `.env.example` and fill in the Cloudflare values:

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

Run the API Worker:

```sh
npm run dev:api
```

Check and test the Worker:

```sh
npm run check
npm test
```

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

Deploy the API Worker:

```sh
npm run deploy:api
```

The Worker config uses a Custom Domain route for `api.typesafe.pro`, so Wrangler should create the Worker domain during deployment.

## CI Deploys

Pushes to `main` run `.github/workflows/deploy.yml`.

The workflow:

1. Installs dependencies with `npm ci`.
2. Runs `npm run check`.
3. Runs `npm test`.
4. Ensures the `typesafe-pro` Pages project exists.
5. Deploys the Pages landing page.
6. Deploys the `typesafe-pro-api` Worker.

Add these GitHub Actions secrets in `https://github.com/chigwell/typesafe.pro/settings/secrets/actions`:

- `CF_ACCOUNT_ID`
- `CF_API_TOKEN`

The workflow also accepts `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` if you prefer Cloudflare's standard names.

## Smoke Checks

```sh
curl https://typesafe.pro/
curl https://api.typesafe.pro/
curl https://api.typesafe.pro/health
```

Expected API root response:

```json
{
  "ok": true,
  "message": "Hello from api.typesafe.pro",
  "service": "typesafe-pro-api"
}
```

## Cloudflare Notes

The local credentials were checked without printing secret values:

- required `.env` keys are present
- the account and `typesafe.pro` zone are readable
- R2 S3 credentials can list visible buckets

One caveat: Cloudflare's token self-verify endpoint returned `Invalid API Token`, even though the same bearer value could read the account and zone. Run a Wrangler command before the first deployment to confirm the token works for deploy operations in this project.
