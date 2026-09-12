import json
import subprocess

import pytest

from email_cli.apple_mail_auth import config_path, dispatch_auth, load_account
from email_cli.apple_mail_client import AppleMailClient, search_terms
from email_cli.apple_mail_transport import call_mail
from email_cli.approved_senders import ApprovedSenders, load_approved_senders
from email_cli.cli import dispatch
from email_cli.cli_parser import build_parser


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("APPLE_MAIL_CLI_CONFIG_DIR", str(tmp_path))
    calls = []
    metadata = {
        "local_id": 1,
        "internet_message_id": "one@example.test",
        "from": "Alice <alice@example.test>",
        "subject": "Hello",
        "read": False,
        "received": "2026-01-01T00:00:00Z",
    }
    draft = {
        "local_id": 123,
        "sender": "me@example.test",
        "subject": "Hi",
        "body": "hello",
        "to": ["alice@example.test"],
        "cc": [],
        "bcc": [],
    }

    def transport(action, **kwargs):
        calls.append((action, kwargs))
        if action == "message":
            return metadata.copy()
        if action == "body":
            assert kwargs["expected_sender"] == metadata["from"]
            return {"body": "quoted text"[: kwargs["max_chars"]]}
        if action == "search":
            return {
                "messages": [metadata.copy()],
                "next_offset": 1,
                "scanned": 1,
                "mailbox_message_count": 3,
            }
        if action in {"draft-new", "draft-reply", "draft"}:
            return draft.copy()
        if action == "send":
            assert kwargs["expected_draft"] == draft
            return {"accepted": True}
        raise AssertionError(action)

    account = {
        "account_id": "account-one",
        "email": "me@example.test",
        "compose": True,
        "send": True,
    }
    client = AppleMailClient(
        account, ApprovedSenders(frozenset()), account_name="school", transport=transport
    )
    return client, calls, metadata, draft


def message_id(client):
    return client._id(
        "message", folder=["Inbox"], local_id=1, internet_message_id="one@example.test"
    )


def test_unapproved_body_never_requested(setup):
    client, calls, _, _ = setup
    result = client.get_message(message_id=message_id(client), include_body=True)
    assert result["body_omitted_reason"] == "sender_not_approved"
    assert [c[0] for c in calls] == ["message"]


def test_approved_body_bounded_and_sender_rechecked(setup):
    client, calls, _, _ = setup
    client.approved_senders = ApprovedSenders(frozenset({"alice@example.test"}))
    result = client.get_message(message_id=message_id(client), include_body=True, max_body_chars=3)
    assert result["body"] == "quo"
    assert result["body_truncated"]
    assert calls[-1][1]["max_chars"] == 4
    assert calls[-1][1]["expected_sender"] == "Alice <alice@example.test>"


def test_forged_display_name_is_not_approved(setup):
    client, _, metadata, _ = setup
    client.approved_senders = ApprovedSenders(frozenset({"alice@example.test"}))
    metadata["from"] = '"alice@example.test" <attacker@example.test>'
    assert not client.get_message(message_id=message_id(client))["body_access_allowed"]


def test_cross_account_id_rejected_before_transport(setup):
    client, calls, _, _ = setup
    identifier = message_id(client)
    client.account["account_id"] = "account-two"
    with pytest.raises(ValueError, match="different account"):
        client.get_message(message_id=identifier)
    assert not calls


def test_pagination_bound_to_search(setup):
    client, calls, _, _ = setup
    page = client.search_messages(query="subject:Hello")["next_page_token"]
    with pytest.raises(ValueError, match="does not match"):
        client.search_messages(query="subject:Other", page_token=page)
    client.search_messages(query="subject:Hello", page_token=page)
    assert calls[-1][1]["offset"] == 1


def test_query_rejects_unsupported_body_search():
    with pytest.raises(ValueError):
        search_terms("body:secret")
    assert search_terms('subject:"two words"') == [{"field": "subject", "value": "two words"}]


