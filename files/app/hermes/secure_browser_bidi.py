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
VERIFICATION_VALUE = re.compile(
    r"\b((?:verification|one[- ]?time|security|login|authentication|auth|recovery)\s*(?:code|pin|number)?\s*(?:is|:|#|-)?\s*)\d{4,8}\b",
    re.IGNORECASE,
)
POTENTIAL_CODE = re.compile(r"(?<![\w.$€£])\d{4,8}(?![\w.,])")
READ_EXPRESSION = re.compile(
    r'^document\.querySelector(All)?\(("(?:[^"\\]|\\.)*")\)\.(innerText|textContent|value|checked|length|href)$'
)

# Fixed, site-independent observation; accepting arbitrary JavaScript as a
# "read" would let the caller mutate the page before any response filtering.
DOM_SNAPSHOT = """(() => {
  const max=120, scanLimit=1500, start=__OFFSET__, nodes=[], all=document.body?.querySelectorAll('*')||[];
  const sensitive=/password|passcode|verification|one.time|security.code|cvv|cvc|card.number|account.number|routing.number|secret|token|recovery.code/i;
  const protectedNode=e=>{
    const hint=[e.name,e.id,e.getAttribute('aria-label'),e.getAttribute('autocomplete'),
      e.getAttribute('placeholder'),...(e.labels?[...e.labels].map(l=>l.innerText):[])].join(' ');
    return sensitive.test(hint)||e.matches('input[type=password],input[type=hidden]')||
      !!e.closest('[autocomplete=one-time-code],[data-sensitive=true]');
  };
  let i=start;
  for(;i<Math.min(all.length,start+scanLimit)&&nodes.length<max;i++){
    const e=all[i];
    if(e.closest('script,style,template,[hidden],[aria-hidden=true]'))continue;
    if(protectedNode(e)||e.isContentEditable)continue;
    const s=getComputedStyle(e);
    if(s.display==='none'||s.visibility==='hidden')continue;
    const r=e.getBoundingClientRect();
    const ownText=[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE)
      .map(n=>n.textContent).join(' ').trim().slice(0,300);
    const row={tag:e.localName,depth:Math.min(32,(()=>{let n=e,d=0;while((n=n.parentElement)&&d<32)d++;return d})()),
      role:e.getAttribute('role')||null,text:ownText||null,
      visible:!!(r.width&&r.height&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth)};
    const label=e.getAttribute('aria-label');
    if(label&&!sensitive.test(label))row.label=label.slice(0,200);
    if(e.matches('input,textarea,select')){
      row.control={type:e.getAttribute('type')||e.localName,disabled:!!e.disabled,
        checked:!!e.checked};
      // Ordinary quantity/variant controls must be observable without a
      // retailer-specific parser. Never export a secret/hidden input value.
      if(e.matches('input,textarea,select')&&!e.matches('input[type=file]'))
        row.control.value=String(e.value??'').slice(0,200);
    }
    nodes.push(row);
  }
  return {total:all.length,nextOffset:i<all.length?i:null,nodes};
})()"""


def _read_script(expression: str) -> str:
    if expression == "document.domSnapshot":
        return DOM_SNAPSHOT.replace("__OFFSET__", "0")
    # A long page may put its actual content after navigation/header nodes.
    # Use raw DOM indices, not filtered result indices, so callers can read
    # every part without a site-specific selector or an unbounded response.
    if re.fullmatch(r"document\.domSnapshot\((?:0|[1-9][0-9]{0,5})\)", expression):
        offset = int(expression[len("document.domSnapshot("):-1])
        if offset > 100000:
            raise ValueError("snapshot offset is too large")
        return DOM_SNAPSHOT.replace("__OFFSET__", str(offset))
    if expression == "document.title":
        return "document.title"
    if expression == "document.body.innerText":
        raise ValueError("unfiltered body text is unavailable; use document.domSnapshot(offset)")
    match = READ_EXPRESSION.fullmatch(expression)
    if not match:
        raise ValueError("unsupported read expression; use document.domSnapshot(offset), document.title, or document.querySelector(All) with a JSON-quoted CSS selector and readable property")
    multiple, raw_selector, prop = match.groups()
    selector = json.loads(raw_selector)
    if not isinstance(selector, str) or not selector or len(selector) > 512:
        raise ValueError("selector must contain 1..512 characters")
    if FORBIDDEN_SOURCE.search(selector):
        raise ValueError("cannot inspect credential, profile, or secret fields")
    if multiple and prop == "length":
        return "document.querySelectorAll(" + json.dumps(selector) + ").length"
    if not multiple and prop == "length":
        raise ValueError("querySelector does not support length")
    # The same per-element credential guard applies to a single match and to
    # collections. This makes rendered text, variants, and controls readable
    # across sites without making a collection a bypass for protected fields.
    getter = ("e => {const hint=[e.name,e.id,e.getAttribute('aria-label'),e.getAttribute('autocomplete'),"
              "...(e.labels?[...e.labels].map(l=>l.innerText):[])].join(' ');"
              "if(e.matches('input[type=password],input[type=hidden]')||e.querySelector('input[type=password],input[autocomplete=one-time-code]')||"
              "/password|passcode|verification|one.time|security.code|cvv|cvc|card.number|account.number|routing.number|secret|token|recovery.code/i.test(hint))return '<redacted>';"
              "return e." + prop + ";}")
    if prop == "href":
        # Credentials may live in arbitrary path segments as well as query
        # parameters. Export only HTTP(S) origins, never a raw link URL.
        getter = ("e => {if(!e.matches('a[href],area[href]'))return null;"
                  "try{const u=new URL(e.href,document.baseURI);"
                  "return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password"
                  "?u.origin:'<redacted>';}catch{return '<redacted>';}}")
    if multiple:
        return ("(() => {const nodes=document.querySelectorAll(" + json.dumps(selector) + ");"
                "return {total:nodes.length,values:[...nodes].slice(0,120).map(" + getter + ")};})()")
    return ("(() => {const e=document.querySelector(" + json.dumps(selector) + ");"
            "return e? (" + getter + ")(e) : null;})()")


