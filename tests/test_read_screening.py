from __future__ import annotations

import base64
import json
from unittest.mock import Mock

import pytest
import requests
from test_client_security import FakeGmailService, message

from email_cli.approved_senders import ApprovedSenders
from email_cli.client import GmailClient
from email_cli.outlook_client import OutlookClient
from email_cli.read_screening import ReadScreener, ScreeningDecision, configured_screener
from email_cli.screening_content import apple_mail_state, gmail_state, outlook_state
from email_cli.screening_policy import MAX_STATE_CHARS, MODEL, QUESTIONS


def response(**risks):
    return {
        "model": MODEL,
        "answers": {name: {"type": "noul", "noul": risks.get(name, 0)} for name in QUESTIONS},
        "usage": {"input_tokens": 500},
    }


def screener(payload=None, status=200):
    transport = Mock()
    transport.post.return_value.status_code = status
    transport.post.return_value.json.return_value = payload or response()
    return ReadScreener("test-only", transport=transport)


def test_approve_requires_every_probability_below_threshold():
    assert screener().evaluate({"parts": []}).approved
    for key in QUESTIONS:
        result = screener(response(**{key: 0.151})).evaluate({"parts": []})
        assert not result.approved
        assert result.reasons == [key]


@pytest.mark.parametrize("value", [True, "0", None, -1, 1.1, float("nan"), float("inf")])
def test_invalid_scores_fail_closed(value):
    assert not screener(response(unfamiliar_site=value)).evaluate({}).approved


@pytest.mark.parametrize("status", [301, 401, 429, 500, 529])
def test_http_failures_keep_body_withheld(status):
    s = screener(status=status)
    assert not s.evaluate({}).approved
    assert s.transport.post.call_args.kwargs["allow_redirects"] is False


def test_missing_answer_and_model_change_fail_closed():
    payload = response()
    del payload["answers"]["package_reference"]
    assert not screener(payload).evaluate({}).approved
    payload = response()
    payload["model"] = "jev-new-version"
    assert not screener(payload).evaluate({}).approved


def test_network_error_is_redacted_and_does_not_leak_error_text():
    s = screener()
    s.transport.post.side_effect = requests.Timeout("private request text")
    result = s.evaluate({"parts": []}).as_dict()
    assert result["decision"] == "flagged"
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "state",
    [
        {"attachments": ["brief.pdf"]},
        {"incomplete": True},
        {"body": "x" * MAX_STATE_CHARS},
    ],
)
def test_uninspected_content_never_auto_approves(state):
    s = screener()
    assert not s.evaluate(state).approved
    s.transport.post.assert_not_called()


def test_audit_records_decision_without_body_or_key(tmp_path):
    s = screener()
    s.audit_path = tmp_path
    s.evaluate({"body": "PRIVATE BODY"}, message_id="msg-1")
    (path,) = tmp_path.glob("*.json")
    data = path.read_text()
    assert "PRIVATE BODY" not in data and "test-only" not in data
    assert json.loads(data)["message_id"] == "msg-1"
    assert path.stat().st_mode & 0o777 == 0o600


def test_account_provider_opt_in_and_missing_key(tmp_path, monkeypatch):
    config = tmp_path / "screening.json"
    config.write_text(json.dumps({"enabled_accounts": {"gmail": ["work"]}}))
    monkeypatch.setenv("EMAIL_CLI_SCREENING_CONFIG", str(config))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert configured_screener("other", "gmail") is None
    assert configured_screener("work", "outlook") is None
    assert not configured_screener("work", "gmail").evaluate({}).approved


def test_mime_all_alternatives_and_html_attributes_are_preserved():
    m = message("m", "sender@example.com", "safe text")
    m["payload"]["parts"] = [
        {
            "mimeType": "text/html",
            "body": {
                "data": base64.urlsafe_b64encode(
                    b'<a href="https://unknown.example">safe</a>'
                ).decode()
            },
        }
    ]
    state = gmail_state(m)
    assert len(state["parts"]) == 2
    assert "unknown.example" in state["parts"][1]["content"]
    assert not state["incomplete"]


def test_malformed_or_external_mime_is_not_clean():
    m = message("m", "sender@example.com")
    m["payload"]["body"] = {"data": "!invalid!"}
    assert gmail_state(m)["incomplete"]
    m["payload"]["body"] = {"attachmentId": "a", "size": 100}
    assert gmail_state(m)["attachments"]
    assert outlook_state({})["incomplete"]


def gmail_client(approved):
    service = FakeGmailService()
    service.messages[("m", "metadata")] = message("m", "unknown@example.com")
    service.messages[("m", "full")] = message("m", "unknown@example.com", "PRIVATE BODY")
    service.threads[("thread-1", "metadata")] = {
        "id": "thread-1",
        "messages": [service.messages[("m", "metadata")]],
    }
    s = Mock()
    s.evaluate.return_value = ScreeningDecision(approved, ["test"])
    return GmailClient(service, approved_senders=ApprovedSenders(frozenset()), read_screener=s)


