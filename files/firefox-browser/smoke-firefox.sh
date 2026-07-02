#!/bin/sh
set -eu

export DISPLAY="${DISPLAY:-:97}"
export HOME="${HOME:-/tmp/nest-firefox-smoke-home}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/nest-firefox-smoke-runtime}"
mkdir -p "$HOME/.vnc" "$XDG_RUNTIME_DIR"
chmod 700 "$HOME/.vnc" "$XDG_RUNTIME_DIR" || true

if [ ! -f "$HOME/.vnc/self.pem" ]; then
  openssl req \
    -x509 \
    -newkey rsa:2048 \
    -keyout "$HOME/.vnc/self.pem" \
    -out "$HOME/.vnc/self.pem" \
    -days 1 \
    -nodes \
    -subj '/CN=browser.eyrie-smoke' >/dev/null 2>&1
  chmod 600 "$HOME/.vnc/self.pem"
fi

kasmvnc_pid=
firefox_pid=
cleanup() {
  kill "$firefox_pid" "$kasmvnc_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

test -x /opt/kasmweb/bin/Xvnc
test -d /opt/kasmweb/share/kasmvnc/www

/opt/kasmweb/bin/Xvnc \
  -interface 127.0.0.1 \
  -PublicIP 127.0.0.1 \
  -disableBasicAuth \
  -RectThreads 0 \
  -Log '*:stdout:30' \
  -httpd /opt/kasmweb/share/kasmvnc/www \
  -sslOnly 1 \
  -SecurityTypes None \
  -websocketPort 6901 \
  -FreeKeyMappings \
  -cert "$HOME/.vnc/self.pem" \
  -key "$HOME/.vnc/self.pem" \
  -geometry 1024x768 \
  "$DISPLAY" &
kasmvnc_pid=$!

for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -S "/tmp/.X11-unix/X${DISPLAY#:}" ] && break
  sleep 1
done

curl -ksSf https://127.0.0.1:6901/ >/tmp/nest-kasmvnc-smoke.html

timeout 20 firefox --no-remote --new-instance --profile "$HOME/.mozilla/firefox/nest-smoke" about:blank &
firefox_pid=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do
  pgrep -P "$firefox_pid" >/dev/null 2>&1 || true
  sleep 1
  if pgrep -f 'firefox.*nest-smoke' >/dev/null 2>&1; then
    break
  fi
done
kill "$firefox_pid" 2>/dev/null || true
firefox_pid=

firefox --headless --version
