#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATH="${ROOT_DIR}/node_modules/.bin:${PATH}"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

CF_ACCOUNT_ID="${CF_ACCOUNT_ID:-${CLOUDFLARE_ACCOUNT_ID:-}}"
CF_API_TOKEN="${CF_API_TOKEN:-${CLOUDFLARE_API_TOKEN:-}}"

if [[ -z "${CF_ACCOUNT_ID:-}" ]]; then
  echo "Missing CF_ACCOUNT_ID or CLOUDFLARE_ACCOUNT_ID in .env or environment" >&2
  exit 1
fi

if [[ -z "${CF_API_TOKEN:-}" ]]; then
  echo "Missing CF_API_TOKEN or CLOUDFLARE_API_TOKEN in .env or environment" >&2
  exit 1
fi

export CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-${CF_ACCOUNT_ID}}"
export CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-${CF_API_TOKEN}}"
export WRANGLER_LOG_PATH="${WRANGLER_LOG_PATH:-${ROOT_DIR}/.wrangler/logs}"

mkdir -p "${WRANGLER_LOG_PATH}"

exec "$@"
