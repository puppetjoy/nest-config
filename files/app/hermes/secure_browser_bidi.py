"""Private Firefox BiDi page inspection for the visible secure-browser workflow.

This module does not create tabs or navigate. Its listener is reached only via a
loopback kubectl port-forward and the existing cross-process BiDi session lock.
The OS/UI adapter remains the authority for tab ownership and input delivery.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from . import secure_browser_legacy_support as legacy

MAX_QUERY_CHARS = 8000
MAX_EXPRESSION_CHARS = 4096
# Browser authority does not imply authority to export profile or vault data
# as tool text. Never execute caller-supplied JavaScript: a purported "query"
# could click a purchase button and bypass the UI action-key journal.
FORBIDDEN_SOURCE = re.compile(
    r"\b(?:cookie|localStorage|sessionStorage|indexedDB|password|passcode|"
    r"credential|secret|token|authorization|XMLHttpRequest|fetch|import)\b",
    re.IGNORECASE,
)
PRIVATE_VALUE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|\b(?:\d[ -]*?){13,19}\b")
READ_EXPRESSION = re.compile(
    r'^document\.querySelector(All)?\(("(?:[^"\\]|\\.)*")\)\.(innerText|textContent|value|checked|length)$'
)


def _read_script(expression: str) -> str:
    if expression == "document.title":
        return "document.title"
    if expression == "document.body.innerText":
        return "document.body.innerText"
    match = READ_EXPRESSION.fullmatch(expression)
    if not match:
        raise ValueError("unsupported read expression; use document.title, document.body.innerText, or document.querySelector(All) with a JSON-quoted CSS selector and readable property")
    multiple, raw_selector, prop = match.groups()
    selector = json.loads(raw_selector)
    if not isinstance(selector, str) or not selector or len(selector) > 512:
        raise ValueError("selector must contain 1..512 characters")
    if FORBIDDEN_SOURCE.search(selector):
        raise ValueError("cannot inspect credential, profile, or secret fields")
    if multiple:
        if prop != "length":
            raise ValueError("querySelectorAll supports length only")
        return "document.querySelectorAll(" + json.dumps(selector) + ").length"
    if prop == "length":
        raise ValueError("querySelector does not support length")
    return ("(() => {const e=document.querySelector(" + json.dumps(selector) + ");"
            "if(!e)return null;"
            "const hint=[e.name,e.id,e.getAttribute('aria-label'),e.getAttribute('autocomplete'),"
            "...(e.labels?[...e.labels].map(l=>l.innerText):[])].join(' ');"
            "if(e.matches('input[type=password],input[type=hidden]')||"
            "/password|passcode|verification|one.time|security.code|cvv|cvc|card.number|account.number|routing.number|secret|token|recovery.code/i.test(hint))return '<redacted>';"
            "return e." + prop + ";})()")


def _url_identity(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme == "about":
        return value if value in {"about:blank", "about:newtab", "about:home"} else ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return ""
    # Compare in process only; never return either URL in a tool response.
    # Dropping query/fragment or truncating paths could map a selected checkout
    # tab to a different same-path BiDi context.
    return value


def _safe_result(value: Any) -> Any:
    if isinstance(value, str):
        return PRIVATE_VALUE.sub("<redacted>", value[:MAX_QUERY_CHARS])
    if isinstance(value, list):
        return [_safe_result(item) for item in value[:120]]
    if isinstance(value, dict):
        return {
            str(key)[:100]: "<redacted>" if FORBIDDEN_SOURCE.search(str(key)) else _safe_result(item)
            for key, item in list(value.items())[:120]
        }
    return value if value is None or isinstance(value, (int, float, bool)) else str(value)[:MAX_QUERY_CHARS]


def _selected_context(browser: Any, ui_snapshot: dict[str, Any]) -> str:
    """Fail closed if a redacted URL cannot uniquely map to the visible tab."""
    if not any(tab.get("selected") for tab in ui_snapshot.get("tabs", [])) or not ui_snapshot.get("url"):
        raise RuntimeError("BiDi requires a selected, visible Firefox tab")
    selected = _url_identity(str(ui_snapshot["url"]))
    if not selected:
        raise RuntimeError("selected UI URL is not an inspectable page")
    matches = [
        str(item.get("context")) for item in browser._bidi_contexts()
        if _url_identity(str(item.get("url") or "")) == selected and item.get("context")
    ]
    if len(matches) != 1:
        raise RuntimeError("BiDi selected-tab mapping is absent or ambiguous; no page operation was performed")
    return matches[0]


def _evaluate(browser: Any, context: str, expression: str) -> Any:
    result = browser._bidi("script.evaluate", {
        "expression": expression,
        "target": {"context": context},
        "awaitPromise": True,
        "resultOwnership": "none",
    })
    if result.get("type") == "exception":
        raise RuntimeError("BiDi page script raised an exception")
    return legacy.CdpSession._bidi_value(result.get("result") or {})


def query(ui_snapshot: dict[str, Any], expression: str) -> dict[str, Any]:
    if not expression or len(expression) > MAX_EXPRESSION_CHARS:
        raise ValueError("query must be bounded")
    script = _read_script(expression)
    def run(browser: Any) -> dict[str, Any]:
        if browser.protocol != "bidi":
            raise RuntimeError("Firefox did not expose the private BiDi session")
        context = _selected_context(browser, ui_snapshot)
        value = _safe_result(_evaluate(browser, context, script))
        return {"operation": "query", "status": "ok", "protocol": "firefox-bidi-ui-v2", "value": value,
                "source": "live DOM in uniquely matched visible Firefox tab", "truncated": len(str(value)) >= MAX_QUERY_CHARS}
    return legacy._with_browser(run)


def selector_point(ui_snapshot: dict[str, Any], selector: str, *, field_only: bool = False) -> list[int]:
    if not selector or len(selector) > 512:
        raise ValueError("selector must contain 1..512 characters")
    def run(browser: Any) -> dict[str, list[int]]:
        if browser.protocol != "bidi":
            raise RuntimeError("Firefox did not expose the private BiDi session")
        context = _selected_context(browser, ui_snapshot)
        # Evaluate a fixed script, not selector text. The browser resolves a
        # unique, visible DOM element; OS/UI input still owns the actual click.
        expression = ("(() => { const nodes = [...document.querySelectorAll(" + json.dumps(selector) + ")]; "
            "if (nodes.length !== 1) return {error:'selector must match exactly one element', count:nodes.length}; "
            "const e=nodes[0], r=e.getBoundingClientRect(), s=getComputedStyle(e); "
            "const hint=[e.name,e.id,e.getAttribute('aria-label'),e.getAttribute('autocomplete'),"
            "...(e.labels?[...e.labels].map(l=>l.innerText):[])].join(' '); "
            "if (/password|passcode|verification|one.time|security.code|cvv|cvc|card.number|account.number|routing.number|secret|token|recovery.code/i.test(hint) || "
            "e.matches('input[type=password],input[type=hidden]') || !r.width || !r.height || "
            "s.visibility==='hidden' || s.display==='none') return {error:'not a visible public control'}; "
            + ("if(!e.matches('input,textarea,[contenteditable=true]'))return {error:'selector is not an editable field'};" if field_only else "") +
            "if(devicePixelRatio!==1)return {error:'unverified display scale; use accessibility or grounded visual coordinates'};"
            "const x=r.x+r.width/2,y=r.y+r.height/2; "
            "if (x<0 || y<0 || x>=innerWidth || y>=innerHeight) return {error:'control is outside viewport'}; "
            "const top=document.elementFromPoint(x,y); "
            "if (top!==e && !e.contains(top)) return {error:'control is occluded or overlaps another control'}; "
            "const sx=Math.round(mozInnerScreenX+x),sy=Math.round(mozInnerScreenY+y); "
            "if(!Number.isFinite(sx)||!Number.isFinite(sy)||sx<0||sy<0||sx>=screen.width||sy>=screen.height) "
            "return {error:'selector point is outside desktop bounds'}; "
            "return {x:sx,y:sy}; })()")
        result = _evaluate(browser, context, expression)
        if not isinstance(result, dict) or "error" in result:
            raise RuntimeError(str(result.get("error") if isinstance(result, dict) else "invalid selector geometry"))
        return {"point": [int(result["x"]), int(result["y"])]}
    return legacy._with_browser(run)["point"]
