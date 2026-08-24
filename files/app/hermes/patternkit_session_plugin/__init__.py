"""Register the Star-only Pattern Kit exact-session tools."""

from .schemas import SCHEMAS, TOOLSET
from . import tools


def register(ctx):
    handlers = {
        "patternkit_session_status": tools.patternkit_session_status,
        "patternkit_session_snapshot": tools.patternkit_session_snapshot,
        "patternkit_session_visual_evidence": tools.patternkit_session_visual_evidence,
        "patternkit_session_diagnostics": tools.patternkit_session_diagnostics,
        "patternkit_session_control": tools.patternkit_session_control,
        "patternkit_session_click": tools.patternkit_session_click,
        "patternkit_session_type": tools.patternkit_session_type,
        "patternkit_session_key": tools.patternkit_session_key,
    }
    for name, handler in handlers.items():
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=SCHEMAS[name],
            handler=lambda params, _handler=handler, **_kwargs: tools._safe_tool_call(_handler, params),
            check_fn=tools.check_requirements,
        )
