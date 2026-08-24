#!/usr/bin/env python3
"""Sanitized synthetic smoke checks for Pattern Kit Eyrie surfaces."""

from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

STUDIO = os.environ["PATTERNKIT_URL"].rstrip("/")
WORKBENCH = os.environ["PATTERNKIT_WORKBENCH_URL"].rstrip("/")
WORKBENCH_BRIDGE = os.environ["PATTERNKIT_WORKBENCH_BRIDGE_URL"].rstrip("/")
TOKEN = os.environ["PATTERNKIT_SMOKE_TOKEN"]
EXPECTED_PATTERNKIT = os.environ["PATTERNKIT_EXPECTED_REVISION"]
EXPECTED_ATELIER = os.environ["PATTERNKIT_ATELIER_EXPECTED_REVISION"]
EXPECTED_SESSION_CREATED_AT = os.environ.get("PATTERNKIT_EXPECTED_SESSION_CREATED_AT")
HOT_RELOAD_PATH = os.environ.get("PATTERNKIT_HOT_RELOAD_PATH")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


context = ssl.create_default_context()
no_redirect = build_opener(HTTPSHandler(context=context), NoRedirect())
normal = build_opener(HTTPSHandler(context=context))
checks: dict[str, object] = {}


def request(
    url: str,
    *,
    authenticated: bool = False,
    bridge_authenticated: bool = False,
    follow: bool = True,
) -> tuple[int, bytes, dict[str, str]]:
    headers = {"Accept": "application/json, text/html;q=0.9"}
    if authenticated:
        headers["X-PatternKit-Smoke-Token"] = TOKEN
    if bridge_authenticated:
        headers["X-PatternKit-Bridge-Token"] = TOKEN
    opener = normal if follow else no_redirect
    try:
        with opener.open(Request(url, headers=headers), timeout=30) as response:
            return response.status, response.read(), dict(response.headers)
    except HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def verify_hot_reload() -> float:
    if not HOT_RELOAD_PATH:
        return 0.0
    stream = normal.open(
        Request(
            STUDIO + "/api/session/events?name=deployment-smoke",
            headers={"Accept": "text/event-stream", "X-PatternKit-Smoke-Token": TOKEN},
        ),
        timeout=30,
    )
    closed = threading.Event()

    def watch_for_close() -> None:
        try:
            while stream.read(4096):
                pass
            closed.set()
        except OSError:
            closed.set()

    reader = threading.Thread(target=watch_for_close, daemon=True)
    reader.start()
    started = time.monotonic()
    os.utime(Path(HOT_RELOAD_PATH))
    if not closed.wait(20):
        stream.close()
        raise SystemExit("Studio event stream did not close after a source change")
    for _attempt in range(100):
        status, _, _ = request(STUDIO + "/api/health", authenticated=True)
        if status == 200:
            return time.monotonic() - started
        time.sleep(0.1)
    raise SystemExit("Studio did not recover after source hot reload")


for name, base in (("studio", STUDIO), ("workbench", WORKBENCH)):
    status, _, headers = request(base + "/", follow=False)
    checks[f"{name}_unauth_status"] = status
    if status != 302 or "gitlab.joyfullee.me/oauth/authorize" not in headers.get("location", ""):
        raise SystemExit(f"{name} did not enforce GitLab OAuth: {json.dumps(checks, sort_keys=True)}")

status, body, _ = request(STUDIO + "/", authenticated=True)
checks["studio_status"] = status
if status != 200 or b"Pattern Kit Studio" not in body:
    raise SystemExit(f"Studio wrapper failed: {json.dumps(checks, sort_keys=True)}")

status, body, _ = request(STUDIO + "/api/catalog", authenticated=True)
checks["catalog_status"] = status
catalog = json.loads(body) if status == 200 else {}
targets = json.dumps(catalog, sort_keys=True).lower()
checks["atelier_catalog_visible"] = "catsuit" in targets or "atelier" in targets
if status != 200 or not checks["atelier_catalog_visible"]:
    raise SystemExit(f"Atelier catalog check failed: {json.dumps(checks, sort_keys=True)}")

