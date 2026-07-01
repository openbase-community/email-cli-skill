"""Approved sender configuration and matching."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from email.utils import getaddresses
from pathlib import Path
from typing import Any

from gmail_cli.accounts import account_dir, normalize_account_name
from gmail_cli.auth_paths import APP_CONFIG_DIR

APPROVED_SENDERS_ENV = "GMAIL_CLI_APPROVED_SENDERS"
LEGACY_APPROVED_SENDERS_ENV = "GMAIL_MCP_APPROVED_SENDERS"
APPROVED_SENDERS_PATH_ENV = "GMAIL_CLI_APPROVED_SENDERS_PATH"
LEGACY_APPROVED_SENDERS_PATH_ENV = "GMAIL_MCP_APPROVED_SENDERS_PATH"
DEFAULT_APPROVED_SENDERS_PATH = APP_CONFIG_DIR / "approved_senders.json"


@dataclass(frozen=True)
class ApprovedSenders:
    senders: frozenset[str]
    sources: tuple[str, ...] = ()

    def is_sender_approved(self, from_header: str | None) -> bool:
        if not self.senders:
            return False
        return any(sender in self.senders for sender in extract_sender_addresses(from_header))

    def as_dict(self) -> dict[str, Any]:
        return {
            "approved_senders": sorted(self.senders),
            "sources": list(self.sources),
        }


def approved_senders_path(account: str | None = None) -> Path:
    env_path = os.environ.get(APPROVED_SENDERS_PATH_ENV) or os.environ.get(
        LEGACY_APPROVED_SENDERS_PATH_ENV
    )
    if env_path:
        return Path(env_path).expanduser()
    name = normalize_account_name(account)
    if name == "default":
        return DEFAULT_APPROVED_SENDERS_PATH
    return account_dir(APP_CONFIG_DIR, name) / "approved_senders.json"


def load_approved_senders(account: str | None = None) -> ApprovedSenders:
    senders: set[str] = set()
    sources: list[str] = []

    env_value = os.environ.get(APPROVED_SENDERS_ENV) or os.environ.get(LEGACY_APPROVED_SENDERS_ENV)
    if env_value:
        senders.update(normalize_sender_list(_split_sender_values(env_value)))
        sources.append(APPROVED_SENDERS_ENV)

    path = approved_senders_path(account)
    if path.exists():
        senders.update(normalize_sender_list(_read_sender_file(path)))
        sources.append(str(path))

    return ApprovedSenders(senders=frozenset(senders), sources=tuple(sources))


def save_approved_senders(senders: list[str], account: str | None = None) -> Path:
    normalized = sorted(normalize_sender_list(senders))
    path = approved_senders_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"approved_senders": normalized}, indent=2) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def add_approved_senders(senders: list[str], account: str | None = None) -> ApprovedSenders:
    existing = load_approved_senders(account)
    merged = sorted(set(existing.senders) | normalize_sender_list(senders))
    save_approved_senders(merged, account)
    return load_approved_senders(account)


def remove_approved_senders(senders: list[str], account: str | None = None) -> ApprovedSenders:
    existing = load_approved_senders(account)
    removed = normalize_sender_list(senders)
    save_approved_senders(sorted(set(existing.senders) - removed), account)
    return load_approved_senders(account)


def extract_sender_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    addresses = []
    for _name, address in getaddresses([value]):
        normalized = normalize_email_address(address)
        if normalized:
            addresses.append(normalized)
    return addresses


def normalize_sender_list(values: list[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        normalized.update(extract_sender_addresses(value))
    return normalized


def normalize_email_address(value: str | None) -> str | None:
    if value is None:
        return None
    address = value.strip().strip("<>").strip().lower()
    if "@" not in address:
        return None
    local, domain = address.rsplit("@", 1)
    if not local or not domain or any(char.isspace() for char in address):
        return None
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    return f"{local}@{domain}"


def _read_sender_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return [str(item) for item in data]
        if isinstance(data, dict):
            values = data.get("approved_senders", [])
            if not isinstance(values, list):
                raise ValueError(f"{path} field approved_senders must be a list.")
            return [str(item) for item in values]
        raise ValueError(f"{path} must contain a JSON list or object.")
    return _split_sender_values(text)


def _split_sender_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
