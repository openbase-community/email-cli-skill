from __future__ import annotations

from unittest.mock import Mock

import pytest

from email_cli.approved_senders import ApprovedSenders
from email_cli.outlook_auth import OutlookCredentials
from email_cli.outlook_client import OutlookClient
from email_cli.outlook_parsing import METADATA_SELECT
from email_cli.safety import ConfirmationRequiredError


def message(id="m1", sender="alice@example.com", **extra):
    return {
        "id": id,
        "conversationId": "t1",
        "subject": "Hello",
        "from": {"emailAddress": {"address": sender, "name": "Alice"}},
        "sentDateTime": "2026-09-10T10:00:00Z",
        "isDraft": False,
        **extra,
    }


@pytest.fixture
def client():
    return OutlookClient(
        OutlookCredentials(
            "test-only", ["Mail.Read", "Mail.ReadWrite", "Mail.Send"], "me@example.com"
        ),
        ApprovedSenders(frozenset({"alice@example.com"})),
        transport=Mock(),
    )


def test_search_never_requests_or_returns_bodies(client):
    client.graph.page.return_value = {
        "value": [
            message(
                bodyPreview="secret",
                body={"content": "secret"},
                uniqueBody={"content": "secret"},
            )
        ]
    }
    result = client.search_messages(query="from:alice@example.com")
    assert "secret" not in str(result)
    assert client.graph.page.call_args.args[1]["$select"] == METADATA_SELECT
    assert client.graph.page.call_args.args[1]["$search"] == '"from:alice@example.com"'


def test_unapproved_sender_does_not_fetch_body(client):
    client.graph.request.return_value = message(sender="mallory@example.com", bodyPreview="secret")
    result = client.get_message(message_id="m1", include_body=True)
    assert result["content_redacted"]
    assert "body" not in result
    assert "secret" not in str(result)
    client.graph.request.assert_called_once_with(
        "GET",
        "/me/messages/m1",
        params={"$select": METADATA_SELECT},
    )


def test_display_name_cannot_approve_sender(client):
    msg = message(sender="mallory@example.com")
    msg["from"]["emailAddress"]["name"] = "alice@example.com"
    client.graph.request.return_value = msg
    assert client.get_message(message_id="m1", include_body=True)["content_redacted"]
    assert client.graph.request.call_count == 1


def test_approved_body_fetched_after_metadata_and_html_converted(client):
    client.graph.request.side_effect = [
        message(),
        message(
            body={"contentType": "html", "content": "<p>Hello world</p><script>secret</script>"},
        ),
    ]
    result = client.get_message(message_id="m1", include_body=True, max_body_chars=5)
    assert result["body"] == {"text": "Hello", "truncated": True}
    assert client.graph.request.call_args.kwargs["params"]["$select"] == METADATA_SELECT + ",body"


def test_sender_change_between_requests_fails_closed(client):
    client.graph.request.side_effect = [message(), message(sender="mallory@example.com")]
    with pytest.raises(PermissionError):
        client.get_message(message_id="m1", include_body=True)


def test_thread_fetches_only_approved_bodies_and_sorts(client):
    client.graph.all_pages.return_value = [
        message("m2", "mallory@example.com", sentDateTime="2026-09-11T10:00:00Z"),
        message(),
    ]
    client.graph.request.return_value = message(body={"contentType": "text", "content": "hello"})
    result = client.get_thread(thread_id="t1")
    assert [m["id"] for m in result["messages"]] == ["m1", "m2"]
    assert result["messages"][1]["content_redacted"]
    assert client.graph.request.call_count == 1


def test_thread_metadata_only_never_fetches_body(client):
    client.graph.all_pages.return_value = [message()]
    client.get_thread(thread_id="t1", include_body=False)
    client.graph.request.assert_not_called()


