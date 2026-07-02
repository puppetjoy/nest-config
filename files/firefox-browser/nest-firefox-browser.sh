#!/bin/sh
set -eu

export DISPLAY="${DISPLAY:-:1}"
export HOME="${FIREFOX_HOME:-/home/kasm-user}"
export LAUNCH_URL="${LAUNCH_URL:-about:blank}"
export APP_ARGS="${APP_ARGS:-}"
# KubeCM still sets the historical VNCOPTIONS variable from the upstream Kasm
# canary. The Nest noVNC wrapper owns the no-password setting directly.
# Keep the value for compatibility, but do not pass it to x11vnc.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-firefox}"
# Firefox's Linux content sandbox expects user namespaces that are not
# available in this Kubernetes container.  Disable the process sandboxes so
# Portage Firefox can load pages instead of repeatedly crashing content
# processes with EPERM while the pod-level/Kubernetes boundary remains the
# workload isolation layer.
export MOZ_DISABLE_CONTENT_SANDBOX="${MOZ_DISABLE_CONTENT_SANDBOX:-1}"
export MOZ_DISABLE_RDD_SANDBOX="${MOZ_DISABLE_RDD_SANDBOX:-1}"
export MOZ_DISABLE_GMP_SANDBOX="${MOZ_DISABLE_GMP_SANDBOX:-1}"
export MOZ_DISABLE_GPU_SANDBOX="${MOZ_DISABLE_GPU_SANDBOX:-1}"

mkdir -p \
  "$HOME" \
  "$HOME/.mozilla/firefox/nest-secure-browser" \
  "$HOME/.mozilla/firefox/nest-secure-browser/thumbnails" \
  "$XDG_RUNTIME_DIR" \
  /tmp/nest-firefox
chmod 700 "$XDG_RUNTIME_DIR" "$HOME/.mozilla/firefox/nest-secure-browser" || true

xvfb_pid=
firefox_pid=
x11vnc_pid=
websockify_pid=

if [ ! -f /tmp/nest-firefox/websockify.pem ]; then
  openssl req \
    -x509 \
    -newkey rsa:2048 \
    -keyout /tmp/nest-firefox/websockify.pem \
    -out /tmp/nest-firefox/websockify.pem \
    -days 1 \
    -nodes \
    -subj '/CN=browser.eyrie' >/dev/null 2>&1
  chmod 600 /tmp/nest-firefox/websockify.pem
fi

Xvfb "$DISPLAY" -screen 0 "${VNC_RESOLUTION:-1365x768x24}" -nolisten tcp &
xvfb_pid=$!

cleanup() {
  kill "$firefox_pid" "$x11vnc_pid" "$websockify_pid" "$xvfb_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# Let Xvfb create the display socket before clients attach.
for _ in 1 2 3 4 5; do
  [ -S "/tmp/.X11-unix/X${DISPLAY#:}" ] && break
  sleep 1
done

x11vnc \
  -display "$DISPLAY" \
  -rfbport 5900 \
  -forever \
  -shared \
  -nopw \
  -quiet &
x11vnc_pid=$!

websockify \
  --web /usr/share/novnc \
  --cert /tmp/nest-firefox/websockify.pem \
  6901 \
  127.0.0.1:5900 &
websockify_pid=$!

# shellcheck disable=SC2086
firefox \
  --no-remote \
  --new-instance \
  --profile "$HOME/.mozilla/firefox/nest-secure-browser" \
  $APP_ARGS \
  "$LAUNCH_URL" &
firefox_pid=$!

wait "$firefox_pid"
