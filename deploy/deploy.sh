#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
sha=${1:?Commit SHA required}
[[ $sha =~ ^[a-f0-9]{40}$ ]] || exit 2
ROOT=/opt/typesafe-proxy
incoming=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
exec 9>"$ROOT/deploy.lock"
flock -w 300 9
release=$(mktemp -d "$ROOT/releases/$sha.XXXXXX")
backup=$(mktemp -d "$ROOT/backups/deploy.XXXXXX")
previous=$(readlink -f "$ROOT/current" || true)
site=/etc/nginx/sites-available/api.typesafe.pro
enabled=/etc/nginx/sites-enabled/api.typesafe.pro
activated=0
nginx_changed=0

compose() {
    local directory=$1
    shift
    local id
    id=$(basename "$directory")
    RELEASE_ID=$id RELEASE_SHA=${id%%.*} PROXY_ENV_FILE="$directory/runtime.env" \
        docker compose -p typesafe-proxy -f "$directory/deploy/compose.yml" "$@"
}

rollback() {
    trap - ERR INT TERM HUP
    set +e
    echo "Deployment failed; restoring previous release" >&2
    local failed=0
    if [[ $nginx_changed == 1 ]]; then
        if [[ -f $backup/site.conf ]]; then
            install -m 644 "$backup/site.conf" "$site"
        else
            rm -f "$site"
        fi
        rm -f "$enabled"
        if [[ -e $backup/enabled || -L $backup/enabled ]]; then
            cp -a "$backup/enabled" "$enabled"
        fi
        nginx -t && systemctl reload nginx || failed=1
    fi
    if [[ $activated == 1 ]]; then
        if [[ -n $previous && -f $previous/deploy/compose.yml ]]; then
            compose "$previous" up -d --no-build --wait --wait-timeout 75 || failed=1
            python3 "$previous/deploy/smoke.py" --base-url http://127.0.0.1:8010 \
                --release "$(basename "$previous" | cut -d. -f1)" || failed=1
        else
            compose "$release" down || failed=1
        fi
    fi
    if [[ $failed == 0 ]]; then
        echo "Rollback complete" >&2
    else
        echo "Rollback failed; inspect the VPS" >&2
    fi
    exit 1
}
trap rollback ERR INT TERM HUP

tar -xzf "$incoming/release.tar.gz" -C "$release"
install -m 600 "$incoming/runtime.env" "$release/runtime.env"
[[ ! -f $site ]] || cp -a "$site" "$backup/site.conf"
if [[ -e $enabled || -L $enabled ]]; then
    cp -a "$enabled" "$backup/enabled"
fi
compose "$release" build
# Validate the candidate before interrupting the running container.
printf 'events {}\nhttp { include %s/deploy/nginx/api.typesafe.pro.conf; }\n' "$release" > "$release/nginx-check.conf"
nginx -t -c "$release/nginx-check.conf"
activated=1
compose "$release" up -d --no-build --wait --wait-timeout 75
python3 "$release/deploy/smoke.py" --base-url http://127.0.0.1:8010 --release "$sha"
nginx_changed=1
install -m 644 "$release/deploy/nginx/api.typesafe.pro.conf" "$site"
ln -sfn "$site" "$enabled"
nginx -t
systemctl reload nginx
if [[ ${DEPLOY_TEST_FAIL_AFTER_START:-0} == 1 ]]; then
    echo "Injecting a failed verification to exercise rollback" >&2
    false
fi
curl --fail --silent --show-error --resolve api.typesafe.pro:443:127.0.0.1 \
    --max-time 15 https://api.typesafe.pro/health > /dev/null
python3 "$release/deploy/smoke.py" --base-url https://api.typesafe.pro \
    --release "$sha" --env-file "$release/runtime.env"
if [[ -n $previous && -d $previous ]]; then
    ln -sfn "$previous" "$ROOT/previous"
fi
ln -sfn "$release" "$ROOT/current.next"
mv -Tf "$ROOT/current.next" "$ROOT/current"
trap - ERR INT TERM HUP
rm -f "$incoming/runtime.env"
echo "Deployed $sha"
