#!/bin/sh
# Smoke-test the Camofox Browser service far enough to catch browser-context
# protocol skew.  A server that only passes /health can still fail every tab
# creation with Browser.setDefaultViewport viewport schema errors.

set -eu

log_path="${1:-/tmp/nest-camofox-smoke.log}"
health_path='/tmp/nest-camofox-health.json'
tab_path='/tmp/nest-camofox-tab.json'
port="${CAMOFOX_PORT:-9377}"
ready=0

rm -f "$log_path" "$health_path" "$tab_path"

command -v camofox-browser >/dev/null

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
