#!/bin/sh
set -eu

export DISPLAY="${DISPLAY:-:1}"
export HOME="${FIREFOX_HOME:-/home/kasm-user}"
export LAUNCH_URL="${LAUNCH_URL:-about:blank}"
export APP_ARGS="${APP_ARGS:-}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-firefox}"
vnc_geometry="${VNC_RESOLUTION:-1365x768x24}"
vnc_width="${vnc_geometry%%x*}"
vnc_height_depth="${vnc_geometry#*x}"
vnc_height="${vnc_height_depth%%x*}"
export FIREFOX_WIDTH="${FIREFOX_WIDTH:-${vnc_width}}"
export FIREFOX_HEIGHT="${FIREFOX_HEIGHT:-${vnc_height}}"
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
  "$HOME/.vnc" \
  "$XDG_RUNTIME_DIR" \
  /tmp/nest-firefox
chmod 700 "$XDG_RUNTIME_DIR" "$HOME/.mozilla/firefox/nest-secure-browser" "$HOME/.vnc" || true

kasmvnc_pid=
firefox_pid=

if [ ! -f "$HOME/.vnc/self.pem" ]; then
  openssl req \
    -x509 \
    -newkey rsa:2048 \
    -keyout "$HOME/.vnc/self.pem" \
    -out "$HOME/.vnc/self.pem" \
    -days 3650 \
    -nodes \
    -subj '/CN=browser.eyrie' >/dev/null 2>&1
  chmod 600 "$HOME/.vnc/self.pem"
fi

cleanup() {
  kill "$firefox_pid" "$kasmvnc_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

/opt/kasmweb/bin/Xvnc \
  -interface 0.0.0.0 \
  -PublicIP 127.0.0.1 \
  -disableBasicAuth \
  -RectThreads 0 \
  -Log '*:stdout:100' \
  -httpd /opt/kasmweb/share/kasmvnc/www \
  -sslOnly 1 \
  -SecurityTypes None \
  -websocketPort 6901 \
  -FreeKeyMappings \
  -cert "$HOME/.vnc/self.pem" \
  -key "$HOME/.vnc/self.pem" \
  -geometry "${FIREFOX_WIDTH}x${FIREFOX_HEIGHT}" \
  "$DISPLAY" &
kasmvnc_pid=$!

# Let KasmVNC create the display socket before clients attach.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -S "/tmp/.X11-unix/X${DISPLAY#:}" ] && break
  sleep 1
done

# shellcheck disable=SC2086
firefox \
  --no-remote \
  --new-instance \
  --profile "$HOME/.mozilla/firefox/nest-secure-browser" \
  --width "$FIREFOX_WIDTH" \
  --height "$FIREFOX_HEIGHT" \
  $APP_ARGS \
  "$LAUNCH_URL" &
firefox_pid=$!

# Without a full desktop session/window manager, Firefox may keep its default
# first-run window geometry.  Resize the top-level window to the KasmVNC
# framebuffer. KasmVNC, not noVNC scaling, owns browser-window resizing from
# there so Joy sees the same unscaled surface as the upstream kasmweb image.
if command -v xdotool >/dev/null 2>&1; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    window_ids=$(xdotool search --onlyvisible --class firefox 2>/dev/null || true)
    if [ -n "$window_ids" ]; then
      for window_id in $window_ids; do
        xdotool windowmove "$window_id" 0 0 windowsize "$window_id" "$FIREFOX_WIDTH" "$FIREFOX_HEIGHT" 2>/dev/null || true
      done
      break
    fi
    sleep 1
  done
fi

wait "$firefox_pid"
