from __future__ import annotations

import base64

from gmail_cli.drafts import build_reply_message


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def original_message() -> dict[str, object]:
    return {
        "id": "msg-1",
        "threadId": "thread-1",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Lauren Katz <lauren@example.com>"},
                {"name": "To", "value": "Gabe Montague <gabe@example.com>"},
                {"name": "Cc", "value": "Jesse <jesse@example.com>"},
                {"name": "Subject", "value": "Time to Connect"},
                {"name": "Date", "value": "Thu, 2 Jul 2026 12:45:07 -0700"},
                {"name": "Message-ID", "value": "<original@example.com>"},
                {"name": "References", "value": "<root@example.com>"},
            ],
            "body": {
                "data": b64("Hi Gabe,\n\nHere are a few times that work.\n\nBest,\nLauren"),
            },
        },
    }


def test_build_reply_message_preserves_headers_and_visible_trail() -> None:
    message = build_reply_message(
        sender="gabe@example.com",
        original_message=original_message(),
        body_text="Thursday works well for me.\n\nBest,\nGabe",
        reply_all=True,
    )

    body = message.get_content()
    assert message["Subject"] == "Re: Time to Connect"
    assert message["In-Reply-To"] == "<original@example.com>"
    assert message["References"] == "<root@example.com> <original@example.com>"
    assert "Lauren Katz <lauren@example.com>" in message["To"]
    assert "Jesse <jesse@example.com>" in message["Cc"]
    assert "Thursday works well for me." in body
    assert "On Thu, 2 Jul 2026 12:45:07 -0700 Lauren Katz <lauren@example.com> wrote:" in body
    assert "> Hi Gabe," in body
    assert "> Here are a few times that work." in body


def test_build_reply_message_can_skip_visible_trail() -> None:
    message = build_reply_message(
        sender="gabe@example.com",
        original_message=original_message(),
        body_text="Thursday works well for me.",
        include_quoted_history=False,
    )

    assert message.get_content().strip() == "Thursday works well for me."
