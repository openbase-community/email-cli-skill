from __future__ import annotations

import json
import stat
from unittest.mock import Mock

import pytest

from gmail_cli import outlook_auth
from gmail_cli.cli import build_parser


@pytest.fixture
def auth(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTLOOK_CLI_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("OUTLOOK_CLI_CLIENT_ID", raising=False)
    monkeypatch.delenv("OUTLOOK_CLI_TENANT", raising=False)
    app = Mock()
    app.get_accounts.return_value = [
        {"home_account_id": "test-account", "username": "a@example.com"}
    ]
    result = {"access_token": "test-only", "scope": "User.Read Mail.Read"}
    app.acquire_token_interactive.return_value = result
    app.acquire_token_silent.return_value = result
    app.acquire_token_by_device_flow.return_value = result
    factory = Mock(return_value=app)
    monkeypatch.setattr(outlook_auth.msal, "PublicClientApplication", factory)
    return factory, app


def login_args(*extra):
    return build_parser().parse_args(
        [
            "auth",
            "login",
            "--provider",
            "outlook",
            "--account",
            "school",
            *extra,
        ]
    )


def test_missing_app_registration_gives_actionable_error_without_network(auth):
    factory, _ = auth
    with pytest.raises(ValueError, match="--client-id"):
        outlook_auth.login(login_args())
    factory.assert_not_called()


def test_login_stores_owner_only_cache_without_exposing_tokens(auth):
    factory, app = auth
    result = outlook_auth.login(
        login_args("--client-id", "test-app", "--username", "a@example.com")
    )
    path = outlook_auth.token_path("school")
    data = json.loads(path.read_text())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert data["username"] == "a@example.com" and data["home_account_id"] == "test-account"
    assert "access_token" not in result and "cache" not in result
    assert "test-only" not in repr(result)
    assert app.acquire_token_interactive.call_args.kwargs["scopes"] == ["User.Read", "Mail.Read"]
    assert factory.call_args.kwargs["authority"] == "https://login.microsoftonline.com/common"


def test_login_rejects_wrong_account_before_saving(auth):
    with pytest.raises(RuntimeError, match="differs"):
        outlook_auth.login(login_args("--client-id", "test-app", "--username", "other@example.com"))
    assert not outlook_auth.token_path("school").exists()


def test_auth_scope_flags_are_explicit(auth):
    _, app = auth
    outlook_auth.login(login_args("--client-id", "test-app", "--include-compose", "--include-send"))
    assert app.acquire_token_interactive.call_args.kwargs["scopes"] == [
        "User.Read",
        "Mail.Read",
        "Mail.ReadWrite",
        "Mail.Send",
    ]


def test_device_flow_keeps_prompt_off_json_stdout(auth, capsys):
    _, app = auth
    app.initiate_device_flow.return_value = {
        "user_code": "TEST",
        "message": "Visit Microsoft login",
    }
    outlook_auth.login(login_args("--client-id", "test-app", "--device-code"))
    output = capsys.readouterr()
    assert output.out == "" and "Visit Microsoft login" in output.err
    app.acquire_token_interactive.assert_not_called()


def test_refresh_uses_pinned_cached_account_without_interactive_login(auth):
    _, app = auth
    outlook_auth.login(login_args("--client-id", "test-app"))
    app.reset_mock()
    creds = outlook_auth.load_credentials("school")
    assert creds.username == "a@example.com"
    assert "test-only" not in repr(creds)
    assert app.acquire_token_silent.call_args.kwargs["account"]["home_account_id"] == "test-account"
    app.acquire_token_interactive.assert_not_called()


def test_refresh_failure_does_not_echo_server_diagnostics(auth):
    _, app = auth
    outlook_auth.login(login_args("--client-id", "test-app"))
    app.acquire_token_silent.return_value = {"error_description": "private server details"}
    with pytest.raises(RuntimeError, match="sign|login") as exc:
        outlook_auth.load_credentials("school")
    assert "private server details" not in str(exc.value)


def test_account_cannot_change_under_existing_sender_permissions(auth):
    _, app = auth
    outlook_auth.login(login_args("--client-id", "test-app"))
    app.get_accounts.return_value = [{"home_account_id": "different", "username": "b@example.com"}]
    with pytest.raises(RuntimeError):
        outlook_auth.login(login_args("--client-id", "test-app", "--username", "b@example.com"))
    assert json.loads(outlook_auth.token_path("school").read_text())["username"] == "a@example.com"


@pytest.mark.parametrize("tenant", ["https://evil.example", "../common", "common?x=1"])
def test_tenant_cannot_redirect_authentication(tenant):
    with pytest.raises(ValueError):
        outlook_auth.authority(tenant)
