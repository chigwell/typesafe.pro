#!/usr/bin/env bash
set -euo pipefail
umask 077
DEPLOY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=/opt/typesafe-proxy
install -d -m 700 "$ROOT" "$ROOT/releases" "$ROOT/incoming" "$ROOT/backups"
backup=$(mktemp -d "$ROOT/backups/bootstrap.XXXXXX")
tar -czf "$backup/nginx.tar.gz" -C /etc nginx
docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}' > "$backup/containers.txt"
install -d -m 755 /var/www/letsencrypt
if [[ ! -f /etc/letsencrypt/live/api.typesafe.pro/fullchain.pem ]]; then
    install -m 644 "$DEPLOY_DIR/nginx/bootstrap.conf" /etc/nginx/sites-available/api.typesafe.pro
    ln -sfn /etc/nginx/sites-available/api.typesafe.pro /etc/nginx/sites-enabled/api.typesafe.pro
    nginx -t
    systemctl reload nginx
    certbot certonly --webroot -w /var/www/letsencrypt -d api.typesafe.pro \
        --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring
fi
install -m 755 "$DEPLOY_DIR/renew-nginx.sh" /etc/letsencrypt/renewal-hooks/deploy/typesafe-nginx
systemctl enable --now certbot.timer
echo "Bootstrap complete; original configuration saved in $backup"
