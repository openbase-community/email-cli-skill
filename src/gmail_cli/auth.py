"""Google OAuth helpers for local Gmail API access."""

from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gmail_cli.accounts import account_token_path, list_account_infos, normalize_account_name
from gmail_cli.auth_paths import APP_CONFIG_DIR, DEFAULT_CREDENTIALS_PATH, DEFAULT_TOKEN_PATH


def credentials_path() -> Path:
    return Path(
        os.environ.get(
            "GMAIL_CLI_CREDENTIALS_PATH",
            os.environ.get("GMAIL_MCP_CREDENTIALS_PATH", DEFAULT_CREDENTIALS_PATH),
        )
    ).expanduser()


def token_path(account: str | None = None) -> Path:
    env_token_path = os.environ.get("GMAIL_CLI_TOKEN_PATH") or os.environ.get(
        "GMAIL_MCP_TOKEN_PATH"
    )
    return account_token_path(
        config_dir=APP_CONFIG_DIR,
        default_token_path=DEFAULT_TOKEN_PATH,
        account=account,
        env_token_path=Path(env_token_path).expanduser() if env_token_path else None,
    )


def list_accounts() -> list[dict[str, str | bool]]:
    env_token_path = os.environ.get("GMAIL_CLI_TOKEN_PATH") or os.environ.get(
        "GMAIL_MCP_TOKEN_PATH"
    )
    accounts = list_account_infos(
        config_dir=APP_CONFIG_DIR,
        default_token_path=DEFAULT_TOKEN_PATH,
        env_token_path=Path(env_token_path).expanduser() if env_token_path else None,
    )
    return [
        {
            "name": account.name,
            "token_path": str(account.token_path),
            "is_default": account.is_default,
        }
        for account in accounts
    ]


def load_credentials(scopes: list[str] | None = None, account: str | None = None) -> Credentials:
    """Load or refresh stored OAuth credentials without starting a browser flow."""
    account_name = normalize_account_name(account)
    token_file = token_path(account_name)
    if not token_file.exists():
        raise RuntimeError(
            f"No Gmail OAuth token found for account {account_name!r}. Run "
            "`gmail-cli auth login --account ACCOUNT` first, or set GMAIL_CLI_TOKEN_PATH "
            "to an existing token file for the default account."
        )

    creds = Credentials.from_authorized_user_file(str(token_file), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds, account=account_name)

    if not creds.valid:
        raise RuntimeError(
            "Stored Gmail OAuth credentials are invalid. Run `gmail-cli auth login` again."
        )

    return creds


def run_oauth_flow(scopes: list[str], port: int = 0) -> Credentials:
    """Run the installed-app OAuth flow and persist the resulting token."""
    client_file = credentials_path()
    if not client_file.exists():
        raise RuntimeError(
            f"OAuth client credentials were not found at {client_file}. Download an OAuth "
            "Desktop client JSON from Google Cloud Console or set GMAIL_CLI_CREDENTIALS_PATH."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes)
    creds = flow.run_local_server(port=port)
    save_credentials(creds)
    return creds


def run_oauth_flow_for_account(
    scopes: list[str],
    port: int = 0,
    account: str | None = None,
) -> Credentials:
    """Run the installed-app OAuth flow and persist the token for an account."""
    client_file = credentials_path()
    if not client_file.exists():
        raise RuntimeError(
            f"OAuth client credentials were not found at {client_file}. Download an OAuth "
            "Desktop client JSON from Google Cloud Console or set GMAIL_CLI_CREDENTIALS_PATH."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes)
    creds = flow.run_local_server(port=port)
    save_credentials(creds, account=account)
    return creds


def save_credentials(creds: Credentials, account: str | None = None) -> None:
    token_file = token_path(account)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    token_file.chmod(0o600)