def _url_identity(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme == "about":
        return value if value in {"about:blank", "about:newtab", "about:home"} else ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return ""
    # Compare in process only; never return either URL in a tool response.
    # Dropping query/fragment or truncating paths could map a selected checkout
    # tab to a different same-path BiDi context.
    # The address bar may display an origin without a trailing slash while
    # BiDi reports its canonical URL with "/". Preserve the exact query and
    # fragment; normalize only this empty-path spelling difference.
    return parsed._replace(path=parsed.path or "/").geturl()


def _safe_result(value: Any) -> Any:
    if isinstance(value, str):
        cleaned = PRIVATE_VALUE.sub("<redacted>", value[:MAX_QUERY_CHARS])
        return POTENTIAL_CODE.sub("<redacted>", VERIFICATION_VALUE.sub(r"\1<redacted>", cleaned))
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
    def visible_identity(value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme == "about":
            return value
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return ""
        try:
            port = f":{parsed.port}" if parsed.port else ""
        except ValueError:
            return ""
        return f"{parsed.scheme}://{parsed.hostname}{port}{parsed.path[:300]}"
    # The accessibility bridge intentionally removes URL queries from tool
    # text. Match exact URLs when available, otherwise require a *unique*
    # sanitized path, never guess between same-path checkout contexts.
    snapshot_redacted = "?" not in selected and "#" not in selected
    matches = [
        str(item.get("context")) for item in browser._bidi_contexts()
        if item.get("context") and (visible_identity(str(item.get("url") or "")) == selected
                                    if snapshot_redacted else _url_identity(str(item.get("url") or "")) == selected)
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


def probe() -> bool:
    """Report live BiDi connectivity, not merely a configured launch flag."""
    def run(browser: Any) -> bool:
        return browser.protocol == "bidi" and isinstance(browser._bidi_contexts(), list)
    try:
        return bool(legacy._with_browser(run))
    except Exception:
        # The status surface must not claim capability when the private
        # connector raises a transport- or protocol-specific exception.
        return False


def query(ui_snapshot: dict[str, Any], expression: str) -> dict[str, Any]:
    if not expression or len(expression) > MAX_EXPRESSION_CHARS:
        raise ValueError("query must be bounded")
    script = _read_script(expression)
    def run(browser: Any) -> dict[str, Any]:
        if browser.protocol != "bidi":
            raise RuntimeError("Firefox did not expose the private BiDi session")
        context = _selected_context(browser, ui_snapshot)
        raw = _evaluate(browser, context, script)
        truncated = (isinstance(raw, dict) and (
            raw.get("nextOffset") is not None if "nextOffset" in raw else
            isinstance(raw.get("total"), int) and raw["total"] > len(raw.get("values", []))))
        value = _safe_result(raw)
        return {"operation": "query", "status": "ok", "protocol": "firefox-bidi-ui-v2", "value": value,
                "source": "live DOM in uniquely matched visible Firefox tab", "truncated": truncated or len(str(value)) >= MAX_QUERY_CHARS}
    return legacy._with_browser(run)
