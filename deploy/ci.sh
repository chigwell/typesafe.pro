#!/usr/bin/env bash
set -euo pipefail
umask 077
sha=${GITHUB_SHA:?GITHUB_SHA required}
[[ $sha =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ ${SSH_HOST:?} =~ ^[a-zA-Z0-9.-]+$ ]] || exit 2
[[ ${SSH_USER:?} =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 2
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
printf '%s\n' "${SSH_PRIVATE_KEY:?}" > "$work/key"
printf '%s\n' "${SSH_KNOWN_HOSTS:?}" > "$work/known_hosts"
python3 deploy/write_env.py "$work/runtime.env"
git archive --format=tar.gz "$sha" apps/api deploy > "$work/release.tar.gz"
target="$SSH_USER@$SSH_HOST"
options=(-i "$work/key" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=$work/known_hosts" -o ConnectTimeout=15
    -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
incoming="/opt/typesafe-proxy/incoming/$sha-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
# The path contains only the validated SHA and GitHub's numeric run identifiers.
# shellcheck disable=SC2029
ssh "${options[@]}" "$target" "install -d -m 700 '$incoming'"
scp "${options[@]}" "$work/release.tar.gz" "$work/runtime.env" "$work/postgres.env" "$target:$incoming/"
# shellcheck disable=SC2029
ssh "${options[@]}" "$target" \
    "tar -xzf '$incoming/release.tar.gz' -C '$incoming' && bash '$incoming/deploy/deploy.sh' '$sha'"
