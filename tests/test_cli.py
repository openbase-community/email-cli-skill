from __future__ import annotations

import json

import pytest

from email_cli.cli import main


def test_approved_sender_add_prints_approval_required_without_mutation(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SUPER_AGENTS_APPROVAL_REQUESTS_FILE", str(tmp_path / "approvals.json"))
    with pytest.raises(SystemExit) as exc_info:
        main(["approved-senders", "add", "--account", "work", "alice@example.com"])

    assert exc_info.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "approval_required"
    assert payload["approval"]["action"] == "add_gmail_approved_senders"
    assert payload["approval"]["details"]["account"] == "work"
    assert payload["approval"]["details"]["senders"] == ["alice@example.com"]


def test_send_draft_prints_approval_required_without_gmail_call(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SUPER_AGENTS_APPROVAL_REQUESTS_FILE", str(tmp_path / "approvals.json"))
    with pytest.raises(SystemExit) as exc_info:
        main(["send-draft", "draft-1"])

    assert exc_info.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "approval_required"
    assert payload["approval"]["action"] == "send_gmail_draft"
    assert payload["approval"]["details"]["draft_id"] == "draft-1"
