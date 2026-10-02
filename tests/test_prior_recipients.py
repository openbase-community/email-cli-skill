from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from test_client_security import message

from email_cli.approved_senders import ApprovedSenders
from email_cli.client import GmailClient
from email_cli.prior_recipients import GmailPriorRecipients, previous_recipient_reads_enabled


def sent_message(recipient="Alice <alice@example.com>", field="To", labels=None):
    return {
        "id": "sent-1",
        "labelIds": ["SENT"] if labels is None else labels,
        "payload": {"headers": [{"name": field, "value": recipient}]},
    }


def service_with_sent(sent):
    service = Mock()
    api = service.users.return_value.messages.return_value
    api.list.return_value.execute.return_value = {"messages": [{"id": "sent-1"}]}
    api.get.return_value.execute.return_value = sent
    return service, api


@pytest.mark.parametrize("field", ["To", "Cc", "Bcc"])
def test_matches_exact_normalized_sent_recipient_using_metadata_only(field):
    service, api = service_with_sent(sent_message('"Example, Alice" <ALICE@Example.com>', field))
    history = GmailPriorRecipients(service)
    incoming = message("incoming", "Alice <alice@example.com>")
    assert history.evidence_for(incoming) == "sent-1"
    assert history.evidence_for(incoming) == "sent-1"
    api.list.assert_called_once()
    assert api.list.call_args.kwargs["labelIds"] == ["SENT"]
    api.get.assert_called_once_with(
        userId="me", id="sent-1", format="metadata", metadataHeaders=["To", "Cc", "Bcc"]
    )


@pytest.mark.parametrize("sent", [
    sent_message("notalice@example.com"),
    sent_message("alice@other.example"),
    sent_message(labels=["DRAFT"]),
    sent_message(labels=["SENT", "DRAFT"]),
    sent_message(labels=["INBOX"]),
    sent_message(field="From"),
])
def test_search_result_alone_does_not_grant_access(sent):
    service, _ = service_with_sent(sent)
    assert GmailPriorRecipients(service).evidence_for(message("m", "alice@example.com")) is None


def test_ambiguous_or_missing_sender_does_not_search():
    service, api = service_with_sent(sent_message())
    history = GmailPriorRecipients(service)
    for sender in ("", "invalid", "alice@example.com, other@example.com"):
        assert history.evidence_for(message("m", sender)) is None
    api.list.assert_not_called()


def test_checks_later_pages():
    service, api = service_with_sent(sent_message())
    api.list.return_value.execute.side_effect = [
        {"messages": [], "nextPageToken": "next"}, {"messages": [{"id": "sent-1"}]}
    ]
    assert GmailPriorRecipients(service).evidence_for(message("m", "alice@example.com"))
    assert api.list.call_args.kwargs["pageToken"] == "next"


def make_client(*, allowed=True, recipient="alice@example.com", full_sender="alice@example.com"):
    service, api = service_with_sent(sent_message(recipient))
    data = {
        ("m", "metadata"): message("m", "alice@example.com"),
        ("m", "full"): message("m", full_sender, "readable body"),
        ("sent-1", "metadata"): sent_message(recipient),
    }
    api.get.side_effect = lambda **kw: Mock(execute=lambda: data[(kw["id"], kw["format"])])
    approved = ApprovedSenders(frozenset())
    client = GmailClient(service, approved_senders=approved, allow_previous_recipients=allowed)
    return client, api


def test_client_releases_body_with_evidence_without_changing_allowlist():
    client, api = make_client()
    result = client.get_message(message_id="m", include_body=True)
    assert result["body"]["text"] == "readable body"
    assert not result["content_redacted"]
    assert not result["sender_approved"]
    assert result["read_access"] == {"basis": "previous_recipient", "sent_message_id": "sent-1"}
    assert client.approved_senders.senders == frozenset()
    assert api.get.call_args.kwargs["format"] == "full"


@pytest.mark.parametrize("allowed,include_body,recipient", [
    (False, True, "alice@example.com"),
    (True, False, "alice@example.com"),
    (True, True, "other@example.com"),
])
def test_no_body_without_matching_enabled_policy(allowed, include_body, recipient):
    client, api = make_client(allowed=allowed, recipient=recipient)
    result = client.get_message(message_id="m", include_body=include_body)
    assert "body" not in result
    assert all(c.kwargs["format"] == "metadata" for c in api.get.call_args_list)
    if not allowed or not include_body:
        api.list.assert_not_called()


def test_sender_change_fails_closed():
    client, _ = make_client(full_sender="different@example.com")
    with pytest.raises(PermissionError, match="identity changed"):
        client.get_message(message_id="m", include_body=True)


def test_history_failure_does_not_fetch_body():
    client, api = make_client()
    api.list.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError):
        client.get_message(message_id="m", include_body=True)
    assert all(c.kwargs["format"] == "metadata" for c in api.get.call_args_list)


def test_configuration_is_opt_in_and_account_scoped(tmp_path, monkeypatch):
    path = tmp_path / "read-access.json"
    monkeypatch.setenv("EMAIL_CLI_READ_ACCESS_CONFIG", str(path))
    assert not previous_recipient_reads_enabled("work")
    path.write_text(json.dumps({"previous_recipients": {"gmail": ["work"]}}))
    assert previous_recipient_reads_enabled("work")
    assert not previous_recipient_reads_enabled("personal")
    assert not previous_recipient_reads_enabled(None)
    path.write_text(json.dumps({"previous_recipients": {"gmail": "work"}}))
    with pytest.raises(ValueError):
        previous_recipient_reads_enabled("work")


def test_thread_checks_each_sender_independently():
    client, api = make_client()
    incoming = message("m", "alice@example.com")
    unknown = message("unknown", "other@example.com")
    client.service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "id": "thread-1", "messages": [incoming, unknown]
    }
    result = client.get_thread(thread_id="thread-1")
    assert result["messages"][0]["body"]["text"] == "readable body"
    assert result["messages"][1]["content_redacted"]
    assert not any(
        c.kwargs["id"] == "unknown" and c.kwargs["format"] == "full"
        for c in api.get.call_args_list
    )


def test_history_cache_is_not_shared_between_accounts():
    first, _ = service_with_sent(sent_message())
    second, _ = service_with_sent(sent_message("other@example.com"))
    incoming = message("m", "alice@example.com")
    assert GmailPriorRecipients(first).evidence_for(incoming) == "sent-1"
    assert GmailPriorRecipients(second).evidence_for(incoming) is None
