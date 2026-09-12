from __future__ import annotations

import base64

from email_cli.parsing import normalize_message, normalize_thread


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_normalize_message_prefers_plain_text_and_lists_attachment_metadata() -> None:
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "snippet": "hello",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "Subject", "value": "Test"},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": b64("<p>HTML <b>body</b></p>")},
                },
                {
                    "mimeType": "text/plain",
                    "body": {"data": b64("Plain body")},
                },
                {
                    "partId": "2",
                    "filename": "file.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "att-1", "size": 123},
                },
            ],
        },
    }

    normalized = normalize_message(message, include_body=True)

    assert normalized["headers"]["From"] == "sender@example.com"
    assert normalized["body"]["text"] == "Plain body"
    assert normalized["body"]["mime_preference"] == "text/plain"
    assert normalized["attachments"] == [
        {
            "filename": "file.pdf",
            "mime_type": "application/pdf",
            "attachment_id": "att-1",
            "size": 123,
            "part_id": "2",
        }
    ]


def test_normalize_message_uses_html_when_plain_text_is_absent() -> None:
    message = {
        "id": "msg-1",
        "payload": {
            "mimeType": "text/html",
            "body": {"data": b64("<html><body><h1>Hello</h1><p>World</p></body></html>")},
        },
    }

    normalized = normalize_message(message, include_body=True)

    assert normalized["body"]["text"] == "Hello\nWorld"
    assert normalized["body"]["mime_preference"] == "text/html"


def test_normalize_thread_truncates_bodies() -> None:
    thread = {
        "id": "thread-1",
        "messages": [
            {"id": "msg-1", "payload": {"mimeType": "text/plain", "body": {"data": b64("abcdef")}}}
        ],
    }

    normalized = normalize_thread(thread, include_body=True, max_body_chars=3)

    assert normalized["message_count"] == 1
    assert normalized["messages"][0]["body"]["text"] == "abc"
    assert normalized["messages"][0]["body"]["truncated"] is True
