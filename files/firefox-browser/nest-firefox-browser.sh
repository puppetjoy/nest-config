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

resize_firefox_windows_once() {
  fallback_width="$1"
  fallback_height="$2"

  display_geometry=$(xdotool getdisplaygeometry 2>/dev/null || true)
  if [ -n "$display_geometry" ]; then
    # shellcheck disable=SC2086
    set -- $display_geometry
    target_width="$1"
    target_height="$2"

    # KasmVNC/Xvnc can report the initial width one pixel smaller than the
    # requested geometry. Keep the launch size for that off-by-one startup case,
    # but honor real client resize events in either direction.
    if [ "$target_width" -lt "$FIREFOX_WIDTH" ] && [ $((FIREFOX_WIDTH - target_width)) -le 1 ]; then
      target_width="$FIREFOX_WIDTH"
    fi
    if [ "$target_height" -lt "$FIREFOX_HEIGHT" ] && [ $((FIREFOX_HEIGHT - target_height)) -le 1 ]; then
      target_height="$FIREFOX_HEIGHT"
    fi
  else
    target_width="$fallback_width"
    target_height="$fallback_height"
  fi

  window_ids=$(xdotool search --onlyvisible --classname Navigator 2>/dev/null || true)
  [ -n "$window_ids" ] || return 1

  # Firefox extension panels and other chrome popups use WM_CLASS firefox but not
  # WM_CLASS Navigator.  Only inspect Navigator top-level browser windows; even
  # enumerating the transient popup windows from the steady-state watcher can
  # make the extensions menu collapse before Joy can move the pointer into it.
  browser_window_id=
  browser_window_area=0
  for window_id in $window_ids; do
    window_geometry=$(xdotool getwindowgeometry --shell "$window_id" 2>/dev/null || true)
    [ -n "$window_geometry" ] || continue
    eval "$window_geometry"
    window_area=$((WIDTH * HEIGHT))
    if [ "$window_area" -gt "$browser_window_area" ]; then
      browser_window_id="$window_id"
      browser_window_area="$window_area"
      browser_window_x="$X"
      browser_window_y="$Y"
      browser_window_width="$WIDTH"
      browser_window_height="$HEIGHT"
    fi
  done

  [ -n "$browser_window_id" ] || return 1
  if [ "$browser_window_x" -eq 0 ] && [ "$browser_window_y" -eq 0 ] && [ "$browser_window_width" -eq "$target_width" ] && [ "$browser_window_height" -eq "$target_height" ]; then
    return 0
  fi
  xdotool windowmove "$browser_window_id" 0 0 windowsize "$browser_window_id" "$target_width" "$target_height" 2>/dev/null || true
}

# Without a full desktop session/window manager, Firefox may keep its default
# first-run window geometry and will not automatically grow when KasmVNC accepts
# a client-side SetDesktopSize resize. Keep the top-level Firefox window pinned
# to the current KasmVNC framebuffer so both shrink and grow browser-window
# resizes behave like the upstream kasmweb image instead of leaving black unused
# desktop area after the viewport is expanded.
if command -v xdotool >/dev/null 2>&1; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if resize_firefox_windows_once "$FIREFOX_WIDTH" "$FIREFOX_HEIGHT"; then
      break
    fi
    sleep 1
  done

  (
    while kill -0 "$firefox_pid" 2>/dev/null; do
      resize_firefox_windows_once "$FIREFOX_WIDTH" "$FIREFOX_HEIGHT" || true
      sleep "${FIREFOX_RESIZE_POLL_SECONDS:-1}"
    done
  ) &
fi

wait "$firefox_pid"
