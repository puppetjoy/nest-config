#!/opt/hermes-agent/venv/bin/python
"""Operator-only OAuth helper for the profile-scoped Google Photos Picker token.

This helper never prints tokens or client-secret contents. Joy completes the
Google consent page interactively and pastes back the final localhost redirect
URL (a browser connection failure at localhost:1 is expected).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"


def private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def paths(home: Path) -> tuple[Path, Path, Path]:
    return (
        home / "google_client_secret.json",
        home / "google_photos_oauth_pending.json",
        home / "google_photos_token.json",
    )


def load_client(path: Path) -> dict:
    payload = json.loads(path.read_text())
    if "installed" not in payload:
        raise SystemExit("Google OAuth client must be a Desktop app ('installed') client JSON")
    return payload


def auth_url(home: Path) -> None:
    from google_auth_oauthlib.flow import Flow

    client_path, pending_path, _ = paths(home)
    client = load_client(client_path)
    redirect_uri = "http://localhost:1"
    flow = Flow.from_client_config(client, scopes=[SCOPE], redirect_uri=redirect_uri)
    url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="false",
    )
    private_json(
        pending_path,
        {
            "state": state,
            "code_verifier": flow.code_verifier,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
        },
    )
    print("Open this URL as Joy, review the Photos Picker read-only consent, and approve only if it matches:")
    print(url)
    print("After redirect to localhost:1, copy the full failed redirect URL and run --auth-response.")


def exchange(home: Path, response: str) -> None:
    from google_auth_oauthlib.flow import Flow

    client_path, pending_path, token_path = paths(home)
    client = load_client(client_path)
    pending = json.loads(pending_path.read_text())
    parsed = urlparse(response)
    query = parse_qs(parsed.query)
    returned_state = (query.get("state") or [""])[0]
    if returned_state != pending.get("state"):
        raise SystemExit("OAuth state mismatch; discard this response and generate a new authorization URL")
    flow = Flow.from_client_config(
        client,
        scopes=[SCOPE],
        state=pending["state"],
        redirect_uri=pending["redirect_uri"],
        code_verifier=pending.get("code_verifier"),
    )
    flow.fetch_token(authorization_response=response)
    if SCOPE not in set(flow.credentials.scopes or []):
        raise SystemExit("Google did not grant the required Photos Picker scope")
    private_json(token_path, json.loads(flow.credentials.to_json()))
    pending_path.unlink(missing_ok=True)
    print("Google Photos Picker OAuth stored successfully (token value not displayed).")


def check(home: Path) -> int:
    client_path, pending_path, token_path = paths(home)
    scopes: list[str] = []
    if token_path.exists():
        payload = json.loads(token_path.read_text())
        raw = payload.get("scopes") or payload.get("scope") or []
        scopes = raw.split() if isinstance(raw, str) else list(raw)
    print(
        json.dumps(
            {
                "profile_home": str(home),
                "desktop_client_present": client_path.exists(),
                "pending_oauth": pending_path.exists(),
                "authenticated": token_path.exists() and SCOPE in scopes,
                "required_scope": SCOPE,
            },
            indent=2,
        )
    )
    return 0 if token_path.exists() and SCOPE in scopes else 1


def revoke_local(home: Path) -> None:
    _, pending_path, token_path = paths(home)
    pending_path.unlink(missing_ok=True)
    token_path.unlink(missing_ok=True)
    print("Local Google Photos OAuth state removed. Also revoke the app in Google Account > Security > Third-party connections.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-home", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--auth-url", action="store_true")
    action.add_argument("--auth-response")
    action.add_argument("--check", action="store_true")
    action.add_argument("--remove-local-token", action="store_true")
    args = parser.parse_args()
    home = args.profile_home.expanduser().resolve()
    expected_root = Path("/home/joy/.hermes/profiles").resolve()
    if expected_root not in home.parents:
        raise SystemExit("profile home must be below /home/joy/.hermes/profiles")
    if args.auth_url:
        auth_url(home)
    elif args.auth_response:
        exchange(home, args.auth_response)
    elif args.check:
        return check(home)
    else:
        revoke_local(home)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"Google Photos OAuth helper failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
