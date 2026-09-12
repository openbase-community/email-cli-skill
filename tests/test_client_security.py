from __future__ import annotations

import base64
from typing import Any

from email_cli.approved_senders import ApprovedSenders
from email_cli.client import GmailClient


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def message(message_id: str, sender: str, body: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mimeType": "text/plain",
        "headers": [
            {"name": "From", "value": sender},
            {"name": "Subject", "value": f"Subject {message_id}"},
        ],
    }
    if body is not None:
        payload["body"] = {"data": b64(body)}
    return {
        "id": message_id,
        "threadId": "thread-1",
        "snippet": f"snippet {message_id}",
        "payload": payload,
    }


class FakeRequest:
    def __init__(self, response: dict[str, Any]):
        self.response = response

    def execute(self) -> dict[str, Any]:
        return self.response


class FakeMessages:
    def __init__(self, service: FakeGmailService):
        self.service = service

    def get(self, **params: Any) -> FakeRequest:
        self.service.calls.append(("messages.get", params))
        message_id = params["id"]
        message_format = params["format"]
        if message_format == "full" and message_id in self.service.blocked_full_ids:
            raise AssertionError(f"full message fetch was blocked for {message_id}")
        return FakeRequest(self.service.messages[(message_id, message_format)])

    def list(self, **params: Any) -> FakeRequest:
        self.service.calls.append(("messages.list", params))
        return FakeRequest(
            {
                "messages": [
                    {
                        "id": "msg-1",
                        "threadId": "thread-1",
                        "snippet": "body-like snippet",
                        "payload": {"body": {"data": b64("hidden")}},
                    }
                ]
            }
        )


class FakeThreads:
    def __init__(self, service: FakeGmailService):
        self.service = service

    def get(self, **params: Any) -> FakeRequest:
        self.service.calls.append(("threads.get", params))
        return FakeRequest(self.service.threads[(params["id"], params["format"])])


class FakeUsers:
    def __init__(self, service: FakeGmailService):
        self.service = service

    def messages(self) -> FakeMessages:
        return FakeMessages(self.service)

    def threads(self) -> FakeThreads:
        return FakeThreads(self.service)


class FakeGmailService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.blocked_full_ids: set[str] = set()
        self.messages: dict[tuple[str, str], dict[str, Any]] = {}
        self.threads: dict[tuple[str, str], dict[str, Any]] = {}

    def users(self) -> FakeUsers:
        return FakeUsers(self)


def test_get_message_does_not_fetch_full_body_for_unapproved_sender() -> None:
    service = FakeGmailService()
    service.blocked_full_ids.add("unapproved")
    service.messages[("unapproved", "metadata")] = message(
        "unapproved",
        "Mallory <mallory@example.com>",
    )
    client = GmailClient(
        service=service,
        approved_senders=ApprovedSenders(frozenset({"alice@example.com"})),
    )

    result = client.get_message(message_id="unapproved", include_body=True)

    assert result["content_redacted"] is True
    assert result["snippet"] is None
    assert "body" not in result
    assert [call[1]["format"] for call in service.calls] == ["metadata"]


def test_get_message_fetches_body_for_approved_sender() -> None:
    service = FakeGmailService()
    service.messages[("approved", "metadata")] = message(
        "approved",
        "Alice <ALICE@example.com>",
    )
    service.messages[("approved", "full")] = message(
        "approved",
        "Alice <ALICE@example.com>",
        body="approved body",
    )
    client = GmailClient(
        service=service,
        approved_senders=ApprovedSenders(frozenset({"alice@example.com"})),
    )

    result = client.get_message(message_id="approved", include_body=True)

    assert result["content_redacted"] is False
    assert result["body"]["text"] == "approved body"
    assert [call[1]["format"] for call in service.calls] == ["metadata", "full"]


def test_get_thread_fetches_full_only_for_approved_messages() -> None:
    service = FakeGmailService()
    service.blocked_full_ids.add("unapproved")
    service.threads[("thread-1", "metadata")] = {
        "id": "thread-1",
        "messages": [
            message("approved", "alice@example.com"),
            message("unapproved", "mallory@example.com"),
        ],
    }
    service.messages[("approved", "full")] = message(
        "approved",
        "alice@example.com",
        body="approved thread body",
    )
    client = GmailClient(
        service=service,
        approved_senders=ApprovedSenders(frozenset({"alice@example.com"})),
    )

    result = client.get_thread(thread_id="thread-1", include_body=True)

    assert result["messages"][0]["body"]["text"] == "approved thread body"
    assert result["messages"][1]["content_redacted"] is True
    assert [call for call in service.calls if call[0] == "messages.get"] == [
        (
            "messages.get",
            {
                "userId": "me",
                "id": "approved",
                "format": "full",
            },
        )
    ]


def test_search_messages_strips_snippet_like_fields() -> None:
    service = FakeGmailService()
    client = GmailClient(service=service)

    result = client.search_messages(query="from:anyone", max_results=1)

    assert result["messages"] == [{"id": "msg-1", "threadId": "thread-1"}]
