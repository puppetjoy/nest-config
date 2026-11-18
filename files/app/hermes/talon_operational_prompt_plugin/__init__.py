"""Freeze Talon's public operational guidance into new session prompts."""

from pathlib import Path

from hermes_constants import get_hermes_home
from hermes_cli.profiles import get_active_profile_name


SECTIONS = (
    ("talon.readable-prose", "readable-prose.md", 2048),
    ("talon.delivery-completion", "delivery-completion.md", 1024),
)


def register(ctx) -> None:
    # HERMES_PROFILE alone can be inherited from another process. Resolve the
    # actual profile home, and accept only its own profile-local plugin copy.
    home = get_hermes_home().resolve()
    plugin_dir = Path(__file__).resolve().parent
    if get_active_profile_name() != "talon" or plugin_dir.parent != home / "plugins":
        return

    # Read once at plugin registration, never on a tool call or prompt turn.
    # Missing/invalid assets raise: core reports a plugin load failure and
    # rolls back registrations rather than quietly installing partial guidance.
    sections = []
    for section_id, filename, max_chars in SECTIONS:
        content = (plugin_dir / filename).read_text(encoding="utf-8").strip()
        if not content or len(content) > max_chars:
            raise ValueError(f"Talon {filename} asset is empty or exceeds its prompt budget")
        sections.append((section_id, content, max_chars))

    # Validate all assets before publishing any section.
    for section_id, content, max_chars in sections:
        ctx.register_system_prompt_section(
            section_id, content, position="after_memory", max_chars=max_chars,
        )
