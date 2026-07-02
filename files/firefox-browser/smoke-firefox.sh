#!/bin/sh
set -eu

export DISPLAY="${DISPLAY:-:97}"
export HOME="${HOME:-/tmp/nest-firefox-smoke-home}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/nest-firefox-smoke-runtime}"
mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR" || true

xvfb_pid=
firefox_pid=

Xvfb "$DISPLAY" -screen 0 1024x768x24 -nolisten tcp &
xvfb_pid=$!
trap 'kill "$xvfb_pid" "$firefox_pid" 2>/dev/null || true' INT TERM EXIT

for _ in 1 2 3 4 5; do
  [ -S "/tmp/.X11-unix/X${DISPLAY#:}" ] && break
  sleep 1
done

firefox --headless --version
firefox --headless --screenshot /tmp/nest-firefox-smoke.png about:blank &
firefox_pid=$!
wait "$firefox_pid"
test -s /tmp/nest-firefox-smoke.png
