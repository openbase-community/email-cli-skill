"""Delegated Microsoft authentication; no client secrets or application permissions."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import msal

from gmail_cli.accounts import account_dir, list_account_infos, normalize_account_name
from gmail_cli.approved_senders import approved_senders_path
from gmail_cli.provider_paths import provider_config_dir

READ_SCOPES = ["User.Read", "Mail.Read"]
COMPOSE_SCOPE = "Mail.ReadWrite"
SEND_SCOPE = "Mail.Send"


@dataclass
class OutlookCredentials:
    access_token: str = field(repr=False)
    scopes: list[str]
    username: str

    def require_scope(self, scope: str) -> None:
        granted = {s.lower().removeprefix("https://graph.microsoft.com/") for s in self.scopes}
        if scope.lower() not in granted:
            raise PermissionError(
                f"This operation requires {scope}. Run `outlook-cli auth login` with "
                "--include-compose for drafts or --include-send for sending."
            )


def token_path(account: str | None = None) -> Path:
    return account_dir(provider_config_dir("outlook"), account) / "token.json"


def authority(tenant: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", tenant):
        raise ValueError("Microsoft tenant must be a tenant ID or domain, not a URL.")
    return f"https://login.microsoftonline.com/{tenant}"


def save_session(path: Path, data: dict[str, Any]) -> None:
    """Atomic replacement with owner-only permissions from the moment of creation."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def _result_credentials(result: dict | None, username: str) -> OutlookCredentials:
    if not result or "access_token" not in result:
        # Do not echo token responses or identity-provider diagnostics into agent output.
        raise RuntimeError(
            "Microsoft authentication failed or consent is required. Run `outlook-cli auth login`. "
            "Work/school tenant policy may require administrator approval."
        )
    return OutlookCredentials(result["access_token"], result.get("scope", "").split(), username)


def load_credentials(account: str | None = None) -> OutlookCredentials:
    path = token_path(account)
    if not path.exists():
        raise RuntimeError(
            f"No Outlook token for account {normalize_account_name(account)!r}. "
            "Run `outlook-cli auth login --account ACCOUNT --client-id CLIENT_ID` first."
        )
    # Serialize refreshes to prevent concurrent CLI processes overwriting rotated tokens.
    import fcntl

    lock_fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text(encoding="utf-8"))
        cache = msal.SerializableTokenCache()
        cache.deserialize(data["cache"])
        app = msal.PublicClientApplication(
            data["client_id"], authority=authority(data["tenant"]), token_cache=cache
        )
        matches = [a for a in app.get_accounts() if a["home_account_id"] == data["home_account_id"]]
        if len(matches) != 1:
            raise RuntimeError("Stored Outlook identity is missing or ambiguous; sign in again.")
        result = app.acquire_token_silent(data["scopes"], account=matches[0])
        if cache.has_state_changed:
            save_session(path, {**data, "cache": cache.serialize()})
        return _result_credentials(result, data["username"])


def login(args) -> dict[str, Any]:
    path = token_path(args.account)
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    client_id = (
        args.client_id or os.environ.get("OUTLOOK_CLI_CLIENT_ID") or previous.get("client_id")
    )
    if not client_id:
        raise ValueError(
            "Provide --client-id or OUTLOOK_CLI_CLIENT_ID for your Microsoft Entra public-client "
            "app. Register a Mobile and desktop application with http://localhost as redirect URI. "
            "For device login, enable public client flows. No client secret is needed."
        )
    tenant = args.tenant or os.environ.get("OUTLOOK_CLI_TENANT") or previous.get("tenant", "common")
    username = args.username or previous.get("username")
    scopes = list(READ_SCOPES)
    if args.include_compose or args.include_modify:
        scopes.append(COMPOSE_SCOPE)
    if args.include_send:
        scopes.append(SEND_SCOPE)
    cache = msal.SerializableTokenCache()
    app = msal.PublicClientApplication(client_id, authority=authority(tenant), token_cache=cache)
    if args.device_code:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise RuntimeError("Microsoft device login is unavailable for this app or tenant.")
        print(flow["message"], file=sys.stderr, flush=True)
        result = app.acquire_token_by_device_flow(flow)
    else:
        result = app.acquire_token_interactive(scopes=scopes, login_hint=username, port=args.port)
    creds = _result_credentials(result, username or "")
    accounts = app.get_accounts()
    if len(accounts) != 1:
        raise RuntimeError("Microsoft login did not return exactly one account; token not saved.")
    signed_in = accounts[0]
    actual_username = signed_in.get("username", "")
    if previous and signed_in["home_account_id"] != previous.get("home_account_id"):
        raise RuntimeError(
            "This account name already belongs to a different Microsoft identity. "
            "Use a new --account name so existing sender permissions cannot transfer."
        )
    if username and actual_username.casefold() != username.casefold():
        raise RuntimeError("Signed-in Microsoft account differs from --username; token not saved.")
    save_session(
        path,
        {
            "provider": "outlook",
            "client_id": client_id,
            "tenant": tenant,
            "username": actual_username,
            "home_account_id": signed_in["home_account_id"],
            "scopes": scopes,
            "cache": cache.serialize(),
        },
    )
    return {
        "provider": "outlook",
        "account": normalize_account_name(args.account),
        "username": actual_username,
        "token_path": str(path),
        "scopes": creds.scopes,
    }


def dispatch_auth(args) -> dict[str, Any]:
    if args.auth_command == "login":
        return login(args)
    if args.auth_command == "paths":
        return {
            "provider": "outlook",
            "token_path": str(token_path(args.account)),
            "approved_senders_path": str(approved_senders_path(args.account, provider="outlook")),
        }
    if args.auth_command == "accounts":
        root = provider_config_dir("outlook")
        accounts = list_account_infos(config_dir=root, default_token_path=root / "token.json")
        return {
            "provider": "outlook",
            "accounts": [
                {"name": a.name, "token_path": str(a.token_path), "is_default": a.is_default}
                for a in accounts
            ],
        }
    raise ValueError("Unknown Outlook auth command")
