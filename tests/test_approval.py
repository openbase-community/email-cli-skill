from __future__ import annotations

import json

import pytest

from gmail_cli.approval import (
    ApprovalRequest,
    ApprovalRequiredError,
    read_approval_store,
    require_user_approval,
)


def test_require_user_approval_records_dashboard_request(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SUPER_AGENTS_APPROVAL_REQUESTS_FILE", str(tmp_path / "approvals.json"))
    with pytest.raises(ApprovalRequiredError) as exc_info:
        require_user_approval(
            False,
            action="send_gmail_draft",
            prompt="Send draft?",
            details={"draft_id": "draft-1"},
        )

    payload = exc_info.value.request.as_dict()
    assert payload["status"] == "approval_required"
    assert payload["approval"]["action"] == "send_gmail_draft"
    assert payload["approval"]["dashboard_url"] == "http://localhost:7999/dashboard/approvals"

    store = read_approval_store()
    request = ApprovalRequest(
        action="send_gmail_draft",
        prompt="Send draft?",
        details={"draft_id": "draft-1"},
    )
    assert store["requests"][request.id]["method"] == "exec/requestApproval"
    assert store["requests"][request.id]["params"]["toolName"] == "gmail-cli"


def test_require_user_approval_allows_after_dashboard_accept(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SUPER_AGENTS_APPROVAL_REQUESTS_FILE", str(tmp_path / "approvals.json"))
    request = ApprovalRequest(
        action="send_gmail_draft",
        prompt="Send draft?",
        details={"draft_id": "draft-1"},
    )
    approval_file = tmp_path / "approvals.json"
    approval_file.write_text(
        json.dumps(
            {
                "requests": {
                    request.id: {
                        "id": request.id,
                        "method": "exec/requestApproval",
                        "params": {},
                    }
                },
                "decisions": {request.id: {"decision": "accept"}},
            }
        ),
        encoding="utf-8",
    )

    require_user_approval(
        False,
        action="send_gmail_draft",
        prompt="Send draft?",
        details={"draft_id": "draft-1"},
    )

    assert read_approval_store() == {"requests": {}, "decisions": {}}


def test_require_user_approval_allows_with_user_approval() -> None:
    require_user_approval(
        True,
        action="send_gmail_draft",
        prompt="Send draft?",
        details={"draft_id": "draft-1"},
    )
