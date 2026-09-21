#!/bin/sh
set -eu

# Sends real anonymous requests to the production gateway.
# Defaults are chosen to exceed the documented anonymous burst limit.

URL=${URL:-https://api.typesafe.pro/v1/systemone}
REQUESTS=${REQUESTS:-12}
CONCURRENCY=${CONCURRENCY:-12}
APPROX_TOKENS=${APPROX_TOKENS:-24}
TIMEOUT=${TIMEOUT:-45}
KEEP=${KEEP:-0}

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

case "$REQUESTS:$CONCURRENCY:$APPROX_TOKENS:$TIMEOUT" in
  *[!0-9:]* | *::* | :* | *:)
    echo "REQUESTS, CONCURRENCY, APPROX_TOKENS and TIMEOUT must be positive integers" >&2
    exit 1
    ;;
esac

if [ "$REQUESTS" -lt 1 ] || [ "$CONCURRENCY" -lt 1 ] || [ "$APPROX_TOKENS" -lt 1 ] || [ "$TIMEOUT" -lt 1 ]; then
  echo "REQUESTS, CONCURRENCY, APPROX_TOKENS and TIMEOUT must be positive integers" >&2
  exit 1
fi

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/typesafe-prod-rl.XXXXXX")
cleanup() {
  if [ "$KEEP" = "1" ]; then
    echo "kept raw responses in $tmp_dir" >&2
  else
    rm -rf "$tmp_dir"
  fi
}
trap cleanup EXIT INT TERM

run_id="anonrl-$(date +%Y%m%d%H%M%S)-$$"

make_state() {
  request_no=$1
  i=1
  printf 'anonymous production rate-limit probe %s request %s. ' "$run_id" "$request_no"
  while [ "$i" -le "$APPROX_TOKENS" ]; do
    printf 'probe '
    i=$((i + 1))
  done
}

make_payload() {
  request_no=$1
  state=$(make_state "$request_no")
  printf '{"model":"jev-latest","state":"%s","questions":{"is_probe":{"type":"noul","instructions":"Is this text a harmless API rate-limit probe?"}}}\n' "$state"
}

json_number() {
  key=$1
  file=$2
  if command -v jq >/dev/null 2>&1; then
    jq -r "$key // \"\"" "$file" 2>/dev/null || true
  else
    field=$(printf '%s\n' "$key" | awk -F . '{print $NF}')
    sed -n "s/.*\"$field\"[[:space:]]*:[[:space:]]*\\([0-9][0-9]*\\).*/\\1/p" "$file" | head -n 1
  fi
}

json_error() {
  file=$1
  if command -v jq >/dev/null 2>&1; then
    jq -r '.error // ""' "$file" 2>/dev/null || true
  else
    sed -n 's/.*"error"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$file" | head -n 1
  fi
}

header_value() {
  name=$1
  file=$2
  awk -F ': *' -v wanted="$name" '
    tolower($1) == tolower(wanted) {
      value = $2
      gsub(/\r/, "", value)
      print value
    }
  ' "$file" | tail -n 1
}

run_one() {
  request_no=$1
  payload="$tmp_dir/payload-$request_no.json"
  headers="$tmp_dir/headers-$request_no.txt"
  body="$tmp_dir/body-$request_no.json"
  err="$tmp_dir/curl-$request_no.err"
  meta="$tmp_dir/meta-$request_no.tsv"

  make_payload "$request_no" > "$payload"
  : > "$headers"
  : > "$body"
  : > "$err"
  bytes=$(wc -c < "$payload" | tr -d ' ')
  curl_rc=0
  curl_meta=$(
    curl "$URL" \
      --silent \
      --show-error \
      --request POST \
      --connect-timeout 10 \
      --max-time "$TIMEOUT" \
      --header 'Content-Type: application/json' \
      --header "X-Request-ID: $run_id-$request_no" \
      --dump-header "$headers" \
      --output "$body" \
      --write-out '%{http_code}\t%{time_total}\t%{size_download}' \
      --data-binary "@$payload" \
      2>"$err"
  ) || curl_rc=$?

  status=$(printf '%s' "$curl_meta" | awk -F '\t' '{print $1}')
  seconds=$(printf '%s' "$curl_meta" | awk -F '\t' '{print $2}')
  downloaded=$(printf '%s' "$curl_meta" | awk -F '\t' '{print $3}')
  retry_after=$(header_value "retry-after" "$headers")
  request_id=$(header_value "x-request-id" "$headers")
  input_tokens=$(json_number ".usage.input_tokens" "$body")
  output_tokens=$(json_number ".usage.output_tokens" "$body")
  error_code=$(json_error "$body")

  if [ -s "$err" ]; then
    error_code="${error_code:-$(tr '\n' ' ' < "$err" | sed 's/[[:space:]]*$//')}"
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$request_no" "${status:-000}" "$curl_rc" "${seconds:-0}" "$bytes" "${downloaded:-0}" \
    "$retry_after" "$request_id" "$input_tokens" "$output_tokens" "$error_code" > "$meta"
}

echo "Target: $URL"
echo "Mode: anonymous, no Authorization header"
echo "Requests: $REQUESTS total, $CONCURRENCY concurrent, approx $APPROX_TOKENS repeated state tokens/request"
echo

request_no=1
active=0
while [ "$request_no" -le "$REQUESTS" ]; do
  run_one "$request_no" &
  active=$((active + 1))
  request_no=$((request_no + 1))

  if [ "$active" -ge "$CONCURRENCY" ]; then
    wait
    active=0
  fi
done
wait

all="$tmp_dir/all.tsv"
sort -n "$tmp_dir"/meta-*.tsv > "$all"

printf '%-4s %-6s %-7s %-8s %-7s %-7s %-11s %-20s %-8s %-8s %s\n' \
  "#" "HTTP" "curl" "seconds" "sent" "recv" "retry-after" "x-request-id" "input" "output" "error"
awk -F '\t' '{
  printf "%-4s %-6s %-7s %-8s %-7s %-7s %-11s %-20s %-8s %-8s %s\n",
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
}' "$all"

echo
echo "Summary:"
awk -F '\t' '
  {
    total += 1
    statuses[$2] += 1
    if ($2 >= 200 && $2 < 300) ok += 1
    if ($2 == 429) limited += 1
    if ($9 != "") input += $9
    if ($10 != "") output += $10
    sent += $5
  }
  END {
    printf "  total_requests=%d\n", total
    printf "  successful_2xx=%d\n", ok
    printf "  rate_limited_429=%d\n", limited
    printf "  request_body_bytes_sent=%d\n", sent
    printf "  reported_input_tokens_on_success=%d\n", input
    printf "  reported_output_tokens_on_success=%d\n", output
    printf "  statuses="
    first = 1
    for (status in statuses) {
      if (!first) printf ","
      printf "%s:%d", status, statuses[status]
      first = 0
    }
    printf "\n"
  }
' "$all"

cat <<'EOF'

Notes:
  - Anonymous limits are per visible client IP. VPNs, shared NATs, or other tests from the same IP affect results.
  - The gateway currently rate-limits anonymous clients by request count; token totals come from successful upstream responses.
  - 429 responses should include Retry-After. 503/504 usually indicate queue/upstream pressure rather than the anonymous request bucket.
  - Set KEEP=1 to inspect raw payloads, headers, and bodies after the run.
EOF