status, body, _ = request(STUDIO + "/api/session?name=deployment-smoke", authenticated=True)
checks["session_status"] = status
session = json.loads(body) if status == 200 else {}
checks["session_schema"] = session.get("schema")
checks["session_revision"] = session.get("revision")
checks["session_created_at"] = session.get("created_at")
if status != 200 or session.get("schema") != 1 or session.get("name") != "deployment-smoke":
    raise SystemExit(f"Persistent collaboration session check failed: {json.dumps(checks, sort_keys=True)}")
if EXPECTED_SESSION_CREATED_AT is not None and str(session.get("created_at")) != EXPECTED_SESSION_CREATED_AT:
    raise SystemExit(f"Collaboration session did not survive restart: {json.dumps(checks, sort_keys=True)}")

status, body, _ = request(STUDIO + "/__patternkit/status", authenticated=True)
checks["revision_status"] = status
revision_status = json.loads(body) if status == 200 else {}
checks["studio_node"] = revision_status.get("node")
revisions = {item.get("path", "").rstrip("/").split("/")[-1]: item.get("revision") for item in revision_status.get("repositories", [])}
checks["patternkit_revision"] = revisions.get("patternkit")
checks["atelier_revision"] = revisions.get("patternkit-atelier")
if revision_status.get("node") != "owl" or revisions.get("patternkit") != EXPECTED_PATTERNKIT or revisions.get("patternkit-atelier") != EXPECTED_ATELIER:
    raise SystemExit(f"Source revision mismatch: {json.dumps(checks, sort_keys=True)}")

if HOT_RELOAD_PATH:
    checks["hot_reload_seconds"] = round(verify_hot_reload(), 3)

status, body, _ = request(WORKBENCH + "/", authenticated=True)
checks["workbench_status"] = status
if status != 200 or b"KasmVNC" not in body:
    raise SystemExit(f"Workbench failed: {json.dumps(checks, sort_keys=True)}")

status, _, _ = request(WORKBENCH_BRIDGE + "/status")
checks["workbench_bridge_unauth_status"] = status
if status != 403:
    raise SystemExit(f"Workbench bridge did not reject an unauthenticated caller: {json.dumps(checks, sort_keys=True)}")

status, body, _ = request(WORKBENCH_BRIDGE + "/status", bridge_authenticated=True)
binding = json.loads(body) if status == 200 else {}
checks["workbench_binding_status"] = status
checks["workbench_binding_reason"] = binding.get("reason")
checks["workbench_active_context_verified"] = binding.get("active_context_verified")
checks["workbench_isolated_browser_verified"] = binding.get("isolated_browser_verified")
if (
    status != 200
    or binding.get("schema") != "patternkit.workbench.binding/v1"
    or binding.get("reason") not in {"verified-active-tab", "explicit-share-required"}
    or bool(binding.get("bound")) != bool(binding.get("active_context_verified"))
    or bool(binding.get("bound")) != bool(binding.get("patternkit_origin_verified"))
    or bool(binding.get("bound")) != bool(binding.get("isolated_browser_verified"))
):
    raise SystemExit(f"Workbench identity check failed: {json.dumps(checks, sort_keys=True)}")

status, body, _ = request(WORKBENCH_BRIDGE + "/synthetic-contract", bridge_authenticated=True)
contract = json.loads(body) if status == 200 else {}
checks["workbench_contract_status"] = status
checks["workbench_contract_cases"] = contract.get("cases")
if status != 200 or contract.get("schema") != "patternkit.workbench.synthetic-contract/v1" or not contract.get("ok"):
    raise SystemExit(f"Workbench fail-closed lifecycle contract failed: {json.dumps(checks, sort_keys=True)}")

print(json.dumps({"ok": True, **checks}, sort_keys=True))