def test_reply_preserves_trail_and_native_conversation(client):
    client.graph.all_pages.return_value = [message(), message("draft", isDraft=True)]
    client.graph.request.side_effect = [
        message(body={"contentType": "text", "content": "Earlier email\n> Prior trail"}),
        {"id": "draft2", "conversationId": "t1", "bodyPreview": "private"},
    ]
    result = client.create_draft_reply(
        thread_id="t1", body_text="Thanks!", reply_all=True, confirm_create=True
    )
    call = client.graph.request.call_args
    assert call.args == ("POST", "/me/messages/m1/createReplyAll")
    content = call.kwargs["json"]["message"]["body"]["content"]
    assert "Thanks!" in content and "> Earlier email\n> > Prior trail" in content
    assert result["thread_id"] == "t1" and result["quoted_history_included"]
    assert "private" not in str(result)


def test_reply_unapproved_trail_is_not_fetched_or_written(client):
    client.graph.all_pages.return_value = [message(sender="mallory@example.com")]
    with pytest.raises(PermissionError):
        client.create_draft_reply(thread_id="t1", body_text="Reply", confirm_create=True)
    client.graph.request.assert_not_called()


def test_reply_without_history_never_fetches_body(client):
    client.graph.all_pages.return_value = [message(sender="mallory@example.com")]
    client.graph.request.return_value = {"id": "d1", "conversationId": "t1"}
    client.create_draft_reply(
        thread_id="t1", body_text="Reply", include_quoted_history=False, confirm_create=True
    )
    client.graph.request.assert_called_once_with(
        "POST",
        "/me/messages/m1/createReply",
        json={"message": {"body": {"contentType": "Text", "content": "Reply"}}},
    )


def test_draft_creation_parses_recipients_and_does_not_return_body(client):
    client.graph.request.return_value = {"id": "d1", "conversationId": "t1", "body": "private"}
    result = client.create_draft_new(
        to='"Doe, Alice" <alice@example.com>, bob@example.com',
        subject="Hello",
        body_text="private",
        confirm_create=True,
    )
    payload = client.graph.request.call_args.kwargs["json"]
    assert len(payload["toRecipients"]) == 2
    assert payload["toRecipients"][0]["emailAddress"]["name"] == "Doe, Alice"
    assert "private" not in str(result)


@pytest.mark.parametrize("operation", ["new", "reply", "send"])
@pytest.mark.parametrize("confirmed", [False, True])
def test_mutations_require_both_confirmation_and_scope(client, operation, confirmed):
    client.credentials.scopes = ["Mail.Read"]
    with pytest.raises(PermissionError if confirmed else ConfirmationRequiredError):
        if operation == "new":
            client.create_draft_new(
                to="alice@example.com", subject="hi", body_text="hi", confirm_create=confirmed
            )
        elif operation == "reply":
            client.create_draft_reply(thread_id="t1", body_text="hi", confirm_create=confirmed)
        else:
            client.send_draft(draft_id="d1", confirm_send=confirmed)
    client.graph.request.assert_not_called()
    client.graph.all_pages.assert_not_called()


def test_send_rejects_non_drafts(client):
    client.graph.request.return_value = message()
    with pytest.raises(ValueError, match="not a draft"):
        client.send_draft(draft_id="m1", confirm_send=True)
    assert client.graph.request.call_count == 1


def test_send_returns_acceptance_not_delivery(client):
    client.graph.request.side_effect = [message(isDraft=True), {}]
    result = client.send_draft(draft_id="m1", confirm_send=True)
    assert result["send_status"] == "accepted"
    client.graph.request.assert_called_with("POST", "/me/messages/m1/send")


def test_folder_tree_lists_nested_folders(client):
    client.graph.all_pages.side_effect = [
        [{"id": "root", "displayName": "Inbox", "childFolderCount": 1}],
        [{"id": "child", "displayName": "Projects", "parentFolderId": "root"}],
    ]
    result = client.list_labels()
    assert [f["id"] for f in result["folders"]] == ["root", "child"]
    assert client.graph.all_pages.call_args.args[0] == "/me/mailFolders/root/childFolders"


def test_multiple_folder_filters_are_rejected(client):
    with pytest.raises(ValueError, match="one --folder-id"):
        client.search_messages(query="hi", label_ids=["inbox", "sentitems"])
    client.graph.page.assert_not_called()
