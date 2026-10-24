"""Resident same-session Firefox windows. Native identities never outlive a session.

No URL/title ownership inference, replacement native sessions, global focus or XTest.
The durable journal is written before creation/input/close. A broken controller
preserves existing windows; observer reconnects retain the exact native session.
"""
from __future__ import annotations

import hashlib
import contextlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

SCOPE = re.compile(r"kanban:[A-Za-z0-9_.-]+:t_[A-Za-z0-9_-]+\Z")
TERMINAL = {"completed", "cancelled", "denied", "superseded"}


class ControlError(RuntimeError):
    """Fixed public errors; never include native exceptions or page data."""
    def __init__(self, code, message, outcome="not_started"):
        super().__init__(message)
        self.code = code
        self.outcome = outcome

# Fixed source only. Selectors and text are JSON arguments, never source.
ELEMENT = """(selector, inputX, inputY) => {
 const found=selector ? [...document.querySelectorAll(selector)] : [document.elementFromPoint(inputX,inputY)];
 if(found.length!==1 || !found[0])throw Error('target is not unique');
 const e=found[0], r=e.getBoundingClientRect(), s=getComputedStyle(e);
 if(!r.width||!r.height||s.visibility==='hidden'||s.display==='none'||e.disabled)throw Error('target unavailable');
 const x=Math.max(0,r.left)+Math.min(r.width,innerWidth-Math.max(0,r.left))/2;
 const y=Math.max(0,r.top)+Math.min(r.height,innerHeight-Math.max(0,r.top))/2;
 const hit=document.elementFromPoint(x,y);
 if(x<0||y<0||x>=innerWidth||y>=innerHeight||!hit||!(hit===e||e.contains(hit)))throw Error('target outside viewport or intercepted');
 const hint=[e.name,e.id,e.getAttribute('aria-label'),e.getAttribute('autocomplete'),
 e.getAttribute('placeholder'),...(e.labels?[...e.labels].map(l=>l.innerText):[])].join(' ');
 const protectedField=e.matches('input[type=password],input[type=hidden],input[type=file]')||
 /password|passcode|verification|one.time|security.code|cvv|cvc|card.number|account.number|routing.number|secret|token|recovery.code/i.test(hint);
 return {node:e, protected:protectedField, editable:(e.matches('input,textarea')||e.isContentEditable)&&!e.readOnly,
 multiline:e.matches('textarea')||e.isContentEditable,
 x,y};
}"""
FIELD = """(e) => ({active:document.activeElement===e,value:e.isContentEditable?e.innerText:e.value,
 start:e.selectionStart,end:e.selectionEnd,visible:!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height)})"""


def valid_scope(scope):
    if not isinstance(scope, str) or (scope != "owner" and not SCOPE.fullmatch(scope)):
        raise ValueError("invalid immutable window scope")
    return scope


def process_generation(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError("invalid native browser process")
    started = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    namespace = os.stat(f"/proc/{pid}/ns/pid").st_ino
    return hashlib.sha256(f"{boot}:{namespace}:{pid}:{started}".encode()).hexdigest()


def driver_request(method, path, data=None):
    connection = http.client.HTTPConnection("127.0.0.1", 4444, timeout=15)
    try:
        connection.request(method, path, body=json.dumps(data) if data is not None else None,
                           headers={"Content-Type": "application/json"})
        reply = connection.getresponse()
        raw = reply.read(1_000_001)
        if len(raw) > 1_000_000 or reply.status >= 400:
            raise RuntimeError("private resident driver request failed")
        return json.loads(raw)["value"]
    finally:
        connection.close()


def validate_session_endpoint(session, endpoint):
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session) or not isinstance(endpoint, str):
        raise ValueError("invalid resident session identity")
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port != 9222 or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/session/" + session):
        raise RuntimeError("invalid private resident session endpoint")


