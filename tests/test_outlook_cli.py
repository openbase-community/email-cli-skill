from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from email_cli import approved_senders, cli


@pytest.mark.parametrize(
    "argv",
    [
        ["--provider", "outlook", "search", "from:alice@example.com"],
        ["search", "from:alice@example.com", "--provider", "outlook"],
    ],
)
def test_provider_routing_and_folder_alias(argv, monkeypatch, capsys):
    client = Mock()
    client.search_messages.return_value = {"messages": []}
    factory = Mock(return_value=client)
    monkeypatch.setattr(cli, "configured_client", factory)
    cli.main(argv + ["--account", "school", "--folder-id", "inbox"])
    factory.assert_called_once_with("school", "outlook")
    assert client.search_messages.call_args.kwargs["label_ids"] == ["inbox"]
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


@pytest.mark.parametrize(
    "command",
    [
        ["draft-new", "--to", "alice@example.com", "--subject", "Hi", "--body", "Hi"],
        ["draft-reply", "t1", "--body", "Hi"],
        ["send-draft", "d1"],
        ["approved-senders", "add", "alice@example.com"],
        ["approved-senders", "remove", "alice@example.com"],
    ],
)
def test_outlook_mutations_stop_before_auth_or_network(command, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SUPER_AGENTS_APPROVAL_REQUESTS_FILE", str(tmp_path / "approvals.json"))
    factory = Mock(side_effect=AssertionError("No network allowed"))
    monkeypatch.setattr(cli, "configured_client", factory)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--provider", "outlook", *command, "--account", "school"])
    assert exc.value.code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "approval_required"
    assert "outlook" in result["approval"]["action"]
    assert result["approval"]["details"]["provider"] == "outlook"
    factory.assert_not_called()


def test_full_body_is_bound_to_approval_not_only_preview(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SUPER_AGENTS_APPROVAL_REQUESTS_FILE", str(tmp_path / "approvals.json"))
    approvals = []
    for suffix in ("one", "two"):
        with pytest.raises(SystemExit):
            cli.main(
                [
                    "--provider",
                    "outlook",
                    "draft-new",
                    "--to",
                    "a@example.com",
                    "--subject",
                    "Hi",
                    "--body",
                    "x" * 500 + suffix,
                ]
            )
        approvals.append(json.loads(capsys.readouterr().out)["approval"])
    assert approvals[0]["details"]["body_preview"] == approvals[1]["details"]["body_preview"]
    assert approvals[0]["id"] != approvals[1]["id"]


def test_sender_permissions_are_provider_and_account_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTLOOK_CLI_CONFIG_DIR", str(tmp_path / "outlook"))
    monkeypatch.setenv("GMAIL_CLI_APPROVED_SENDERS", "gmail@example.com")
    monkeypatch.setenv("GMAIL_CLI_APPROVED_SENDERS_PATH", str(tmp_path / "gmail.json"))
    approved_senders.add_approved_senders(["school@example.com"], "school", provider="outlook")
    assert approved_senders.load_approved_senders("school", provider="outlook").senders == {
        "school@example.com",
    }
    assert approved_senders.load_approved_senders("other", provider="outlook").senders == set()
    assert approved_senders.load_approved_senders("school").senders == {"gmail@example.com"}


def test_provider_defaults_preserve_gmail_and_outlook_alias():
    assert cli.build_parser().parse_args(["auth", "accounts"]).provider == "gmail"
    assert (
        cli.build_parser(default_provider="outlook").parse_args(["auth", "accounts"]).provider
        == "outlook"
    )
