"""Pin a local account alias to an Apple Mail account; Mail owns all OAuth credentials."""

from __future__ import annotations

import json
from pathlib import Path

from gmail_cli.accounts import account_dir, normalize_account_name
from gmail_cli.apple_mail_transport import call_mail
from gmail_cli.approved_senders import approved_senders_path
from gmail_cli.provider_paths import provider_config_dir, save_private


def config_path(account: str | None = None) -> Path:
    return account_dir(provider_config_dir("apple-mail"), account) / "account.json"


def load_account(account: str | None = None) -> dict:
    path = config_path(account)
    if not path.exists():
        raise RuntimeError("Run apple-mail-cli auth login --account NAME --username EMAIL first.")
    return json.loads(path.read_text(encoding="utf-8"))


def dispatch_auth(args) -> dict:
    if args.auth_command == "paths":
        return {
            "account_path": str(config_path(args.account)),
            "approved_senders_path": str(
                approved_senders_path(args.account, provider="apple-mail")
            ),
        }
    available = call_mail("accounts")["accounts"]
    if args.auth_command == "accounts":
        return {"accounts": available, "provider": "apple-mail"}
    if args.auth_command != "login":
        raise ValueError("Unsupported Apple Mail authentication command.")
    if args.client_id or args.tenant or args.device_code or args.port or args.include_modify:
        raise ValueError("Apple Mail owns sign-in; Microsoft OAuth/modify flags do not apply.")
    if not args.username:
        raise ValueError("Provide --username with the exact email configured in Apple Mail.")
    email = args.username.strip().lower()
    matches = [a for a in available if a["enabled"] and email in [e.lower() for e in a["emails"]]]
    if len(matches) != 1:
        raise ValueError(
            "Email must match exactly one enabled Apple Mail account. Set it up in Mail."
        )
    path = config_path(args.account)
    old = load_account(args.account) if path.exists() else None
    if old and (old["account_id"] != matches[0]["id"] or old["email"] != email):
        raise ValueError("Account identity changed; use a new CLI account alias.")
    data = {
        "account_id": matches[0]["id"],
        "email": email,
        "compose": args.include_compose,
        "send": args.include_send,
    }
    save_private(path, data)
    return {
        "account": normalize_account_name(args.account),
        "provider": "apple-mail",
        "email": email,
        "compose_enabled": data["compose"],
        "send_enabled": data["send"],
        "authentication": "managed_by_apple_mail",
    }
