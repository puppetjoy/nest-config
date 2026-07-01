#!/bin/sh
# Smoke-test the Camofox Browser service far enough to catch browser-context
# protocol skew.  A server that only passes /health can still fail every tab
# creation with Browser.setDefaultViewport viewport schema errors.

set -eu

log_path="${1:-/tmp/nest-camofox-smoke.log}"
health_path='/tmp/nest-camofox-health.json'
tab_path='/tmp/nest-camofox-tab.json'
mobile_tab_path='/tmp/nest-camofox-mobile-tab.json'
mobile_eval_path='/tmp/nest-camofox-mobile-eval.json'
port="${CAMOFOX_PORT:-9377}"
ready=0

export CAMOFOX_SCREEN_WIDTH="${CAMOFOX_SCREEN_WIDTH:-1365}"
export CAMOFOX_SCREEN_HEIGHT="${CAMOFOX_SCREEN_HEIGHT:-768}"
export CAMOFOX_CONTEXT_CLOSE_TIMEOUT_MS="${CAMOFOX_CONTEXT_CLOSE_TIMEOUT_MS:-10000}"

rm -f "$log_path" "$health_path" "$tab_path" "$mobile_tab_path" "$mobile_eval_path"

command -v camofox-browser >/dev/null
command -v node >/dev/null

nest-camofox-browser >"$log_path" 2>&1 &
server_pid=$!

cleanup() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _attempt in $(seq 1 30); do
  if curl --fail --silent --show-error "http://127.0.0.1:${port}/health" >"$health_path"; then
    ready=1
    break
  fi

  if ! kill -0 "$server_pid" 2>/dev/null; then
    cat "$log_path" >&2 || true
    echo 'Camofox Browser exited before /health was ready' >&2
    exit 1
  fi

  sleep 1
done

if [ "$ready" -ne 1 ]; then
  cat "$log_path" >&2 || true
  echo 'Camofox Browser did not become healthy' >&2
  exit 1
fi

http_code=$(curl --silent --show-error \
  --output "$tab_path" \
  --write-out '%{http_code}' \
  --request POST "http://127.0.0.1:${port}/tabs" \
  --header 'Content-Type: application/json' \
  --data '{"userId":"nest-build-smoke","sessionKey":"viewport-context","url":"https://example.com"}')

cat "$tab_path"
echo

case "$http_code" in
  2*) ;;
  *)
    cat "$log_path" >&2 || true
    echo "Camofox Browser POST /tabs smoke failed with HTTP ${http_code}" >&2
    exit 1
    ;;
esac

if ! grep --extended-regexp '"(id|tabId|tabs|snapshot|url)"' "$tab_path" >/dev/null; then
  echo 'Camofox Browser POST /tabs returned an unexpected response shape' >&2
  exit 1
fi

echo 'Camofox Browser POST /tabs smoke passed'

mobile_http_code=$(curl --silent --show-error \
  --output "$mobile_tab_path" \
  --write-out '%{http_code}' \
  --request POST "http://127.0.0.1:${port}/tabs" \
  --header 'Content-Type: application/json' \
  --data '{"userId":"nest-build-smoke-mobile","sessionKey":"viewport-context","url":"https://example.com","viewport":{"width":390,"height":844}}')

case "$mobile_http_code" in
  2*) ;;
  *)
    cat "$log_path" >&2 || true
    echo "Camofox Browser mobile POST /tabs smoke failed with HTTP ${mobile_http_code}" >&2
    exit 1
    ;;
esac

mobile_tab_id=$(node -e "const fs=require('node:fs'); const data=JSON.parse(fs.readFileSync(process.argv[1], 'utf8')); const id=data.tabId || data.id; if (!id) process.exit(1); console.log(id);" "$mobile_tab_path")

mobile_eval_code=$(curl --silent --show-error \
  --output "$mobile_eval_path" \
  --write-out '%{http_code}' \
  --request POST "http://127.0.0.1:${port}/tabs/${mobile_tab_id}/evaluate" \
  --header 'Content-Type: application/json' \
  --data '{"userId":"nest-build-smoke-mobile","expression":"({innerWidth,innerHeight,screenWidth:screen.width,screenHeight:screen.height,clientWidth:document.documentElement.clientWidth,clientHeight:document.documentElement.clientHeight})"}')

case "$mobile_eval_code" in
  2*) ;;
  *)
    cat "$log_path" >&2 || true
    echo "Camofox Browser mobile evaluate smoke failed with HTTP ${mobile_eval_code}" >&2
    exit 1
    ;;
esac

node - "$mobile_eval_path" <<'JS'
const fs = require('node:fs');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const result = payload.result || {};
const expected = { innerWidth: 390, innerHeight: 844, screenWidth: 390, screenHeight: 844, clientWidth: 390, clientHeight: 844 };
const mismatches = Object.entries(expected).filter(([key, value]) => result[key] !== value);
if (mismatches.length) {
  console.error('Camofox mobile viewport metrics did not match requested viewport');
  console.error(JSON.stringify({ expected, actual: result, mismatches }, null, 2));
  process.exit(1);
}
JS

curl --silent --show-error --max-time 20 \
  --request DELETE "http://127.0.0.1:${port}/sessions/nest-build-smoke-mobile" \
  >/dev/null

echo 'Camofox Browser mobile viewport smoke passed'
