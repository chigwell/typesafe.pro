#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT=/opt/typesafe-proxy
current=$(readlink -f "$ROOT/current")
python3 "$current/deploy/smoke.py" --base-url https://api.typesafe.pro \
    --release "$(basename "$current" | cut -d. -f1)"
backup=$(mktemp -d "$ROOT/backups/legacy.XXXXXX")
cp -a /etc/nginx/sites-available "$backup/"
cp -a /etc/nginx/sites-enabled "$backup/"
if docker container inspect hermes-factory-app >/dev/null 2>&1; then
    docker inspect hermes-factory-app > "$backup/hermes-container.json"
    docker update --restart=no hermes-factory-app
    docker stop hermes-factory-app
fi
if systemctl cat ollama.service > "$backup/ollama.service" 2>/dev/null; then
    systemctl disable --now ollama.service
fi
rm -f /etc/nginx/sites-enabled/hermes-factory
nginx -t
systemctl reload nginx
echo "Legacy services stopped; configuration saved in $backup; volumes retained"