@pytest.mark.parametrize("thread", [False, True])
@pytest.mark.parametrize("approved", [False, True])
def test_gmail_release_is_per_message_with_no_sender_grant(thread, approved):
    client = gmail_client(approved)
    result = (
        client.get_thread(thread_id="thread-1")["messages"][0]
        if thread
        else (client.get_message(message_id="m", include_body=True))
    )
    assert result["sender_approved"] is False
    assert ("PRIVATE BODY" in json.dumps(result)) is approved
    assert result["content_redacted"] is not approved
    assert not client.approved_senders.senders


def test_gmail_metadata_read_does_not_screen_or_fetch_body():
    client = gmail_client(True)
    client.get_message(message_id="m", include_body=False)
    client.read_screener.evaluate.assert_not_called()
    assert len(client.service.calls) == 1


def test_gmail_changed_identity_refused():
    client = gmail_client(True)
    client.service.messages[("m", "full")]["id"] = "other"
    with pytest.raises(PermissionError):
        client.get_message(message_id="m", include_body=True)


@pytest.mark.parametrize("approved", [False, True])
def test_outlook_screening_preserves_html_and_redacts_flagged_body(approved):
    metadata = {"id": "m", "from": {"emailAddress": {"address": "unknown@example.com"}}}
    full = {**metadata, "body": {"contentType": "html", "content": "PRIVATE BODY"}}
    graph = Mock()
    graph.request.side_effect = [metadata, full]
    s = Mock()
    s.evaluate.return_value = ScreeningDecision(approved, ["test"])
    client = OutlookClient(None, ApprovedSenders(frozenset()), transport=graph, read_screener=s)
    result = client.get_message(message_id="m", include_body=True)
    assert ("PRIVATE BODY" in json.dumps(result)) is approved
    assert not result["sender_approved"]
    assert s.evaluate.call_args.args[0]["parts"][0]["content"] == "PRIVATE BODY"


def test_apple_raw_mime_keeps_hidden_links():
    state = apple_mail_state(
        "Subject: hello\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        '<a href="https://unknown.example">notes</a>'
    )
    assert "unknown.example" in state["parts"][0]["content"]
    assert not state["incomplete"]


@pytest.mark.parametrize(
    "url",
    [
        "https://githuub.com/login",
        "https://github.com.evil.example/repo",
        "https://github.com@evil.example/repo",
        "https://gіthub.com/login",
        "https://xn--gthub-9za.com",
        "https://%67ithub.com",
        "http://192.0.2.5/setup",
        "https://google.com/url?q=https%3A%2F%2Fevil.example",
    ],
)
def test_deceptive_urls_flag_even_if_model_would_approve(url):
    s = screener()
    assert not s.evaluate({"parts": [{"content": url}]}).approved
    s.transport.post.assert_not_called()


def test_known_hostname_is_not_an_automatic_grant():
    s = screener(response(unfamiliar_repository=0.99))
    assert not s.evaluate({"body": "https://github.com/unknown/new-project"}).approved
    assert s.transport.post.called


def test_html_entity_destination_is_decoded():
    s = screener()
    assert not s.evaluate({"body": '<a href="https://githuub&#46;com">Notes</a>'}).approved


def test_no_content_is_reused_for_future_message_from_same_sender():
    client = gmail_client(True)
    assert "body" in client.get_message(message_id="m", include_body=True)
    client.read_screener.evaluate.return_value = ScreeningDecision(False, ["unknown_site"])
    assert "body" not in client.get_message(message_id="m", include_body=True)
    assert client.read_screener.evaluate.call_count == 2


@pytest.mark.parametrize("approved", [False, True])
def test_apple_mail_screening_releases_only_screened_source(approved):
    from email_cli.apple_mail_client import AppleMailClient

    transport = Mock()
    metadata = {"local_id": 7, "internet_message_id": "m1", "from": "unknown@example.com"}
    transport.side_effect = [
        metadata,
        {
            "source": (
                "Subject: Hello\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPRIVATE BODY"
            )
        },
    ]
    s = Mock()
    s.evaluate.return_value = ScreeningDecision(approved, ["test"])
    client = AppleMailClient(
        {"account_id": "a", "email": "me@example.com"},
        ApprovedSenders(frozenset()),
        transport=transport,
        read_screener=s,
    )
    message_id = client._id("message", folder=["Inbox"], local_id=7, internet_message_id="m1")
    result = client.get_message(message_id=message_id, include_body=True)
    assert ("PRIVATE BODY" in json.dumps(result)) is approved
    assert result["body_access_allowed"] is approved
    assert [c.args[0] for c in transport.call_args_list] == ["message", "screening-source"]


def test_screening_never_changes_draft_approval_gate(monkeypatch):
    from email_cli.approval import ApprovalRequiredError
    from email_cli.cli import dispatch
    from email_cli.cli_parser import build_parser

    def refuse(*args, **kwargs):
        raise PermissionError("manual write approval still required")

    monkeypatch.setattr("email_cli.cli.require_user_approval", refuse)
    args = build_parser().parse_args(
        ["draft-new", "--to", "other@example.com", "--subject", "Hello", "--body", "Thanks"]
    )
    with pytest.raises((PermissionError, ApprovalRequiredError)):
        dispatch(args)