def test_sender_configuration_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("APPLE_MAIL_CLI_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("GMAIL_CLI_APPROVED_SENDERS", "gmail@example.test")
    monkeypatch.setenv("OUTLOOK_CLI_APPROVED_SENDERS", "outlook@example.test")
    monkeypatch.delenv("APPLE_MAIL_CLI_APPROVED_SENDERS", raising=False)
    assert not load_approved_senders("school", provider="apple-mail").senders


def test_binding_requires_exact_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("APPLE_MAIL_CLI_CONFIG_DIR", str(tmp_path))
    accounts = [{"id": "one", "enabled": True, "emails": ["me@example.test"]}]
    monkeypatch.setattr(
        "email_cli.apple_mail_auth.call_mail", lambda action: {"accounts": accounts}
    )
    args = build_parser(default_provider="apple-mail").parse_args(
        ["auth", "login", "--account", "school", "--username", "me@example.test"]
    )
    dispatch_auth(args)
    assert load_account("school")["account_id"] == "one"
    assert config_path("school").stat().st_mode & 0o777 == 0o600
    accounts[0]["id"] = "two"
    with pytest.raises(ValueError, match="identity changed"):
        dispatch_auth(args)


def test_compose_disabled_before_write(setup):
    client, calls, _, _ = setup
    client.account["compose"] = False
    with pytest.raises(PermissionError):
        client.create_draft_new(
            to="alice@example.test", subject="Hi", body_text="hello", confirm_create=True
        )
    assert not calls


def test_reply_uses_native_message_and_quote_gate(setup):
    client, calls, _, _ = setup
    with pytest.raises(PermissionError):
        client.create_draft_reply(
            thread_id=message_id(client), body_text="Reply", confirm_create=True
        )
    assert not any(action == "draft-reply" for action, _ in calls)
    client.approved_senders = ApprovedSenders(frozenset({"alice@example.test"}))
    result = client.create_draft_reply(
        thread_id=message_id(client), body_text="Reply", confirm_create=True
    )
    assert result["quoted_history_included"]
    assert calls[-1][0] == "draft-reply"
    assert "> quoted text" in calls[-1][1]["body"]


def test_send_refuses_changed_draft(setup):
    client, calls, _, draft = setup
    result = client.create_draft_new(
        to="alice@example.test", subject="Hi", body_text="hello", confirm_create=True
    )
    draft["to"] = ["different@example.test"]
    with pytest.raises(ValueError, match="changed"):
        client.send_draft(draft_id=result["draft_id"], confirm_send=True)
    assert not any(action == "send" for action, _ in calls)


def test_send_cannot_repeat(setup):
    client, calls, _, _ = setup
    result = client.create_draft_new(
        to="alice@example.test", subject="Hi", body_text="hello", confirm_create=True
    )
    assert (
        client.send_draft(draft_id=result["draft_id"], confirm_send=True)["send_status"]
        == "accepted"
    )
    with pytest.raises(ValueError, match="already attempted"):
        client.send_draft(draft_id=result["draft_id"], confirm_send=True)
    assert [action for action, _ in calls].count("send") == 1


def test_ambiguous_send_stays_blocked(setup):
    client, _, _, _ = setup
    result = client.create_draft_new(
        to="alice@example.test", subject="Hi", body_text="hello", confirm_create=True
    )
    original_transport = client.transport

    def transport(action, **kwargs):
        if action == "send":
            raise RuntimeError("timeout")
        return original_transport(action, **kwargs)

    client.transport = transport
    with pytest.raises(RuntimeError, match="timeout"):
        client.send_draft(draft_id=result["draft_id"], confirm_send=True)
    with pytest.raises(ValueError, match="already attempted"):
        client.send_draft(draft_id=result["draft_id"], confirm_send=True)


def test_transport_keeps_values_out_of_source_and_argv(monkeypatch):
    monkeypatch.setattr("email_cli.apple_mail_transport.sys.platform", "darwin")

    def run(argv, **kwargs):
        assert "private body" not in " ".join(argv)
        assert json.loads(kwargs["input"])["body"] == "private body"
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(argv, 0, stdout='{"accepted": true}', stderr="")

    monkeypatch.setattr("email_cli.apple_mail_transport.subprocess.run", run)
    assert call_mail("draft-new", body="private body")["accepted"]


def test_cli_approval_stops_before_client(monkeypatch):
    args = build_parser(default_provider="apple-mail").parse_args(
        [
            "draft-new",
            "--account",
            "school",
            "--to",
            "alice@example.test",
            "--subject",
            "Hi",
            "--body",
            "hello",
        ]
    )

    def approval(*args, **kwargs):
        assert kwargs["details"]["provider"] == "apple-mail"
        raise PermissionError("approval required")

    monkeypatch.setattr("email_cli.cli.require_user_approval", approval)
    with pytest.raises(PermissionError, match="approval required"):
        dispatch(args)
