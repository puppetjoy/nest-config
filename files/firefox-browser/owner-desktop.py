"""Owner desktop controls: private peer-authenticated IPC, never a public API."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import socket
import socketserver
import struct
import threading

SOCKET_PATH = "/tmp/nest-firefox/owner-desktop.sock"
MAX_LINE = 4096
SCOPE = re.compile(r"kanban:[A-Za-z0-9_.-]+:t_[A-Za-z0-9_-]+\Z")


def visible_windows(windows):
    with windows.operation():
        return [{"scope": scope, "label": "Owner window" if scope == "owner" else scope.replace("kanban:", "Task ", 1)}
                for scope, record in sorted(windows.state.get("windows", {}).items(), key=lambda item: (item[0] != "owner", item[0]))
                if record.get("state") == "open" and record.get("epoch") == windows.epoch
                and (scope == "owner" or SCOPE.fullmatch(scope))][:12]


def native_window_id(windows, client_window):
    from firefox_windows import driver_request
    session = windows.state['controller']['session']
    path = '/session/' + session
    driver_request('POST', path + '/moz/context', {'context': 'chrome'})
    try:
        handle = driver_request('POST', path + '/execute/sync', {'script': '''
          const {windowManager}=ChromeUtils.importESModule("chrome://remote/content/shared/WindowManager.sys.mjs");
          const w=windowManager.getWindowById(arguments[0]);
          if(!w)throw new Error('exact native window unavailable');
          const handle=w.docShell.treeOwner.QueryInterface(Ci.nsIBaseWindow).nativeHandle;
          const {ctypes}=ChromeUtils.importESModule('resource://gre/modules/ctypes.sys.mjs');
          const gdk=ctypes.open('libgdk-3.so.0');
          try {
            const top=gdk.declare('gdk_window_get_toplevel',ctypes.default_abi,ctypes.voidptr_t,ctypes.voidptr_t);
            const xid=gdk.declare('gdk_x11_window_get_xid',ctypes.default_abi,ctypes.unsigned_long,ctypes.voidptr_t);
            return xid(top(ctypes.voidptr_t(ctypes.UInt64(handle)))).toString();
          } finally {gdk.close();}
        ''', 'args': [client_window]})
    finally:
        driver_request('POST', path + '/moz/context', {'context': 'content'})
    if not isinstance(handle, str) or not re.fullmatch(r'(?:0x[0-9a-fA-F]+|[0-9]+)', handle):
        raise ValueError('native window identity unavailable')
    return str(int(handle, 16 if handle.startswith('0x') else 10))


def focus_native_window(handle, pid):
    import ctypes as c
    import subprocess
    import time
    identity = subprocess.check_output(['xprop', '-id', handle, '_NET_WM_PID'], text=True, timeout=2)
    if identity.strip() != f'_NET_WM_PID(CARDINAL) = {pid}':
        raise ValueError('native X window process changed')
    x = c.CDLL('libX11.so.6')
    class Message(c.Structure):
        _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int), ('display', c.c_void_p),
                    ('window', c.c_ulong), ('message_type', c.c_ulong), ('format', c.c_int), ('data', c.c_long * 5)]
    class Event(c.Union):
        _fields_ = [('message', Message), ('pad', c.c_long * 24)]
    x.XOpenDisplay.argtypes = [c.c_char_p]
    x.XOpenDisplay.restype = c.c_void_p
    x.XDefaultRootWindow.argtypes = [c.c_void_p]
    x.XDefaultRootWindow.restype = c.c_ulong
    x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]
    x.XInternAtom.restype = c.c_ulong
    x.XSendEvent.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_long, c.POINTER(Event)]
    x.XFlush.argtypes = [c.c_void_p]
    x.XCloseDisplay.argtypes = [c.c_void_p]
    display = x.XOpenDisplay(None)
    if not display:
        raise ValueError('owner display unavailable')
    try:
        root = x.XDefaultRootWindow(display)
        event = Event()
        event.message.type = 33
        event.message.display = display
        event.message.window = root
        event.message.message_type = x.XInternAtom(display, b'_NEST_OWNER_FOCUS', False)
        event.message.format = 32
        event.message.data[0] = int(handle)
        if not x.XSendEvent(display, root, False, (1 << 19) | (1 << 20), c.byref(event)):
            raise ValueError('owner focus request refused')
        x.XFlush(display)
    finally:
        x.XCloseDisplay(display)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        current = subprocess.check_output(['xdotool', 'getwindowfocus'], text=True, timeout=2).strip()
        if current == handle:
            return
        time.sleep(.05)
    raise ValueError('owner focus not observed; selection was not retried')


def select_window(windows, scope, epoch):
    with windows.operation():
        if (not isinstance(scope, str) or not isinstance(epoch, str) or epoch != windows.epoch
                or scope != "owner" and not SCOPE.fullmatch(scope)):
            raise ValueError("stale selection")
        record = windows.state.get("windows", {}).get(scope)
        if not isinstance(record, dict) or record.get("state") != "open" or record.get("epoch") != epoch:
            raise ValueError("stale selection")
        context = windows._resolve(record)
        cid = context.get("context")
        if not isinstance(cid, str) or cid != record.get("context"):
            raise ValueError("stale selection")
        # Deliberate owner focus only. Agent dispatch never calls this path and
        # never follows the foreground window. No prompt is dismissed or accepted.
        handle = native_window_id(windows, record['window'])
        windows._resolve(record)
        focus_native_window(handle, windows.state['controller']['pid'])


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(5)
            peer = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _pid, uid, _gid = struct.unpack("3i", peer)
            if uid != self.server.peer_uid:
                return
            raw = self.rfile.readline(MAX_LINE + 1)
            if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
                raise ValueError("invalid")
            request = json.loads(raw)
            if not isinstance(request, dict) or request.get("command") not in {"list", "select"}:
                raise ValueError("invalid")
            if request["command"] == "list" and set(request) != {"command", "owner_capability"}:
                raise ValueError("invalid")
            if request["command"] == "select" and set(request) != {"command", "scope", "epoch", "owner_capability"}:
                raise ValueError("invalid")
            with self.server.windows.operation():
                owner = self.server.windows.state.get('windows', {}).get('owner', {})
                capability = request.get('owner_capability')
                if (not isinstance(capability, str) or not 20 <= len(capability) <= 200
                        or owner.get('state') != 'open' or owner.get('epoch') != self.server.windows.epoch
                        or not secrets.compare_digest(owner.get('viewer', ''), capability)):
                    raise ValueError('owner authentication required')
                if request["command"] == "list":
                    result = {"status": "ok", "epoch": self.server.windows.epoch, "windows": visible_windows(self.server.windows)}
                else:
                    select_window(self.server.windows, request["scope"], request["epoch"])
                    result = {"status": "ok"}
        except Exception:
            result = {"status": "error", "message": "Window unavailable or selection uncertain. No automatic retry or fallback."}
        try:
            self.wfile.write(json.dumps(result, separators=(",", ":")).encode() + b"\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # Never repeat an owner selection after a lost acknowledgement.


class OwnerSocket:
    def __init__(self, path, windows, peer_uid=None):
        self.path, self.windows = str(path), windows
        self.peer_uid = os.getuid() if peer_uid is None else peer_uid
        self.server = self.thread = None

    def start(self):
        parent = Path(self.path).parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(parent, 0o700)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self.server = socketserver.ThreadingUnixStreamServer(self.path, _Handler)
        self.server.daemon_threads = True
        self.server.windows, self.server.peer_uid = self.windows, self.peer_uid
        os.chmod(self.path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            if self.thread:
                self.thread.join(timeout=2)
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass


class OwnerPanel:
    """Controller-spawned native UI with a non-addressable inherited channel.

    Desktop access is the owner boundary. No task capability authenticates this
    channel, and neither HTTP clients nor same-UID socket clients can open it.
    The legacy private capability socket remains separate for compatibility.
    """
    def __init__(self, windows):
        self.windows = windows
        self.server, self.client = socket.socketpair()
        self.thread = self.process = None
        self.handles = {}

    def directory(self):
        # Native owner-created windows have no agent lease. Discover them from
        # the private native tree, without assigning custody or altering state.
        live = {}
        for context in self.windows._tree():
            if isinstance(context.get('clientWindow'), str):
                live.setdefault(context['clientWindow'], context['context'])
        records = {}
        entries = []
        for item in visible_windows(self.windows):
            record = self.windows.state['windows'][item['scope']]
            if record['window'] in live:
                records[item['scope']] = record
                entries.append(item)
        managed = {record['window'] for record in records.values()}
        for index, native in enumerate(sorted(set(live) - managed), 2):
            scope = 'desktop:' + native
            entries.append({'scope': scope, 'label': f'Owner window {index}'})
            records[scope] = {'context': live[native], 'window': native}
        return entries, records

    def dispatch(self, request):
        if not isinstance(request, dict):
            raise ValueError('invalid')
        command = request.get('command')
        required = {'command'} if command == 'list' else {'command', 'scope', 'epoch'}
        if command not in {'list', 'select'} or set(request) != required:
            raise ValueError('invalid')
        with self.windows.operation():
            if command == 'select':
                scope = request['scope']
                if not isinstance(scope, str) or request['epoch'] != self.windows.epoch:
                    raise ValueError('stale selection')
                if scope.startswith('desktop:'):
                    _, records = self.directory()
                    record = records.get(scope)
                    if not record:
                        raise ValueError('stale selection')
                    handle = native_window_id(self.windows, record['window'])
                    _, current = self.directory()
                    if current.get(scope) != record:
                        raise ValueError('stale selection')
                    focus_native_window(handle, self.windows.state['controller']['pid'])
                else:
                    select_window(self.windows, scope, request['epoch'])
                return {'status': 'ok'}
            entries, records = self.directory()
            # Cache only native identity, keyed by immutable generation/binding.
            active = set()
            import subprocess
            focus = subprocess.check_output(['xdotool', 'getwindowfocus'], text=True, timeout=2).strip()
            current = None
            for entry in entries:
                scope = entry['scope']
                record = records[scope]
                key = (self.windows.epoch, scope, record['context'], record['window'])
                active.add(key)
                if key not in self.handles:
                    self.handles[key] = native_window_id(self.windows, record['window'])
                if self.handles[key] == focus:
                    current = scope
            self.handles = {key: value for key, value in self.handles.items() if key in active}
            return {'status': 'ok', 'epoch': self.windows.epoch, 'windows': entries, 'current': current}

    def serve(self):
        try:
            with self.server.makefile('rb') as stream:
                while True:
                    raw = stream.readline(MAX_LINE + 1)
                    if not raw:
                        return
                    if len(raw) > MAX_LINE or not raw.endswith(b'\n'):
                        return
                    try:
                        response = self.dispatch(json.loads(raw))
                    except Exception:
                        response = {'status': 'error', 'message': 'Window unavailable or selection uncertain. No automatic retry or fallback.'}
                    self.server.sendall(json.dumps(response).encode() + b'\n')
        except (OSError, ValueError):
            pass  # Channel loss never replays an owner selection.

    def start(self):
        import subprocess
        import sys
        env = dict(os.environ)
        # A supported controller refresh may not inherit the desktop bus.
        session = Path('/tmp/nest-firefox/session.env')
        for line in session.read_text().splitlines() if session.exists() else []:
            key, value = line.split('=', 1)
            if key == 'DBUS_SESSION_BUS_ADDRESS':
                env[key] = value
        env.update(DISPLAY=os.environ.get('DISPLAY', ':1'), NO_AT_BRIDGE='0', GTK_MODULES='atk-bridge', ATSPI_DISABLE_P2P='1')
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--gtk', '--fd', str(self.client.fileno())],
                                        pass_fds=(self.client.fileno(),), env=env)
        self.client.close()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.client.close()
        try:
            self.server.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.server.close()
        if self.thread:
            self.thread.join(timeout=2)


def gtk_main(fd):
    import subprocess
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import Gtk, Gdk, GdkX11, GLib, Pango

    channel = socket.socket(fileno=fd)
    channel.settimeout(8)
    stream = channel.makefile('rb')
    def request(command, **kwargs):
        try:
            channel.sendall(json.dumps({'command': command, **kwargs}).encode() + b'\n')
            raw = stream.readline(MAX_LINE + 1)
        except (BrokenPipeError, ConnectionResetError):
            GLib.idle_add(Gtk.main_quit)
            raise
        if not raw:
            GLib.idle_add(Gtk.main_quit)
            raise ValueError('controller channel closed')
        if len(raw) > MAX_LINE:
            raise ValueError('invalid response')
        response = json.loads(raw)
        if response.get('status') != 'ok':
            raise ValueError('Window unavailable or selection uncertain. No retry or fallback.')
        return response

    window = Gtk.Window(title='Firefox windows')
    window.set_type_hint(Gdk.WindowTypeHint.DOCK)
    window.set_keep_above(True)
    window.set_focus_on_map(False)
    window.set_resizable(False)
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.set_border_width(3)
    box.pack_start(Gtk.Label(label='Windows'), False, False, 3)
    combo = Gtk.ComboBoxText()
    combo.set_hexpand(True)
    combo.set_size_request(80, -1)
    for cell in combo.get_cells():
        cell.set_property('ellipsize', Pango.EllipsizeMode.END)
        cell.set_property('width-chars', 16)
    box.pack_start(combo, True, True, 0)
    owner = Gtk.Button(label='Return to owner')
    box.pack_start(owner, False, False, 0)
    window.add(box)
    cache = {'entries': [], 'epoch': None, 'updating': False}

    def choose(scope):
        if cache['updating'] or not scope:
            return
        try:
            request('select', scope=scope, epoch=cache['epoch'])
            combo.set_tooltip_text(None)
        except Exception:
            # Do not silently select a different window or replay an uncertain
            # input. The next list observation only repairs the visible model.
            combo.set_tooltip_text('Selection unavailable or uncertain; choose again deliberately')
        refresh()

    def refresh(*_args):
        cache['updating'] = True
        try:
            response = request('list')
            entries = response['windows']
            if entries != cache['entries'] or response['epoch'] != cache['epoch']:
                combo.remove_all()
                cache.update(entries=entries, epoch=response['epoch'])
                for item in entries:
                    combo.append(item['scope'], item['label'])
            current = response.get('current')
            if current:
                combo.set_active_id(current)
            elif combo.get_active_id() not in {item['scope'] for item in entries}:
                combo.set_active(-1)
            combo.set_sensitive(bool(entries))
            owner.set_sensitive(any(item['scope'] == 'owner' for item in entries))
        except Exception:
            combo.set_tooltip_text('Window list temporarily unavailable')
            combo.set_sensitive(False)
        finally:
            cache['updating'] = False
        return True

    combo.connect('changed', lambda *_: choose(combo.get_active_id()))
    owner.connect('clicked', lambda *_: choose('owner'))
    window.connect('destroy', Gtk.main_quit)
    screen = window.get_screen()
    def geometry(*_args):
        monitor = Gdk.Display.get_default().get_monitor(0).get_geometry()
        width = monitor.width
        window.set_size_request(width, -1)
        height = max(1, window.get_preferred_height()[1])
        window.resize(width, height)
        window.move(0, 0)
        if window.get_realized():
            xid = GdkX11.X11Window.get_xid(window.get_window())
            height = window.get_allocated_height()
            subprocess.run(['xprop', '-id', str(xid), '-f', '_NET_WM_STRUT_PARTIAL', '32c', '-set', '_NET_WM_STRUT_PARTIAL',
                            f'0, 0, {height}, 0, 0, 0, 0, 0, 0, {width - 1}, 0, 0'], check=True, capture_output=True)
    screen.connect('size-changed', geometry)
    window.connect('size-allocate', geometry)
    geometry()
    window.show_all()
    geometry()
    refresh()
    GLib.timeout_add_seconds(2, refresh)
    Gtk.main()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--gtk', action='store_true')
    parser.add_argument('--fd', type=int, required=True)
    args = parser.parse_args()
    if not args.gtk:
        raise SystemExit('controller is started by firefox-bridge-server')
    gtk_main(args.fd)
