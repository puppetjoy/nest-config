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


def gtk_main(path=SOCKET_PATH):
    import subprocess
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GdkX11", "3.0")
    from gi.repository import Gtk, Gdk, GdkX11, GLib

    def request(command, **kwargs):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(8)
            client.connect(path)
            client.sendall(json.dumps({"command": command, 'owner_capability': cache['capability'], **kwargs}).encode() + b"\n")
            with client.makefile("rb") as stream:
                raw = stream.readline(MAX_LINE + 1)
        if len(raw) > MAX_LINE:
            raise ValueError("invalid response")
        response = json.loads(raw)
        if response.get("status") != "ok":
            raise ValueError("Window unavailable or selection uncertain. No retry or fallback.")
        return response

    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.pack_start(Gtk.Label(label="Firefox windows"), False, False, 4)
    combo = Gtk.ComboBoxText()
    status = Gtk.Label(label="Unlock with the owner window link from Star")
    cache = {"entries": [], "epoch": None, 'capability': None}
    credential = Gtk.Entry()
    credential.set_visibility(False)
    credential.set_placeholder_text('Owner window link')
    credential.set_max_length(512)

    def refresh(*_args):
        if cache['capability'] is None:
            return True
        selected = combo.get_active_id()
        try:
            response = request("list")
            entries = response["windows"]
            if entries != cache["entries"] or response["epoch"] != cache["epoch"]:
                combo.remove_all()
                cache.update(entries=entries, epoch=response["epoch"])
                for item in entries:
                    combo.append(item["scope"], item["label"])
                if selected and not combo.set_active_id(selected):
                    status.set_text("Previously viewed window closed; choose a current window")
        except Exception:
            status.set_text("Controller unavailable; no window selected")
        return True

    def choose_scope(scope):
        if not scope:
            status.set_text("Choose a current window first")
            return
        try:
            request("select", scope=scope, epoch=cache["epoch"])
            combo.set_active_id(scope)
            status.set_text("Viewing " + ("owner" if scope == "owner" else scope.rsplit(":", 1)[-1]))
        except Exception:
            status.set_text("Selection unavailable or uncertain; no fallback")

    view = Gtk.Button(label="View")
    view.connect("clicked", lambda *_: choose_scope(combo.get_active_id()))
    reload_button = Gtk.Button(label="Refresh")
    reload_button.connect("clicked", refresh)
    owner = Gtk.Button(label="Return to owner")
    owner.connect("clicked", lambda *_: choose_scope("owner"))
    controls = (combo, view, reload_button, owner)
    unlock_button = Gtk.Button(label='Unlock')
    lock_button = Gtk.Button(label='Lock')

    def lock(*_args):
        cache.update(capability=None, entries=[], epoch=None)
        combo.remove_all()
        credential.set_text('')
        unlock_button.show()
        lock_button.hide()
        for widget in controls:
            widget.hide()
        status.set_text('Unlock with the owner window link from Star')

    def unlock(*_args):
        # The existing owner-only fragment capability, never a service token or
        # task capability. Keep it only in this process's memory, not a file,
        # browser storage, command line, log, or clipboard helper.
        cache['capability'] = credential.get_text().rsplit('#', 1)[-1]
        credential.set_text('')
        try:
            request('list')
        except Exception:
            cache['capability'] = None
            status.set_text('Owner authentication unavailable; task links cannot unlock the directory')
            return
        credential.hide()
        unlock_button.hide()
        lock_button.show()
        for widget in controls:
            widget.show()
        status.set_text('Choose a window, then View')
        refresh()

    def prompt_unlock(*_args):
        dialog = Gtk.Dialog(title='Unlock Firefox windows', transient_for=window, modal=True)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        dialog.add_button('Unlock', Gtk.ResponseType.OK)
        dialog.get_content_area().add(credential)
        entry_handler = credential.connect('activate', lambda *_: dialog.response(Gtk.ResponseType.OK))
        dialog.show_all()
        credential.grab_focus()
        response = dialog.run()
        credential.disconnect(entry_handler)
        dialog.get_content_area().remove(credential)
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            unlock()
        else:
            credential.set_text('')

    unlock_button.connect('clicked', prompt_unlock)
    lock_button.connect('clicked', lock)
    for widget in (unlock_button, lock_button, combo, view, reload_button, owner, status):
        box.pack_start(widget, False, False, 0)
    window = Gtk.Window(title="Firefox windows")
    window.set_type_hint(Gdk.WindowTypeHint.DOCK)
    window.set_keep_above(True)
    window.set_focus_on_map(False)
    window.set_resizable(False)
    window.move(0, 0)
    window.add(box)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    lock()
    xid = GdkX11.X11Window.get_xid(window.get_window())
    height = window.get_allocated_height()
    # Reserve the visible bar in xmonad; this changes no browser binding. Only
    # this process's own X window is addressed, never another window or input.
    subprocess.run(["xprop", "-id", str(xid), "-f", "_NET_WM_STRUT_PARTIAL", "32c", "-set", "_NET_WM_STRUT_PARTIAL",
                    f"0, 0, {height}, 0, 0, 0, 0, 0, 0, 16383, 0, 0"], check=True, capture_output=True)
    refresh()
    GLib.timeout_add_seconds(2, refresh)
    Gtk.main()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--gtk", action="store_true")
    parser.add_argument("--socket", default=SOCKET_PATH)
    args = parser.parse_args()
    if not args.gtk:
        raise SystemExit("controller is started by firefox-bridge-server")
    gtk_main(args.socket)
