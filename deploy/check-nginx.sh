#!/usr/bin/env bash
set -euo pipefail
directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=api.typesafe.pro \
    -keyout "$work/privkey.pem" -out "$work/fullchain.pem" >/dev/null 2>&1
docker run --rm --network none \
    -v "$directory/nginx/api.typesafe.pro.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$work:/etc/letsencrypt/live/api.typesafe.pro:ro" \
    nginx:1.28.0-bookworm nginx -t
