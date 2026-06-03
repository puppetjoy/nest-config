#!/usr/bin/env python3
"""Run Talon on pending Hermes agent requests marked for review."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REVIEWER = "talon"
DEFAULT_HERMES_BIN = "/opt/hermes-agent/venv/bin/hermes"
PROCESSABLE_STATUSES = {"reviewing", "approved"}
REVIEW_DECISION_STATUSES = {"cancelled", "denied", "needs_info", "proposed"}
APPROVED_DECISION_STATUSES = {"cancelled", "completed", "denied", "in_progress", "needs_info", "proposed"}
MAX_TEXT = 12000
PERSONAL_ASSISTANT_TERMS = {
    "delivery",
    "gmail",
    "glassware",
    "merchant",
    "order",
    "package",
    "purchase",
    "shipment",
    "shopping",
    "tracking",
    "ups",
}
MISSION_TERMS = {
    "backup",
    "bolt",
    "dashboard",
    "deploy",
    "eyrie",
    "gitlab",
    "google oauth",
    "google workspace oauth",
    "hermes",
    "honcho",
    "kubernetes",
    "nest",
    "oauth",
    "openvox",
    "ops",
    "puppet",
    "service",
    "systemd",
    "star",
    "talon",
}
TOOLING_SCOPE_TERMS = {
    "agent request",
    "broker",
    "capability",
    "google-workspace skill",
    "google_workspace",
    "hermes",
    "profile-scoped skill",
    "skill documentation",
    "skill_manage",
    "tool bug",
    "tooling",
    "toolset",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any, max_len: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_len]


def hermes_root() -> Path:
    configured = Path(os.environ.get("HERMES_HOME", "/home/joy/.hermes")).expanduser()
    if configured.parent.name == "profiles":
        return configured.parent.parent
    return configured


def store_dir() -> Path:
    return hermes_root() / "agent-requests"


def state_path() -> Path:
    return store_dir() / "requests.json"


def lock_path() -> Path:
    return store_dir() / ".requests.lock"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"requests": []}
    with path.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state, dict) or not isinstance(state.get("requests"), list):
        raise ValueError(f"Invalid agent request state in {path}")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix="requests.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def telegram_send(message: str) -> dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", "").strip()
    if not token or not chat_id:
        return {"sent": False, "reason": "missing Telegram token or home channel"}

    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message[:3900]}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"sent": bool(payload.get("ok")), "ok": payload.get("ok")}
    except Exception as exc:  # noqa: BLE001 - report best-effort notification failure
        return {"sent": False, "reason": str(exc)}


def event_marker(request: dict[str, Any]) -> str:
    update = request.get("latest_update") or {}
    return f"{request.get('updated_at')}:{update.get('at')}:{update.get('action')}"


def request_has_joy_approval(request: dict[str, Any]) -> bool:
    if request.get("joy_approved_at"):
        return True
    for event in request.get("events", []):
        if event.get("joy_approval") or event.get("joy_steering"):
            return True
    return False


def pending_items(state: dict[str, Any], reviewer: str, request_id: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for request in state.get("requests", []):
        if request_id and request.get("id") != request_id:
            continue
        status = request.get("status")
        if status not in PROCESSABLE_STATUSES:
            continue
        if status == "approved" and not request_has_joy_approval(request):
            continue
        if request.get("reviewer", reviewer) != reviewer:
            continue
        marker = event_marker(request)
        if request.get("reviewer_agent_hold"):
            continue
        if request.get("reviewer_agent_processed") == marker:
            continue
        items.append({"request": request, "marker": marker})
    return items


def request_context(request: dict[str, Any]) -> str:
    public = {
        "id": request.get("id"),
        "requester": request.get("requester"),
        "title": request.get("title"),
        "urgency": request.get("urgency"),
        "status": request.get("status"),
        "submitted_at": request.get("submitted_at"),
        "updated_at": request.get("updated_at"),
        "request": request.get("request"),
        "context": request.get("context"),
        "latest_update": request.get("latest_update"),
    }
    return json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True)


def scope_guard_decision(request: dict[str, Any]) -> dict[str, str] | None:
    """Decline obvious personal-assistant requests before invoking Talon."""
    text = "\n".join(
        str(request.get(key) or "")
        for key in ("title", "request", "context")
    ).lower()
    personal_hits = sorted(term for term in PERSONAL_ASSISTANT_TERMS if term in text)
    mission_hits = sorted(term for term in MISSION_TERMS if term in text)
    tooling_hits = sorted(term for term in TOOLING_SCOPE_TERMS if term in text)
    if tooling_hits:
        return None
    if not personal_hits:
        return None
    if mission_hits and not ({"gmail", "order", "purchase", "shipment", "tracking", "ups"} & set(personal_hits)):
        return None
    if mission_hits and {"google oauth", "google workspace oauth", "oauth"} & set(mission_hits):
        return None
    return {
        "status": "denied",
        "summary": "Declined before tool use because the request appears to be a personal-assistant task outside Talon's Nest Ops mission.",
        "proposal": "",
        "response_to_requester": (
            "Talon is Joy's Nest Ops bot and should not handle personal Gmail, "
            "shopping, shipment, or similar assistant tasks through the ops broker. "
            "Please keep this with a personal-assistant profile instead of Talon."
        ),
    }


def extract_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("reviewer decision was not a JSON object")
    return parsed


def normalize_decision(output: str, allowed_statuses: set[str]) -> dict[str, str]:
    parsed = extract_json(output)
    status = clean_text(parsed.get("status"), max_len=40).lower()
    if status not in allowed_statuses:
        allowed = ", ".join(sorted(allowed_statuses))
        raise ValueError(f"invalid reviewer status for this phase: {status!r}; allowed: {allowed}")
    summary = clean_text(parsed.get("summary"), max_len=2000)
    if not summary:
        raise ValueError("reviewer decision missing summary")
    return {
        "status": status,
        "summary": summary,
        "proposal": clean_text(parsed.get("proposal")),
        "response_to_requester": clean_text(parsed.get("response_to_requester")),
    }


def run_reviewer_agent(reviewer: str, request: dict[str, Any]) -> dict[str, str]:
    profile_home = hermes_root() / "profiles" / reviewer
    hermes_bin = os.environ.get("HERMES_BIN", DEFAULT_HERMES_BIN)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(profile_home)
    env.setdefault("PYTHONPATH", "/opt/hermes-agent/src")
    status = str(request.get("status") or "")
    approved_phase = status == "approved"
    allowed_statuses = APPROVED_DECISION_STATUSES if approved_phase else REVIEW_DECISION_STATUSES
    phase_instructions = (
        "Joy has approved or steered this proposal. You may now implement the "
        "approved/steered change, staying within Joy's steering and Talon's "
        "Nest Ops mission. If the work needs a materially different plan, "
        "return status proposed with a revised proposal instead of changing it."
        if approved_phase else
        "This is review-only. Do not make setup, ops, Puppet, credential, "
        "service, or other side-effecting changes. Inspect only what you need "
        "to produce a concrete proposal, ask for missing information, or deny "
        "out-of-scope work. Joy must approve or steer the proposal before Talon "
        "implements changes."
    )
    toolsets = "terminal,file,web,skills" if approved_phase else "file,web,skills"
    prompt = textwrap.dedent(
        f"""
        You are {reviewer}, Joy's Nest Ops reviewer for the local Hermes
        agent-request broker. A requesting assistant submitted a request and
        the deterministic watcher marked it for review.

        Request phase: {status}
        Phase rules: {phase_instructions}

        Request data:
        {request_context(request)}

        Begin work only if the request is within Talon's Nest Ops mission:
        operating Nest, Eyrie, Puppet, GitLab, Kubernetes, Hermes, Honcho,
        related infrastructure, or approved setup/security work for those
        systems. Hermes/tooling/capability/skill-management bug reports are
        in scope even when the affected tool or example mentions Google
        Workspace, Gmail, calendar, or another personal-assistant domain.
        Talon is not a general personal assistant: decline requests to read,
        summarize, act on, or retrieve personal Gmail, shopping, shipment
        tracking, calendar/social, or similar private-life content for its own
        sake. Do not decline a request merely because it mentions one of those
        domains while asking about a tool, skill, broker, OAuth, profile, or
        Puppet-managed capability problem.

        Return ONLY one JSON object with these
        string fields:

        - status: one of {", ".join(sorted(allowed_statuses))}
        - summary: concise update for Joy/broker history
        - proposal: required when status is proposed, otherwise empty string
        - response_to_requester: required when the requester should receive a
          concrete answer or missing-input request, otherwise empty string

        During review-only phase, use status proposed with a concrete plan for
        any setup or ops change, even if the change seems obvious or safe. Joy
        must approve or steer it before implementation. During approved phase,
        implement only the approved/steered plan. If required input is missing,
        use needs_info and state exactly what is missing. If unsafe or out of
        policy, deny it.

        Do not merely summarize the request. Do not send a separate Telegram
        message. The runner will update the broker from your JSON. Keep secrets
        out of the response. Verify concrete claims with tools where practical.
        """
    ).strip()
    command = [
        hermes_bin,
        "--profile",
        reviewer,
        "--toolsets",
        toolsets,
        "--oneshot",
        prompt,
    ]
    result = subprocess.run(
        command,
        env=env,
        cwd=f"/home/{os.environ.get('USER', 'joy')}",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hermes reviewer oneshot failed rc={result.returncode}: {result.stderr[-1000:]}")
    output = result.stdout.strip()
    if not output:
        raise RuntimeError("Hermes reviewer oneshot produced no output")
    return normalize_decision(output, allowed_statuses)


def notify_update(request: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    sections = [
        "🦉 Talon updated an agent request",
        f"ID: {request.get('id')}",
        f"Status: {request.get('status')}",
        f"Title: {request.get('title')}",
        "",
        str(update.get("summary", "")),
    ]
    proposal = str(update.get("proposal") or "").strip()
    response = str(update.get("response_to_requester") or "").strip()
    if proposal:
        sections.extend(["", "Proposal:", proposal])
    if response:
        sections.extend(["", "Response to requester:", response])
    return telegram_send("\n".join(sections))


def apply_decision(request_id: str, marker: str, reviewer: str, decision: dict[str, str]) -> dict[str, Any]:
    path = state_path()
    lock = lock_path()
    with lock.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        state = load_state(path)
        request = None
        for candidate in state.get("requests", []):
            if candidate.get("id") == request_id:
                request = candidate
                break
        if request is None:
            raise ValueError(f"request not found: {request_id}")
        if request.get("reviewer_agent_hold"):
            return {"skipped": True, "reason": "held"}
        if request.get("reviewer_agent_processed") == marker:
            return {"skipped": True, "reason": "already processed"}
        at = now()
        update: dict[str, Any] = {
            "at": at,
            "actor": reviewer,
            "action": decision["status"],
            "summary": decision["summary"],
        }
        if decision.get("proposal"):
            update["proposal"] = decision["proposal"]
        if decision.get("response_to_requester"):
            update["response_to_requester"] = decision["response_to_requester"]
        if decision["status"] in {"in_progress", "completed"} and not request_has_joy_approval(request):
            raise ValueError("Joy approval is required before applying implementation statuses")
        request["status"] = decision["status"]
        request["updated_at"] = at
        request["latest_update"] = update
        request["reviewer_agent_processed"] = marker
        request["reviewer_agent_processed_at"] = at
        request.setdefault("events", []).append(update)
        save_state(path, state)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)
    notification = notify_update(request, update)
    return {"request": request, "update": update, "telegram": notification}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviewer", nargs="?", default=os.environ.get("REVIEWER_PROFILE", DEFAULT_REVIEWER))
    parser.add_argument("--request-id", help="Only process one request id")
    parser.add_argument("--dry-run", action="store_true", help="List work without running Talon")
    parser.add_argument("--limit", type=int, default=1, help="Maximum requests to run per invocation")
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    directory = store_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = state_path()
    lock = lock_path()

    with lock.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        state = load_state(path)
        items = pending_items(state, args.reviewer, args.request_id)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)

    if not items:
        target = f" id={args.request_id}" if args.request_id else ""
        print(f"no pending review requests for {args.reviewer}{target}")
        return 0

    if args.dry_run:
        for item in items[: args.limit]:
            request = item["request"]
            print(f"would_review id={request.get('id')} requester={request.get('requester')} title={request.get('title')!r}")
        return 0

    failures = 0
    for item in items[: args.limit]:
        request = item["request"]
        request_id = str(request.get("id"))
        try:
            decision = scope_guard_decision(request)
            guarded = decision is not None
            if decision is None:
                decision = run_reviewer_agent(args.reviewer, request)
            result = apply_decision(request_id, item["marker"], args.reviewer, decision)
            if result.get("skipped"):
                print(f"review_skipped id={request_id} reason={result.get('reason')}")
            else:
                verb = "scope_denied" if guarded else "reviewed"
                print(
                    f"{verb} id={request_id} status={decision['status']} "
                    f"telegram_sent={result.get('telegram', {}).get('sent')}"
                )
        except Exception as exc:  # noqa: BLE001 - leave marker unset so the request can retry
            failures += 1
            print(f"review_failed id={request_id} error={exc}", file=sys.stderr)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
