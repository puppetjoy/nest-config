"""Require approval only for Star terminal calls that invoke sudo."""

from __future__ import annotations

import os
from pathlib import PurePath
import re
import shlex
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4


_SHELLS = {"bash", "dash", "ksh", "sh", "zsh"}
_COMMAND_WRAPPERS = {"builtin", "command", "exec", "nohup", "time"}
_APPROVAL_MESSAGE = "Star is requesting permission to execute a sudo command"
_SHELL_HEREDOC = re.compile(
    r"(?ms)(?:^|[;&|(\n])\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*"
    r"(?:\S*/)?(?:bash|dash|ksh|sh|zsh)\b[^\n]*?"
    r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*\n"
    r"(.*?)^\s*\1\s*$",
)


def _tokens(command: str) -> list[str]:
    """Return shell words and operators, or an empty list for malformed input."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        return list(lexer)
    except ValueError:
        return []


def _segments(tokens: Iterable[str]) -> Iterable[list[str]]:
    segment: list[str] = []
    for token in tokens:
        if token and all(character in ";|&()" for character in token):
            if segment:
                yield segment
                segment = []
            continue
        segment.append(token)
    if segment:
        yield segment


def _is_assignment(token: str) -> bool:
    if "=" not in token or token.startswith("="):
        return False
    name, _value = token.split("=", 1)
    return name.replace("_", "a").isalnum() and not name[0].isdigit()


def _skip_options(words: list[str], index: int) -> int:
    while index < len(words) and words[index].startswith("-") and words[index] != "-":
        index += 1
    return index


def _command_word(words: list[str]) -> tuple[int, str]:
    """Return the executable index/name after assignments and common wrappers."""
    index = 0
    while index < len(words) and _is_assignment(words[index]):
        index += 1

    while index < len(words):
        executable = PurePath(words[index]).name
        if executable == "env":
            index = _skip_options(words, index + 1)
            while index < len(words) and _is_assignment(words[index]):
                index += 1
            continue
        if executable in _COMMAND_WRAPPERS:
            index = _skip_options(words, index + 1)
            continue
        return index, executable
    return index, ""


def _shell_payload(words: list[str], executable_index: int) -> Optional[str]:
    """Return a shell -c payload, including combined flags such as -lc."""
    index = executable_index + 1
    while index < len(words):
        option = words[index]
        if option == "--":
            return None
        if option == "-c":
            return words[index + 1] if index + 1 < len(words) else None
        if option.startswith("-") and not option.startswith("--") and "c" in option[1:]:
            return words[index + 1] if index + 1 < len(words) else None
        if not option.startswith("-"):
            return None
        index += 1
    return None


def command_invokes_sudo(command: str, *, _depth: int = 0) -> bool:
    """Detect real sudo command words, including env/command and shell -c wrappers."""
    if not isinstance(command, str) or not command or _depth > 4:
        return False

    for match in _SHELL_HEREDOC.finditer(command):
        if command_invokes_sudo(match.group(2), _depth=_depth + 1):
            return True

    for words in _segments(_tokens(command)):
        executable_index, executable = _command_word(words)
        if executable == "sudo":
            return True
        if executable in _SHELLS:
            payload = _shell_payload(words, executable_index)
            if payload and command_invokes_sudo(payload, _depth=_depth + 1):
                return True
    return False


def _on_pre_tool_call(
    tool_name: str = "",
    args: Any = None,
    tool_call_id: str = "",
    **_: Any,
) -> Optional[Dict[str, str]]:
    """Escalate each Star sudo invocation to Hermes' approval gate."""
    if os.environ.get("HERMES_PROFILE") != "star" or tool_name != "terminal":
        return None
    if not isinstance(args, dict) or not command_invokes_sudo(args.get("command", "")):
        return None

    invocation_id = tool_call_id.strip() if isinstance(tool_call_id, str) else ""
    if not invocation_id:
        invocation_id = uuid4().hex
    return {
        "action": "approve",
        "message": _APPROVAL_MESSAGE,
        "rule_key": f"star-sudo:{invocation_id}",
    }


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
