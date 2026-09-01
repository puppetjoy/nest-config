from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
REFRESH_HELPER = REPO_ROOT / "files/app/hermes/hermes-systemd-user-refresh"


def test_gateway_refresh_restarts_process_to_activate_installed_code() -> None:
    helper = REFRESH_HELPER.read_text(encoding="utf-8")

    assert 'systemctl --user restart "$service"' in helper
    assert "try-reload-or-restart" not in helper
