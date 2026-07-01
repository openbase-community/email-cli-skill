"""Account naming and token path helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ACCOUNT_NAME = "default"
ACCOUNT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class AccountInfo:
    name: str
    token_path: Path
    is_default: bool


def normalize_account_name(account: str | None) -> str:
    if account is None or account.strip() == "":
        return DEFAULT_ACCOUNT_NAME
    name = account.strip()
    if not ACCOUNT_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Account names must start with a letter or number and contain only letters, "
            "numbers, dots, underscores, and hyphens."
        )
    return name


def account_dir(config_dir: Path, account: str | None) -> Path:
    name = normalize_account_name(account)
    if name == DEFAULT_ACCOUNT_NAME:
        return config_dir
    return config_dir / "accounts" / name


def account_token_path(
    *,
    config_dir: Path,
    default_token_path: Path,
    account: str | None,
    env_token_path: Path | None = None,
) -> Path:
    name = normalize_account_name(account)
    if name == DEFAULT_ACCOUNT_NAME:
        return env_token_path or default_token_path
    return account_dir(config_dir, name) / "token.json"


def list_account_infos(
    *,
    config_dir: Path,
    default_token_path: Path,
    env_token_path: Path | None = None,
) -> list[AccountInfo]:
    accounts: dict[str, AccountInfo] = {}
    default_path = env_token_path or default_token_path
    if default_path.exists():
        accounts[DEFAULT_ACCOUNT_NAME] = AccountInfo(
            name=DEFAULT_ACCOUNT_NAME,
            token_path=default_path,
            is_default=True,
        )

    accounts_dir = config_dir / "accounts"
    if accounts_dir.exists():
        for token_file in sorted(accounts_dir.glob("*/token.json")):
            name = token_file.parent.name
            try:
                normalize_account_name(name)
            except ValueError:
                continue
            accounts[name] = AccountInfo(name=name, token_path=token_file, is_default=False)

    return sorted(accounts.values(), key=lambda item: (not item.is_default, item.name))
