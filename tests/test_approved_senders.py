from __future__ import annotations

import json

from gmail_cli.accounts import account_token_path, list_account_infos
from gmail_cli.approved_senders import (
    ApprovedSenders,
    extract_sender_addresses,
    load_approved_senders,
)


def test_sender_matching_handles_display_names_and_case() -> None:
    approved = ApprovedSenders(frozenset({"alice@example.com"}))

    assert approved.is_sender_approved('"Alice Example" <ALICE@Example.com>')
    assert approved.is_sender_approved("Alice <alice@example.com>, Other <other@example.com>")
    assert not approved.is_sender_approved("mallory@example.com")


def test_sender_extraction_rejects_invalid_values() -> None:
    assert extract_sender_addresses("not an email address") == []
    assert extract_sender_addresses("Name <bad value@example.com>") == []


def test_load_approved_senders_from_account_file(tmp_path, monkeypatch) -> None:
    sender_file = tmp_path / "approved.json"
    sender_file.write_text(
        json.dumps({"approved_senders": ["Alice <Alice@Example.com>"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GMAIL_CLI_APPROVED_SENDERS_PATH", str(sender_file))

    approved = load_approved_senders("work")

    assert approved.senders == frozenset({"alice@example.com"})
    assert str(sender_file) in approved.sources


def test_account_paths_preserve_default_token_and_add_named_accounts(tmp_path) -> None:
    default_token = tmp_path / "token.json"
    default_token.write_text("{}", encoding="utf-8")
    named_token = tmp_path / "accounts" / "work" / "token.json"
    named_token.parent.mkdir(parents=True)
    named_token.write_text("{}", encoding="utf-8")

    assert (
        account_token_path(
            config_dir=tmp_path,
            default_token_path=default_token,
            account=None,
        )
        == default_token
    )
    assert (
        account_token_path(
            config_dir=tmp_path,
            default_token_path=default_token,
            account="work",
        )
        == named_token
    )

    accounts = list_account_infos(config_dir=tmp_path, default_token_path=default_token)
    assert [account.name for account in accounts] == ["default", "work"]
