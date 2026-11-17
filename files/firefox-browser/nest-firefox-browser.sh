#!/bin/sh
set -eu

export DISPLAY="${DISPLAY:-:1}"
export HOME="${FIREFOX_HOME:-/home/kasm-user}"
export LAUNCH_URL="${LAUNCH_URL:-}"
export APP_ARGS="${APP_ARGS:-}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-firefox}"
export NO_AT_BRIDGE=0
export GTK_MODULES="${GTK_MODULES:-atk-bridge}"
# AT-SPI 2.58 retains disconnected direct client connections in Firefox,
# including their libdbus pidfds. Fresh bridge workers then grow descriptors
# and dispatch latency indefinitely. Use the same private accessibility bus
# instead of advertising a direct socket; keep accessibility/authentication on.
# This must be set before Firefox loads atk-bridge, not only in its clients.
export ATSPI_DISABLE_P2P=1
vnc_geometry="${VNC_RESOLUTION:-1365x768x24}"
vnc_width="${vnc_geometry%%x*}"
vnc_height_depth="${vnc_geometry#*x}"
vnc_height="${vnc_height_depth%%x*}"
export FIREFOX_WIDTH="${FIREFOX_WIDTH:-${vnc_width}}"
export FIREFOX_HEIGHT="${FIREFOX_HEIGHT:-${vnc_height}}"
# Keep Firefox's process sandboxes enabled.  The Kubernetes workload grants the
# narrow SETFCAP capability Firefox needs to create its user namespace instead
# of suppressing the sandbox and showing a visible unsupported-configuration
# warning in the browser chrome.

mkdir -p \
  "$HOME" \
  "$HOME/.mozilla/firefox/nest-secure-browser" \
  "$HOME/.mozilla/firefox/nest-secure-browser/thumbnails" \
  "$HOME/.vnc" \
  "$HOME/.local/state/nest-firefox-ui" \
  "$XDG_RUNTIME_DIR" \
  /tmp/nest-firefox
chmod 700 "$XDG_RUNTIME_DIR" "$HOME/.mozilla/firefox/nest-secure-browser" "$HOME/.vnc" "$HOME/.local/state/nest-firefox-ui" || true

# The optional v2 backend attaches to this SAME visible Firefox process through
# a loopback-only BiDi listener. Never accept arbitrary automation arguments
# from KubeCM, and never publish this listener as a container/service port.
case " $APP_ARGS " in
  *remote-debugging*|*marionette*|*webdriver*|*bidi*|*devtools-server*)
    printf '%s\n' 'Refusing automation-specific Firefox APP_ARGS' >&2
    exit 64
    ;;
esac

case "${FIREFOX_CONTROL_PROTOCOL:-firefox-ui-v1}" in
  firefox-ui-v1) bidi_args= ;;
  # geckodriver connects to this existing Firefox over loopback Marionette.
  firefox-bidi-ui-v2) bidi_args='--remote-debugging-port=9222 --marionette' ;;
  firefox-windows-v3) bidi_args='--remote-debugging-port=9222 --marionette --remote-allow-system-access' ;;
  *) printf '%s\n' 'Unknown Firefox control protocol' >&2; exit 64 ;;
esac

kasmvnc_pid=
xmonad_pid=
firefox_pid=
dbus_pid=
bridge_pid=
owner_desktop_pid=
driver_pid=

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
  trap - INT TERM EXIT
  # Keep Firefox's display and accessibility bus alive until it has exited.
  # Never escalate to SIGKILL or automatically relaunch it here.
  if [ -n "$firefox_pid" ] && kill -0 "$firefox_pid" 2>/dev/null; then
    kill "$firefox_pid" 2>/dev/null || true
    wait "$firefox_pid" 2>/dev/null || true
  fi
  for pid in "$owner_desktop_pid" "$bridge_pid" "$driver_pid" "$xmonad_pid" "$kasmvnc_pid" "$dbus_pid"; do
    [ -z "$pid" ] || kill "$pid" 2>/dev/null || true
  done
}
trap 'exit 143' TERM
trap 'exit 130' INT
trap cleanup EXIT

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

# Firefox and the UI bridge share one private desktop accessibility bus. The
# bridge receives only the bus address, never profile/session secrets. This is
# the OS accessibility boundary; v2 additionally uses private BiDi for page
# content/selector access, but keeps this bus for chrome and fallback controls.
eval "$(dbus-launch --sh-syntax)"
dbus_pid="${DBUS_SESSION_BUS_PID:-}"
printf 'DBUS_SESSION_BUS_ADDRESS=%s\n' "$DBUS_SESSION_BUS_ADDRESS" > /tmp/nest-firefox/session.env
chmod 600 /tmp/nest-firefox/session.env
gsettings set org.gnome.desktop.interface toolkit-accessibility true >/dev/null 2>&1 || true
/usr/libexec/at-spi-bus-launcher --launch-immediately >/tmp/nest-firefox/at-spi.log 2>&1 &

# Run xmonad from the workstation base image so Firefox chrome popups (including
# the extensions panel/Bitwarden entry point) get normal transient-window focus
# semantics without introducing decorated window chrome.
if command -v xmonad >/dev/null 2>&1; then
  mkdir -p "$HOME/.xmonad" "${XDG_CONFIG_HOME:-$HOME/.config}/xmonad"
  cp /opt/nest/firefox/xmonad.hs "$HOME/.xmonad/xmonad.hs"
  cp /opt/nest/firefox/xmonad.hs "${XDG_CONFIG_HOME:-$HOME/.config}/xmonad/xmonad.hs"
  xmonad >/tmp/nest-firefox/xmonad.log 2>&1 &
  xmonad_pid=$!
  sleep 1
fi

# shellcheck disable=SC2086
# Do not append about:blank on every restart: an explicit launch URL creates
# an extra tab even when session restoration is enabled.
set --
[ -z "$LAUNCH_URL" ] || set -- "$LAUNCH_URL"
firefox \
  --no-remote \
  --new-instance \
  --profile "$HOME/.mozilla/firefox/nest-secure-browser" \
  --width "$FIREFOX_WIDTH" \
  --height "$FIREFOX_HEIGHT" \
  $bidi_args \
  $APP_ARGS \
  "$@" &
firefox_pid=$!

# One native session for the same Firefox, surviving bridge observer reconnects.
# Neither driver nor native listeners are routed by the Kubernetes Service.
if [ "${FIREFOX_CONTROL_PROTOCOL:-}" = firefox-windows-v3 ]; then
  geckodriver --host 127.0.0.1 --port 4444 --connect-existing --marionette-port 2828 \
    >/dev/null 2>&1 &
  driver_pid=$!
fi

# Controller disconnects and bridge failures never restart Firefox. Isolated
# smoke tests without a credential do not start this guarded service listener.
if [ -n "${FIREFOX_BRIDGE_TOKEN_FILE:-}" ]; then
  python3 /opt/nest/firefox/bin/firefox-bridge-server.py &
  bridge_pid=$!
  # The resident controller launches its native owner panel with a private
  # inherited channel. No link, task capability or addressable UI socket.
fi

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
# In v3 xmonad owns the managed window geometry and the dock's strut. Do
# not race it by forcing the Firefox window across the reserved toolbar.
if command -v xdotool >/dev/null 2>&1 && [ "${FIREFOX_CONTROL_PROTOCOL:-}" != firefox-windows-v3 ]; then
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