class Windows:
    def __init__(self, path, connect=None):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.connect = connect or self._connect
        self.browser = None
        self.broken = False
        self.epoch = secrets.token_hex(24)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"windows": {}, "actions": {}}
        # Old uncertain keys remain non-replayable across the architecture
        # transition. Keep the original journal intact; import no draft data.
        legacy = self.path.parent / "state.json"
        self.legacy_keys = set(json.loads(legacy.read_text()).get("action_keys", {})) if legacy.exists() else set()
        self.legacy_keys.update(self.state.get("retired_action_keys", []))
        # A fresh native session changes identities even for existing windows.
        # Do not reconnect to old IDs, guess by URL, or spawn replacements.
        self.orphaned = any(r.get("state") != "closed" for r in self.state["windows"].values())
        if self._resumable():
            self.epoch = self.state["controller"]["epoch"]
            self.orphaned = False
        elif not self.state.get("controller") and self.state.get("reconciliation", {}).get("epoch"):
            self.epoch = self.state["reconciliation"]["epoch"]
            self.orphaned = False  # Explicit grant committed before native session creation.

    def _resumable(self):
        controller = self.state.get("controller", {})
        try:
            return (controller.get("state") == "ready"
                    and process_generation(controller["pid"]) == controller["generation"])
        except (OSError, ValueError, KeyError, IndexError):
            return False

    def reconcile_generation(self, grant):
        """Local administrator-only transition, under the exclusive server lease.

        The grant is supplied by the operator after exact owner authorization,
        never accepted from the public bridge or inferred from recovery prose.
        Crash before the final journal commit leaves the old generation fenced.
        """
        with self.operation():
            if set(grant) not in ({"approval", "scope", "journal_sha256"},
                                  {"approval", "scope", "journal_sha256", "retire_unresolved"}):
                raise ValueError("exact scoped reconciliation grant required")
            exemptions = grant.get("retire_unresolved", [])
            if not isinstance(exemptions, list) or any(
                    not isinstance(e, dict) or set(e) != {"journal", "key_sha256", "record_sha256"}
                    or e["journal"] != "state.json"
                    or any(not isinstance(e[k], str) or not re.fullmatch(r"[a-f0-9]{64}", e[k])
                           for k in ("key_sha256", "record_sha256")) for e in exemptions):
                raise ValueError("exact historical legacy record fingerprints required")
            allowed = {(e["journal"], e["key_sha256"], e["record_sha256"]) for e in exemptions}
            if len(allowed) != len(exemptions):
                raise ValueError("duplicate historical retirement fingerprint")
            scope = valid_scope(grant["scope"])
            if scope == "owner" or not re.fullmatch(r"apr-[A-Za-z0-9_-]+", grant["approval"]):
                raise ValueError("exact request and owner approval receipt required")
            previous = self.state.get("reconciliation")
            if previous and previous.get("approval") == grant["approval"]:
                if (previous.get("scope") != scope or previous.get("journal_sha256") != grant["journal_sha256"]
                        or previous.get("retire_unresolved", []) != exemptions):
                    raise RuntimeError("conflicting reconciliation receipt")
                return  # Never retire the newly established generation twice.
            if previous or not self.orphaned or self._resumable() or self.browser is not None:
                raise RuntimeError("only an unconnected lost generation may be retired")
            if self.state["windows"].get(scope, {}).get("state") == "closed":
                raise RuntimeError("terminal acceptance scope cannot be reopened")
            journals = {p.name: p.read_bytes() for p in sorted(self.path.parent.glob("*.json"))}
            digest = hashlib.sha256(json.dumps({name: hashlib.sha256(raw).hexdigest()
                                               for name, raw in journals.items()}, sort_keys=True).encode()).hexdigest()
            if digest != grant["journal_sha256"] or json.loads(journals[self.path.name]) != self.state:
                raise RuntimeError("journal changed since the authorized safety read")
            retired_keys = set(self.legacy_keys)
            matched = set()
            for name, raw in journals.items():
                journal = json.loads(raw)
                retired_keys.update(journal.get("actions", {}))
                retired_keys.update(journal.get("action_keys", {}))
                for field in ("actions", "action_keys"):
                    for key, record in journal.get(field, {}).items():
                        if isinstance(record, dict) and record.get("state", record.get("delivery_state")) == "delivered":
                            continue
                        fingerprint = (name, hashlib.sha256(key.encode()).hexdigest(),
                                       hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest())
                        if (field != "action_keys" or not isinstance(record, dict)
                                or record.get("delivery_state") not in {"delivery_started", "delivery_uncertain"}
                                or fingerprint not in allowed):
                            raise RuntimeError("pending or uncertain input prevents reconciliation")
                        matched.add(fingerprint)
            if matched != allowed:
                raise RuntimeError("historical retirement records missing or changed")
            # Never end an existing native session just to make a new one fit.
            deadline = time.monotonic() + 5
            while True:
                try:
                    driver_ready = driver_request("GET", "/status").get("ready")
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.1)
            if driver_ready is not True:
                raise RuntimeError("native driver already occupied; preserve without session replacement")
            history = self.path.parent / "generation-history"
            history.mkdir(mode=0o700, exist_ok=True)
            archive = history / (digest + ".json")
            bundle = json.dumps({"grant": grant, "journals": {name: raw.decode("utf-8")
                                for name, raw in journals.items()}}, sort_keys=True).encode()
            try:
                fd = os.open(archive.with_suffix(".new"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(bundle)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.fchmod(stream.fileno(), 0o400)
                os.link(archive.with_suffix(".new"), archive)
            except FileExistsError:
                if archive.read_bytes() != bundle:
                    raise RuntimeError("immutable generation archive conflicts") from None
            finally:
                archive.with_suffix(".new").unlink(missing_ok=True)
            for directory_path in (history, self.path.parent):
                directory = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            retired = {key: record if record.get("state") == "closed" else {"state": "retired", "archive": archive.name}
                       for key, record in self.state["windows"].items()
                       if key not in {"owner", scope}}
            # Keep every action key non-replayable; full original bindings and
            # all journals are immutable history, not claimed as closed windows.
            replacement = {**self.state, "windows": retired, "retired_action_keys": sorted(retired_keys),
                           "reconciliation": {**grant, "epoch": self.epoch}}
            replacement.pop("controller", None)
            original = self.state
            self.state = replacement
            try:
                self._save()
            except BaseException:
                self.state = original
                self.broken = True
                raise
            self.orphaned = False
            self.broken = False
            self.legacy_keys.update(retired_keys)

    @contextlib.contextmanager
    def operation(self):
        # Covers owner-viewer and API clients alike; nested dispatch is reentrant.
        if not self.lock.acquire(timeout=5):
            raise ControlError("FIREFOX_BUSY", "resident controller busy; no operation started")
        try:
            yield
        finally:
            self.lock.release()

    def _connect(self):
        from secure_browser_local_bidi import CdpSession
        controller = self.state.get("controller")
        if controller:
            if not self._resumable():
                raise RuntimeError("resident native session identity lost; no replacement session")
        else:
            self.state["controller"] = {"state": "creating", "epoch": self.epoch}
            self._save()
            # Readiness reads may wait; session creation itself is sent ONCE.
            deadline = time.monotonic() + 5
            while True:
                try:
                    driver_request("GET", "/status")
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.1)
            created = driver_request("POST", "/session", {"capabilities": {"alwaysMatch": {"browserName": "firefox", "webSocketUrl": True}}})
            endpoint = created["capabilities"]["webSocketUrl"]
            validate_session_endpoint(created["sessionId"], endpoint)
            pid = created["capabilities"]["moz:processID"]
            controller = {"state": "ready", "epoch": self.epoch, "pid": pid, "generation": process_generation(pid),
                          "session": created["sessionId"], "endpoint": endpoint}
            self.state["controller"] = controller
            self._save()
        # Classic session owns identity. Closing this observer socket does not
        # call session.end or change native window/context IDs.
        validate_session_endpoint(controller["session"], controller["endpoint"])
        driver_request("GET", "/session/" + controller["session"] + "/window/handles")
        return CdpSession(websocket_url=controller["endpoint"])

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".new")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(self.state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.path)
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _call(self, method, params=None, *, on_reply=None):
        if self.broken and self._resumable():
            self.browser = None
            self.broken = False  # Reconnect identity, never replay the failed call.
        if self.broken or self.orphaned:
            raise ControlError("FIREFOX_IDENTITY_LOST", "window controller identity lost; preserved windows require explicit recovery; no replacement created")
        try:
            if self.browser is None:
                self.browser = self.connect()
            if on_reply is not None:
                return self.browser._bidi(method, params or {}, on_reply=on_reply)
            return self.browser._bidi(method, params or {})
        except BaseException as exc:
            if getattr(exc, "native_outcome", None) == "reply_pending":
                # Retain the sole observer and correlated callback for bounded
                # reconciliation. No command is replayed and no thread is added.
                raise ControlError("FIREFOX_NATIVE_OUTCOME_UNCERTAIN", "native creation reply pending; recover the retained observer; do not resend", "uncertain") from exc
            if on_reply is not None and getattr(exc, "native_outcome", None) == "not_started":
                raise ControlError("FIREFOX_CREATE_REJECTED", "creation was not sent; route to existing browser repair") from exc
            if on_reply is not None and getattr(exc, "native_code", None) in {
                    "invalid argument", "unsupported operation", "no such frame", "no such user context"}:
                raise ControlError("FIREFOX_CREATE_REJECTED", "native creation rejected without effect; route to existing browser repair") from exc
            # Never reconnect/retry a possibly delivered native operation.
            self.broken = True
            if self.browser is not None:
                try:
                    self.browser.close()
                except Exception:
                    pass
            if not isinstance(exc, Exception):
                raise
            raise ControlError("FIREFOX_NATIVE_OUTCOME_UNCERTAIN", "native window operation failed; preserve action key and window; read back before further input; no automatic retry", "uncertain") from exc

    def _tree(self):
        return self._call("browsingContext.getTree")["contexts"]

    def _visible_context(self, contexts):
        if len(contexts) == 1:
            return contexts[0]
        selected = []
        for context in contexts:
            result = self._call("script.evaluate", {
                "expression": 'document.visibilityState === "visible"',
                "target": {"context": context["context"], "sandbox": "nest-window-observation"},
                "awaitPromise": False, "resultOwnership": "none"})
            value = result.get("result") or {}
            if result.get("type") == "exception" or value.get("type") != "boolean":
                raise RuntimeError("bound-window tab visibility unavailable")
            if value.get("value") is True:
                selected.append(context)
        if len(selected) != 1:
            raise RuntimeError("selected context in bound window is ambiguous")
        return selected[0]

    def _resolve(self, record):
        if record.get("state") != "open" or record.get("epoch") != self.epoch:
            raise RuntimeError("window binding is closed or uncertain; refusing replacement")
        tree = self._tree()
        if record.get("owner"):
            selected = self._visible_context([c for c in tree if c.get("clientWindow") == record["window"]])
            if record["context"] != selected["context"]:
                record["context"] = selected["context"]
                self._save()
            return selected
        matches = [c for c in tree if c.get("context") == record["context"] and c.get("clientWindow") == record["window"]]
        if len(matches) != 1:
            raise RuntimeError("bound window identity changed; preserve without replacement")
        # Tabs moved into the window by an unrelated actor are not ours to close
        # or automatically select. Never infer a new selected context from URL.
        if [c["context"] for c in tree if c.get("clientWindow") == record["window"]] != [record["context"]]:
            raise RuntimeError("bound window contains unproven contexts; preserve and refuse input")
        return matches[0]

    def authorize_binding(self, grant):
        """Local operator only: admit one new binding, never replay an old create.

        Like reconcile_generation, this is not a public API. The administrator
        must independently verify the exact canonical nonterminal request and
        trusted proposal approval before supplying this short-lived grant.
        """
        with self.operation():
            if not isinstance(grant, dict) or set(grant) != {"approval", "scope", "archive", "epoch", "expires_at"}:
                raise ValueError("exact local binding recovery grant required")
            scope = valid_scope(grant["scope"])
            if (scope == "owner" or not isinstance(grant["approval"], str)
                    or not re.fullmatch(r"apr-[A-Za-z0-9_-]+", grant["approval"])
                    or type(grant["expires_at"]) is not int or grant["expires_at"] <= time.time()
                    or grant["epoch"] != self.epoch):
                raise ValueError("invalid or expired scoped binding recovery grant")
            record = self.state["windows"].get(scope, {})
            if record.get("terminal") or record.get("state") == "closed":
                raise RuntimeError("terminal scope cannot be reopened")
            previous = self.state.get("binding_recoveries", {}).get(scope)
            if previous:
                if previous != grant:
                    raise RuntimeError("conflicting binding recovery grant")
                return  # Includes an uncertain new creation: never send it twice.
            if (record.get("state") != "retired" or record.get("archive") != grant["archive"]
                    or not re.fullmatch(r"[a-f0-9]{64}\.json", str(grant["archive"]))):
                raise RuntimeError("grant does not identify the exact retired binding")
            if (self.orphaned or self.broken
                    or (self.state.get("controller") and not self._resumable())
                    or self.state.get("reconciliation", {}).get("epoch") != self.epoch):
                raise RuntimeError("current resident generation required for binding recovery")
            if any(r.get("state") != "delivered" for r in self.state["actions"].values()):
                raise RuntimeError("pending or uncertain input prevents binding recovery")
            archive = self.path.parent / "generation-history" / grant["archive"]
            bundle = json.loads(archive.read_bytes())
            original = json.loads(bundle["journals"][self.path.name])["windows"].get(scope)
            if not original or original.get("state") == "closed":
                raise RuntimeError("immutable history does not contain a recoverable binding")
            # Preserve both the tombstone provenance and the operator receipt.
            # Atomic commit precedes any later allocation by the normal caller.
            original_state = self.state
            self.state = {**self.state,
                          "binding_recoveries": {**self.state.get("binding_recoveries", {}), scope: dict(grant)},
                          "windows": {**self.state["windows"], scope: {**record, "state": "recovery_ready"}}}
            try:
                self._save()
            except BaseException:
                self.state = original_state
                raise

    def authorize_creation_recovery(self, grant):
        """Local administrator only, under a NEW exclusive controller lease.

        The operator must already have authority to abandon this exact missing
        receipt and allocate once. This is not a public bridge command, and the
        authorization label is provenance, not an approval-shaped capability.
        Unknown native windows remain untouched. Input keys remain fenced.
        """
        with self.operation():
            if not isinstance(grant, dict) or set(grant) != {
                    "scope", "authorization", "epoch", "creation_id", "journal_sha256", "expires_at"}:
                raise ValueError("exact local creation recovery grant required")
            scope = valid_scope(grant["scope"])
            if (scope == "owner" or not isinstance(grant["authorization"], str)
                    or not re.fullmatch(r"ar-[A-Za-z0-9_-]+", grant["authorization"])
                    or grant["epoch"] != self.epoch or type(grant["expires_at"]) is not int
                    or not time.time() < grant["expires_at"] <= time.time() + 600):
                raise ValueError("invalid scoped local creation recovery grant")
            previous = self.state.get("creation_recoveries", {}).get(scope)
            if previous:
                if previous["grant"] != grant:
                    raise RuntimeError("one bounded creation recovery per scope; no replacement loop")
                return  # Even if the new creation failed: never create twice.
            if self.browser is not None or not self._resumable() or self.orphaned:
                raise RuntimeError("new exclusive controller in the same native generation required")
            raw = self.path.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != grant["journal_sha256"]
                    or json.loads(raw) != self.state):
                raise RuntimeError("journal changed since scoped recovery safety read")
            record = self.state["windows"].get(scope, {})
            if (record.get("state") != "creating" or record.get("context") or record.get("terminal")
                    or record.get("epoch") != self.epoch or record.get("creation_id") != grant["creation_id"]):
                raise RuntimeError("exact nonterminal creation without native receipt required")
            if any(r.get("state") != "delivered" for r in self.state["actions"].values()):
                raise RuntimeError("pending or uncertain input prevents creation recovery")
            # Preserve full old provenance in the same atomic transaction as
            # the new admission. No old native identity is adopted or closed.
            original = self.state
            self.state = {**original,
                          "creation_recoveries": {**original.get("creation_recoveries", {}),
                                                 scope: {"grant": dict(grant), "original": dict(record)}},
                          "binding_recoveries": {**original.get("binding_recoveries", {}), scope: dict(grant)},
                          "windows": {**original["windows"], scope: {"state": "recovery_ready", "epoch": self.epoch,
                                                                    "abandoned_creation_id": record["creation_id"]}}}
            try:
                self._save()
            except BaseException:
                self.state = original
                raise

    def acquire(self, scope):
        valid_scope(scope)
        with self.lock:
            old = self.state["windows"].get(scope)
            if old and old.get("state") == "retired":
                raise ControlError("FIREFOX_BINDING_RETIRED", "old generation preserved in history; no replacement authorized")
            if old and old.get("state") == "recovery_ready":
                grant = self.state.get("binding_recoveries", {}).get(scope, {})
                if grant.get("epoch") != self.epoch or grant.get("expires_at", 0) <= time.time():
                    raise ControlError("FIREFOX_BINDING_RETIRED", "binding recovery grant expired; no replacement authorized")
                if any(r.get("state") != "delivered" for r in self.state["actions"].values()):
                    raise RuntimeError("pending or uncertain input prevents binding recovery")
                old = None  # New reservation below, not a retry of the archived create.
            if old:
                if old.get("state") == "creating":
                    return self._finish_creation(old)
                if old.get("state") == "create_failed":
                    raise ControlError("FIREFOX_CREATE_REJECTED", "native creation was rejected without effect; inspect lifecycle status and route to browser repair")
                self._resolve(old)
                return old
            if self.broken or self.orphaned:
                self._tree()  # Fail before reserving another creation.
            tree = self._tree()
            if scope == "owner":
                # Reserve the pre-existing active owner window once, before
                # creating any background AR windows. Never map URLs/titles.
                if len(tree) == 1 and tree[0].get("clientWindow"):
                    context = tree[0]
                else:
                    active = [w["clientWindow"] for w in self._call("browser.getClientWindows").get("clientWindows", []) if w.get("active") is True]
                    if len(active) != 1 or any(r.get("window") == active[0] for r in self.state["windows"].values()):
                        raise RuntimeError("root owner identity is ambiguous; no window selected")
                    context = self._visible_context([c for c in tree if c.get("clientWindow") == active[0]])
            else:
                if "owner" not in self.state["windows"]:
                    self.acquire("owner")
                if (sum(r.get("state") not in {"closed", "retired"} for r in self.state["windows"].values()) >= 12
                        or len({c["clientWindow"] for c in tree if c.get("clientWindow")}) >= 12):
                    raise RuntimeError("owned window budget reached; no replacement created")
                record = {"state": "creating", "epoch": self.epoch, "creation_id": secrets.token_hex(24),
                          "prior_windows": sorted({c["clientWindow"] for c in tree if c.get("clientWindow")})}
                self.state["windows"][scope] = record
                self._save()
                def receipt(reply):
                    # Only a transport-correlated native response can supply
                    # ownership, never URL/title or tree differences.
                    before = dict(record)
                    if reply.get("type") == "error" or "error" in reply:
                        code = reply.get("error")
                        record["native_error"] = code if code in {
                            "invalid argument", "unsupported operation", "no such frame", "no such user context", "unknown error"} else "other_native_error"
                        if code in {"invalid argument", "unsupported operation", "no such frame", "no such user context"}:
                            record.update(state="create_failed", native_error=code)
                    else:
                        context = (reply.get("result") or {}).get("context")
                        if isinstance(context, str) and context:
                            record["context"] = context
                    record["native_receipt_id"] = reply.get("id")
                    try:
                        self._save()
                    except BaseException:
                        record.clear()
                        record.update(before)
                        raise
                try:
                    self._call("browsingContext.create", {"type": "window", "background": True}, on_reply=receipt)
                except ControlError as exc:
                    cause = exc.__cause__
                    # Privacy-safe phase evidence, never native messages.
                    phase = getattr(cause, "native_outcome", None)
                    record["creation_outcome"] = phase or "transport_or_native_failure"
                    if phase == "not_started":
                        record.update(state="create_failed", native_error="transport_not_sent")
                    if phase == "reply_pending":
                        record["command_id"] = getattr(cause, "command_id", None)
                    with contextlib.suppress(OSError):
                        self._save()  # Diagnostics do not replace the original failure.
                    raise
                return self._finish_creation(record)
            record = {"state": "open", "epoch": self.epoch, "context": context["context"],
                      "window": context["clientWindow"], "viewer": secrets.token_urlsafe(32), "owner": scope == "owner"}
            self.state["windows"][scope] = record
            self._save()
            return record

    def _finish_creation(self, record):
        if not record.get("context") or record.get("epoch") != self.epoch or "prior_windows" not in record:
            raise ControlError("FIREFOX_CREATION_UNCERTAIN", "window creation has no retained native identity; preserve windows; explicit recovery required", "uncertain")
        deadline = time.monotonic() + 2
        while True:
            candidates = [c for c in self._tree() if c["context"] == record["context"]]
            if len(candidates) == 1 and candidates[0].get("clientWindow"):
                window = candidates[0]["clientWindow"]
                if window in record["prior_windows"]:
                    break
                record.update(state="open", window=window, viewer=secrets.token_urlsafe(32), owner=False)
                record.pop("prior_windows")
                self._save()
                return record
            if time.monotonic() >= deadline:
                break
            time.sleep(.05)
        raise ControlError("FIREFOX_CREATION_UNCERTAIN", "retained window creation is not yet proven; no replacement or replay permitted", "uncertain")

    def recovery(self, scope, *, reconcile=False):
        """Finite reconciliation; never allocate, infer ownership or replay."""
        valid_scope(scope)
        record = self.state["windows"].get(scope)
        state = record.get("state") if record else "unallocated"
        result = {"scope_state": state, "retry_allowed": False, "input_replay_allowed": False}
        if record and record.get("terminal") and state in {"retired", "recovery_ready"}:
            return {**result, "recovery_state": "terminal_binding_preserved", "next_action": "none",
                    "reason": "terminal_scope_fenced", "new_binding_allowed": False}
        if state == "recovery_ready":
            grant = self.state.get("binding_recoveries", {}).get(scope, {})
            if (grant.get("epoch") == self.epoch and grant.get("expires_at", 0) > time.time()
                    and not self.orphaned and not self.broken
                    and all(r.get("state") == "delivered" for r in self.state["actions"].values())
                    and (not self.state.get("controller") or self._resumable())):
                return {**result, "recovery_state": "fresh_binding_authorized", "next_action": "acquire",
                        "reason": "scoped_operator_grant", "new_binding_allowed": True}
            return {**result, "recovery_state": "scoped_authorization_required", "next_action": "verify_existing_approval_and_apply_local_binding_grant",
                    "reason": "binding_grant_expired_or_generation_lost", "automatic_recovery_exhausted": True}
        if state == "retired":
            return {**result, "recovery_state": "scoped_authorization_required", "next_action": "verify_existing_approval_and_apply_local_binding_grant",
                    "reason": "binding_retired_with_history", "automatic_recovery_exhausted": True}
        if not record or state == "closed":
            return {**result, "recovery_state": "not_needed", "next_action": "acquire" if not record else "none"}
        if (record.get("epoch") != self.epoch or self.orphaned
                or (self.state.get("controller") and not self._resumable())):
            return {**result, "recovery_state": "owner_reconciliation_required", "next_action": "preserve_windows_and_request_scoped_owner_decision",
                    "reason": "native_generation_lost", "automatic_recovery_exhausted": True}
        if state == "create_failed":
            return {**result, "recovery_state": "engineering_repair_required", "next_action": "route_to_existing_browser_repair",
                    "reason": "native_create_rejected_without_effect", "outcome": "not_started", "automatic_recovery_exhausted": True}
        if state == "creating":
            if (reconcile and not record.get("context") and self.browser is not None
                    and getattr(self.browser, "pending", None) is not None):
                try:
                    self.browser.drain_pending()
                except TimeoutError:
                    # One extra bounded receipt wait, not an indefinite loop.
                    self.browser.close()
                    self.broken = True
                    return {**result, "recovery_state": "engineering_repair_required", "next_action": "route_to_existing_browser_repair",
                            "reason": "correlated_reply_wait_exhausted", "outcome": "uncertain", "automatic_recovery_exhausted": True}
                except Exception:
                    return {**result, "recovery_state": "engineering_repair_required", "next_action": "route_to_existing_browser_repair",
                            "reason": "creation_receipt_unavailable", "outcome": "uncertain", "automatic_recovery_exhausted": True}
            if not record.get("context"):
                return {**result, "recovery_state": "engineering_repair_required", "next_action": "route_to_existing_browser_repair",
                        "reason": "creation_reply_not_retained", "outcome": "uncertain", "automatic_recovery_exhausted": True}
            if not reconcile:
                return {**result, "recovery_state": "reconcile_available", "next_action": "recover"}
            try:
                self._finish_creation(record)
            except ControlError:
                return {**result, "recovery_state": "engineering_repair_required", "next_action": "route_to_existing_browser_repair",
                        "reason": "retained_creation_not_verified", "outcome": "uncertain", "automatic_recovery_exhausted": True}
            result["scope_state"] = record["state"]
        if record["state"] == "open":
            if reconcile:
                self._resolve(record)
            return {**result, "recovery_state": "verified" if reconcile else "not_needed", "next_action": "read_back_before_input"}
        return {**result, "recovery_state": "engineering_repair_required", "next_action": "route_to_existing_browser_repair",
                "reason": "terminal_close_pending", "automatic_recovery_exhausted": True}

    def lifecycle(self, payload):
        scope = valid_scope(payload.get("scope"))
        event = payload.get("terminal_event_id")
        status = payload.get("terminal_status")
        if scope == "owner" or payload.get("action") != "close" or type(event) is not int or event <= 0 or status not in TERMINAL:
            raise ValueError("exact terminal window close required; owner window cannot close")
        with self.lock:
            record = self.state["windows"].get(scope)
            receipt = {"status": "ok", "action": "close", "scope": scope,
                       "terminal_event_id": event, "terminal_status": status}
            terminal = {"event": event, "status": status}
            if record and record.get("terminal") and record["terminal"] != terminal:
                raise RuntimeError("terminal event conflicts with retained exact scope receipt")
            if record is None:
                # No browser operation has ever reserved this exact scope.
                self.state["windows"][scope] = {"state": "closed", "terminal": terminal}
                self._save()
                return {**receipt, "already_closed": True}
            if record["state"] == "closed":
                if record.get("terminal") != terminal:
                    raise RuntimeError("closed scope lacks the exact terminal receipt")
                return {**receipt, "already_closed": True}
            if record.get("state") in {"retired", "recovery_ready"}:
                # Retain terminal fencing without claiming the unknown old
                # native window was closed. The outbox stays unacknowledged.
                record.update(state="retired", terminal=terminal)
                self._save()
                raise RuntimeError("retired native window preserved; terminal scope fenced")
            # An interrupted close is reconciled only in the retained native
            # session, including an observer restored to that exact session.
            if record["state"] == "closing" and record.get("epoch") == self.epoch:
                if not any(c.get("clientWindow") == record["window"] for c in self._tree()):
                    record["state"] = "closed"
                    self._save()
                    return {**receipt, "already_closed": True}
                raise RuntimeError("window close uncertain; preserved without replay")
            if record.get("state") == "create_failed":
                record.update(state="closed", terminal=terminal)
                self._save()
                return {**receipt, "already_closed": True}
            if record.get("state") == "creating":
                self._finish_creation(record)
            self._resolve(record)
            record.update(state="closing", terminal=terminal)
            self._save()
            self._call("browsingContext.close", {"context": record["context"], "promptUnload": False})
            if any(c.get("clientWindow") == record["window"] for c in self._tree()):
                raise RuntimeError("window remains after close; no closure acknowledgement")
            record["state"] = "closed"
            self._save()
            return {**receipt, "closed": True}

    def _evaluate(self, context, expression):
        import secure_browser_bidi as observation
        reply = self._call("script.evaluate", {"expression": expression, "target": {"context": context}, "awaitPromise": True})
        if reply.get("type") == "exception":
            raise RuntimeError("bounded page observation unavailable")
        return observation.legacy.CdpSession._bidi_value(reply.get("result") or {})

    def _function(self, context, declaration, arguments):
        reply = self._call("script.callFunction", {"functionDeclaration": declaration, "target": {"context": context},
                           "awaitPromise": True, "arguments": arguments, "resultOwnership": "none"})
        if reply.get("type") == "exception":
            raise RuntimeError("window target unavailable or protected")
        return reply.get("result") or {}

    def _shot(self, context):
        return self._call("browsingContext.captureScreenshot", {"context": context, "origin": "viewport"})["data"]

    def _pointer(self, context, x, y):
        if not all(type(n) in {int, float} and 0 <= n <= 16384 for n in (x, y)):
            raise ValueError("invalid viewport coordinate")
        self._call("input.performActions", {"context": context, "actions": [{"type": "pointer", "id": "window-pointer", "parameters": {"pointerType": "mouse"},
                    "actions": [{"type": "pointerMove", "x": int(x), "y": int(y), "origin": "viewport"},
                                {"type": "pointerDown", "button": 0}, {"type": "pointerUp", "button": 0}]}]})

    def _keys(self, context, text):
        self._call("input.performActions", {"context": context, "actions": [{"type": "key", "id": "window-keyboard",
                    "actions": [action for character in text for action in ({"type": "keyDown", "value": character}, {"type": "keyUp", "value": character})]}]})

    def _text_character(self, context, character):
        if character == "\n":
            # Public multiline text is not a Send action. Use the ordinary
            # multiline gesture, never an unmodified Enter or a Tab focus move.
            self._call("input.performActions", {"context": context, "actions": [{"type": "key", "id": "window-keyboard", "actions": [
                {"type": "keyDown", "value": "\ue008"}, {"type": "keyDown", "value": "\ue007"},
                {"type": "keyUp", "value": "\ue007"}, {"type": "keyUp", "value": "\ue008"}]}]})
        else:
            self._keys(context, character)

    def dispatch(self, command, payload):
        scope = valid_scope(payload.get("scope"))
        with self.lock:
            if command in {"status", "diagnostics"} or (command == "tabs" and payload.get("action", "status") in {"status", "recover"}):
                # Observation must not create a window (or orphan a scope).
                recovery = self.recovery(scope, reconcile=command == "tabs" and payload.get("action") == "recover")
                available = recovery.get("reason") not in {
                    "native_generation_lost", "creation_reply_not_retained", "creation_receipt_unavailable", "correlated_reply_wait_exhausted"}
                if available:
                    self._tree()
                return {"status": "ok", "scope": scope, "protocol": "firefox-windows-v3",
                        "launch_protocol": "firefox-windows-v3", "bidi_available": available,
                        "native_element_available": available,
                        "browser_generation": self.epoch,
                        "window_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        "scope_state": self.state["windows"].get(scope, {}).get("state", "unallocated"),
                        "session_contract": "one bridge-owned classic session; serialized commands; reconnect observer only",
                        "recovery": recovery}
            record = self.acquire(scope)
            context = self._resolve(record)
            cid = context["context"]
            common = {"status": "ok", "scope": scope, "protocol": "firefox-windows-v3", "browser_generation": self.epoch,
                      "window_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "owner_window_url": "/_nest/bridge/window/#" + record["viewer"], "tab_count": 1,
                      "observation_boundary": "bound native Firefox window viewport; no global desktop capture or focus"}
            if command == "tabs":
                if payload.get("action", "status") not in {"status", "acquire", "keep_open", "release"}:
                    raise ValueError("window recovery never creates replacements; terminal broker hook owns closure")
                # release is intentionally NOT terminal. Blocked/waiting scopes
                # and their owner URL survive worker exit and lease expiration.
                return {**common, "retained": True, "lifecycle": "canonical terminal hook only"}
            if command == "navigate":
                url = payload.get("url", "")
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("navigation requires a credential-free HTTP(S) URL")
                self._call("browsingContext.navigate", {"context": cid, "url": url, "wait": "complete"})
                self._resolve(record)
                return {**common, "readback": self._summary(cid)}
            if command == "screenshot":
                data = self._shot(cid)
                self._resolve(record)
                return {**common, "png_base64": data, "capture_mode": "bound native window viewport", "full_page": False}
            if command in {"snapshot", "wait", "query"}:
                if command == "query":
                    result = self._query(cid, payload.get("expression", ""), payload.get("cursor"))
                    self._resolve(record)
                    return {**common, **result}
                snapshot = self._snapshot(cid)
                if command == "wait":
                    budget = payload.get("max_wait_seconds", 6)
                    if type(budget) not in {int, float} or not 0 <= budget <= 15:
                        raise ValueError("wait budget must be between zero and fifteen seconds")
                    deadline = time.monotonic() + budget
                    stable = False
                    while time.monotonic() < deadline:
                        time.sleep(min(.25, max(0, deadline - time.monotonic())))
                        current = self._snapshot(cid)
                        if current == snapshot:
                            stable = True
                            break
                        snapshot = current
                    snapshot.update(stable=stable, stability_boundary="unchanged bounded DOM observation, not application completion")
                self._resolve(record)
                return {**common, **snapshot, "tabs": [{"selected": True, "name": snapshot["title"], "locator": "window:" + self.epoch}]}
            if command == "checkout_readback":
                # Reuse the existing pure sanitized readback parser. Never use
                # its global OS observation/input functions in window mode.
                spec = importlib.util.spec_from_file_location("window_readback", Path(__file__).with_name("firefox-ui-bridge.py"))
                ui = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(ui)
                snapshot = self._snapshot(cid)
                result = ui._commerce_readback(snapshot, payload)
                self._resolve(record)
                return {**result, **common, "source": "filtered native DOM viewport readback"}
            if command == "scroll":
                amount = payload.get("amount", 1)
                if type(amount) not in {int, float} or not 0 < amount <= 10 or payload.get("direction", "down") not in {"up", "down"}:
                    raise ValueError("bounded vertical scroll required")
                self._call("input.performActions", {"context": cid, "actions": [{"type": "wheel", "id": "window-wheel", "actions": [{
                    "type": "scroll", "x": 10, "y": 10, "deltaX": 0, "deltaY": int(500 * amount) * (-1 if payload.get("direction") == "up" else 1), "duration": 100}]}]})
                return {**common, "readback": self._summary(cid)}
            if command in {"click", "type", "selector_action"}:
                return self._input(command, payload, record, common)
            raise ValueError("unsupported window operation; no legacy global-input fallback")

    def _query(self, cid, expression, cursor=None):
        import secure_browser_bidi as observation
        if not isinstance(expression, str) or not 0 < len(expression) <= observation.MAX_EXPRESSION_CHARS:
            raise ValueError("bounded direct read expression required")
        script = observation._read_script(expression)
        text_read = bool(observation.TEXT_EXPRESSION.fullmatch(expression))
        if cursor is not None and not text_read:
            raise ValueError("cursor requires document.readText")
        raw = self._evaluate(cid, script)
        if text_read:
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str) or len(raw["text"]) > observation.MAX_TEXT_CHARS:
                raise ValueError("bounded text observation unavailable")
            # Redact before paging so a value cannot escape across boundaries.
            text = observation.PRIVATE_VALUE.sub("<redacted>", raw["text"])
            text = observation.POTENTIAL_CODE.sub("<redacted>", observation.VERIFICATION_VALUE.sub(r"\1<redacted>", text))
            revision = hashlib.sha256(json.dumps([self.epoch, cid, expression, raw.get("epoch"), raw.get("url"), text], sort_keys=True).encode()).hexdigest()
            offset = 0
            if cursor is not None:
                if (not isinstance(cursor, dict) or set(cursor) != {"revision", "offset"} or cursor.get("revision") != revision
                        or type(cursor.get("offset")) is not int or not 0 < cursor["offset"] < len(text)):
                    raise ValueError("stale text cursor; restart the element read")
                offset = cursor["offset"]
            end = min(len(text), offset + observation.TEXT_PAGE_CHARS)
            return {"value": {"text": text[offset:end], "total": raw.get("total"), "offset": offset, "totalChars": len(text)},
                    "revision": revision, "complete": end == len(text), "truncated": end < len(text),
                    "redacted": bool(raw.get("redacted")) or text != raw["text"],
                    "nextCursor": None if end == len(text) else {"revision": revision, "offset": end}}
        value = observation._safe_result(raw)
        return {"value": value, "truncated": bool(isinstance(raw, dict) and (
                raw.get("nextOffset") is not None if "nextOffset" in raw else
                isinstance(raw.get("total"), int) and raw["total"] > len(raw.get("values", []))))}

    def _snapshot(self, cid):
        result = self._query(cid, "document.domSnapshot")
        value = result["value"]
        nodes = []
        for row in value.get("nodes", []) if isinstance(value, dict) else []:
            if not row.get("visible"):
                continue
            control = row.get("control") or {}
            nodes.append({**row, "name": row.get("label") or row.get("text") or "",
                          "role": row.get("role") or ("entry" if control else row.get("tag")),
                          "value": control.get("value"), "states": ["showing"] + (["checked"] if control.get("checked") else [])})
        return {**self._summary(cid), "nodes": nodes, "value": value, "truncated": result["truncated"]}

    def _summary(self, cid):
        import secure_browser_bidi as observation
        # Export only origin/path, never URL query, fragment or credentials.
        raw = self._evaluate(cid, "({title:document.title,url:location.origin+location.pathname})")
        return observation._safe_result(raw)

    def _input(self, command, payload, record, common):
        operation = payload.get("operation") if command == "selector_action" else command
        key = payload.get("action_key")
        if operation not in {"click", "type"} or not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ValueError("window input requires a stable action key")
        if key in self.legacy_keys:
            raise RuntimeError("action key belongs to preserved legacy journal; no replay in a new window")
        if payload.get("expected_generation") not in {None, self.epoch}:
            raise RuntimeError("stale window generation")
        cid = record["context"]
        if payload.get("expected_url") not in {None, self._summary(cid)["url"]}:
            raise RuntimeError("window URL changed before input")
        digest = hashlib.sha256(json.dumps({"operation": operation, "payload": {
            k: v for k, v in payload.items() if k not in {"expected_tab", "expected_url", "expected_generation"}}}, sort_keys=True).encode()).hexdigest()
        prior = self.state["actions"].get(key)
        if prior:
            if prior.get("digest") != digest or prior.get("scope") != payload["scope"]:
                raise ValueError("action key already bound to a different input")
            verified = prior["state"] == "delivered"
            return {**common, "status": "already_readback_confirmed" if verified and operation == "type" else "already_delivered" if verified else "delivery_uncertain",
                    "action_key": key, "delivery": {"input_sent": False, "state": prior["state"], "replay_blocked": True,
                    "dom_value_confirmed": verified if operation == "type" else None, "visible_value_confirmed": None}}
        selector = payload.get("selector")
        coordinate = payload.get("coordinate")
        if payload.get("locator") or (not selector and not isinstance(coordinate, dict)):
            raise ValueError("use a CSS selector or viewport coordinate in the bound window; legacy AX locators cannot cross the boundary")
        if selector and (not isinstance(selector, str) or len(selector) > 512):
            raise ValueError("bounded CSS selector required")
        from secure_browser_local_bidi import CdpSession
        coord = coordinate or {}
        args = [{"type": "string", "value": selector} if selector else {"type": "null"},
                {"type": "number", "value": coord.get("x", 0)}, {"type": "number", "value": coord.get("y", 0)}]
        target = self._function(cid, ELEMENT, args)
        values = {k: v for k, v in target.get("value", [])}
        node = values.get("node", {})
        if not node.get("sharedId"):
            raise RuntimeError("native element identity unavailable")
        element = {"sharedId": node["sharedId"]}
        details = CdpSession._bidi_value(target)
        if details.get("protected"):
            raise ValueError("protected field requires owner interaction through the window URL")
        text = payload.get("text", "")
        mode = payload.get("mode", "insert")
        if mode not in {"insert", "replace"} or (operation == "type" and (not isinstance(text, str) or not 1 <= len(text) <= 4096 or not details.get("editable"))):
            raise ValueError("bounded public editable text and valid mode required")
        if operation == "type" and any((ord(c) < 32 and c != "\n") or 0xe000 <= ord(c) <= 0xf8ff for c in text):
            raise ValueError("control characters and native special keys cannot be passed as public text")
        if operation == "type" and "\n" in text and not details.get("multiline"):
            raise ValueError("multiline public text requires a multiline editable target")
        focused = CdpSession._bidi_value(self._function(cid, FIELD, [element])) if operation == "type" else {}
        self._resolve(record)
        self.state["actions"][key] = {"scope": payload["scope"], "digest": digest, "state": "started"}
        self._save()
        # A click in an already active textarea moves its caret/selection.
        # Ordinary continued entry must preserve it, not insert at the center.
        if not focused.get("active"):
            self._pointer(cid, details["x"], details["y"])
        confirmed = operation == "click"
        if operation == "type":
            before = CdpSession._bidi_value(self._function(cid, FIELD, [element]))
            expected = None
            if before.get("active") and isinstance(before.get("value"), str):
                start, end = before.get("start"), before.get("end")
                if mode == "replace":
                    expected = text
                elif type(start) is int and type(end) is int and all(ord(c) <= 0xffff for c in before["value"]):
                    expected = before["value"][:start] + text + before["value"][end:]
            if not before.get("active"):
                raise RuntimeError("target did not become active inside its own window; no typing delivered")
            if mode == "replace":
                self._call("input.performActions", {"context": cid, "actions": [{"type": "key", "id": "window-keyboard", "actions": [
                    {"type": "keyDown", "value": "\ue009"}, {"type": "keyDown", "value": "a"},
                    {"type": "keyUp", "value": "a"}, {"type": "keyUp", "value": "\ue009"}]}]})
            for character in text:
                self._text_character(cid, character)
                self._evaluate(cid, "new Promise(resolve=>setTimeout(()=>resolve(true),100))")
            after = CdpSession._bidi_value(self._function(cid, FIELD, [element]))
            confirmed = expected is not None and after.get("value") == expected and after.get("active") and after.get("visible")
        self._resolve(record)
        self.state["actions"][key]["state"] = "delivered" if confirmed else "uncertain"
        self._save()
        return {**common, "status": "input_readback_confirmed" if confirmed and operation == "type" else "delivered" if confirmed else "delivery_uncertain",
                "action_key": key, "delivery": {"input_sent": True, "state": "delivered" if confirmed else "uncertain",
                "dom_value_confirmed": bool(confirmed) if operation == "type" else None, "visible_value_confirmed": None,
                "confirmation_boundary": "native element value, active state and geometry; screenshot text not independently matched"},
                "readback": self._summary(cid)}

    def viewer_scope(self, capability):
        # Capabilities are not scope selectors and are never exported in logs.
        with self.lock:
            matches = [scope for scope, record in self.state["windows"].items()
                       if record.get("state") == "open" and secrets.compare_digest(record.get("viewer", ""), capability)]
            if len(matches) != 1:
                raise ValueError("window viewer unavailable")
            self._resolve(self.state["windows"][matches[0]])
            return matches[0]

    def owner_input(self, capability, payload):
        # Separate owner-facing UI path, not an agent secret typing/export API.
        with self.lock:
            scope = self.viewer_scope(capability)
            record = self.state["windows"][scope]
            context = record["context"]
            if payload.get("kind") == "pointer" and set(payload) == {"kind", "x", "y"}:
                self._pointer(context, payload["x"], payload["y"])
            elif payload.get("kind") == "scroll" and set(payload) == {"kind", "x", "y", "deltaX", "deltaY"}:
                if any(type(payload[k]) is not int or not 0 <= payload[k] <= 8192 for k in ["x", "y"]):
                    raise ValueError("bounded owner viewport coordinates required")
                if any(type(payload[k]) is not int or not -2000 <= payload[k] <= 2000 for k in ["deltaX", "deltaY"]):
                    raise ValueError("bounded owner scroll required")
                self._call("input.performActions", {"context": context, "actions": [{"type": "wheel", "id": "window-wheel", "actions": [{
                    "type": "scroll", "x": payload["x"], "y": payload["y"], "deltaX": payload["deltaX"], "deltaY": payload["deltaY"], "duration": 100}]}]})
            elif payload.get("kind") == "key" and set(payload) == {"kind", "key"}:
                key = payload["key"]
                special = {"Enter": "\ue007", "Backspace": "\ue003", "Tab": "\ue004", "Escape": "\ue00c", "ArrowLeft": "\ue012", "ArrowRight": "\ue014", "ArrowUp": "\ue013", "ArrowDown": "\ue015", "Delete": "\ue017"}
                if not isinstance(key, str) or (len(key) != 1 and key not in special):
                    raise ValueError("unsupported owner key")
                self._keys(context, special.get(key, key))
            else:
                raise ValueError("unsupported owner window input")
            self._resolve(record)
            return {"status": "ok"}
