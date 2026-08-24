"""Schemas for the Star Pattern Kit exact-session plugin."""

TOOLSET = "patternkit_session"
SESSION = {
    "type": "string",
    "description": "Pattern Kit collaborative session name (default: atelier)",
    "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
}
REVISION = {
    "type": "integer",
    "description": "Exact session revision from a fresh status or snapshot",
    "minimum": 0,
}
SELECTOR = {
    "type": "string",
    "description": "A single visible Pattern Kit control selected by its literal DOM id",
    "pattern": "^#[A-Za-z][A-Za-z0-9_-]{0,63}$",
}


def schema(name, description, properties=None, required=None):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }


SCHEMAS = {
    "patternkit_session_status": schema(
        "patternkit_session_status",
        "Check the visibly shared exact Pattern Kit tab, Star presence, control owner, revision, and service health. Inspect first before any other Pattern Kit session tool.",
        {"session": SESSION},
    ),
    "patternkit_session_snapshot": schema(
        "patternkit_session_snapshot",
        "Read Pattern Kit's supported redacted semantic diagnostic snapshot for the exact visibly shared tab. Never returns private measurements or browser storage.",
        {"session": SESSION},
    ),
    "patternkit_session_visual_evidence": schema(
        "patternkit_session_visual_evidence",
        "Capture safe canvas-only PNG evidence from the exact visibly shared Pattern Kit tab. The browser chrome, controls, credentials, and private measurement fields are excluded.",
        {"session": SESSION},
    ),
    "patternkit_session_diagnostics": schema(
        "patternkit_session_diagnostics",
        "Read bounded structured app/session/render diagnostics plus sanitized console and failed/slow request observations from the exact visibly shared Pattern Kit tab.",
        {
            "session": SESSION,
            "observe_seconds": {"type": "number", "minimum": 0, "maximum": 5, "default": 1},
            "slow_ms": {"type": "integer", "minimum": 100, "maximum": 10000, "default": 1000},
        },
    ),
    "patternkit_session_control": schema(
        "patternkit_session_control",
        "Acquire, release, or visibly hand off Pattern Kit's supported session control lease as Star. This changes only collaborative control state, never source or Git.",
        {
            "session": SESSION,
            "action": {"type": "string", "enum": ["acquire", "release", "handoff"]},
            "to_actor": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"},
        },
        ["action"],
    ),
    "patternkit_session_click": schema(
        "patternkit_session_click",
        "Click one visible non-rendering, non-source Pattern Kit control by literal id. Requires Star's visible control lease and an exact fresh revision; fails closed on tab, origin, lease, or revision mismatch.",
        {"session": SESSION, "revision": REVISION, "selector": SELECTOR},
        ["revision", "selector"],
    ),
    "patternkit_session_type": schema(
        "patternkit_session_type",
        "Replace text in one visible non-sensitive Pattern Kit input by literal id. Requires Star's visible control lease and exact revision; refuses credentials, PII, private measurements, source, and Git actions.",
        {
            "session": SESSION,
            "revision": REVISION,
            "selector": SELECTOR,
            "text": {"type": "string", "maxLength": 500},
        },
        ["revision", "selector", "text"],
    ),
    "patternkit_session_key": schema(
        "patternkit_session_key",
        "Send one bounded navigation key to the currently focused safe Pattern Kit control. Requires Star's visible control lease and exact revision.",
        {
            "session": SESSION,
            "revision": REVISION,
            "key": {"type": "string", "enum": ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape", "Tab", "Space"]},
        },
        ["revision", "key"],
    ),
}
