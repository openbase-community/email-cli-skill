from __future__ import annotations

import base64
from email import message_from_bytes, policy

from bs4 import BeautifulSoup

from email_cli.drafts import build_new_message, build_reply_message


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def original_message() -> dict[str, object]:
    return {
        "id": "msg-1",
        "threadId": "thread-1",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Jordan Lee <jordan@example.com>"},
                {"name": "To", "value": "Casey Morgan <casey@example.com>"},
                {"name": "Cc", "value": "Jesse <jesse@example.com>"},
                {"name": "Subject", "value": "Time to Connect"},
                {"name": "Date", "value": "Thu, 2 Jul 2026 12:45:07 -0700"},
                {"name": "Message-ID", "value": "<original@example.com>"},
                {"name": "References", "value": "<root@example.com>"},
            ],
            "body": {
                "data": b64("Hi Casey,\n\nHere are a few times that work.\n\nBest,\nJordan"),
            },
        },
    }


def test_build_reply_message_preserves_headers_and_visible_trail() -> None:
    message = build_reply_message(
        sender="casey@example.com",
        original_message=original_message(),
        body_text="Thursday works well for me.\n\nBest,\nCasey",
        reply_all=True,
    )

    body = message.get_body(preferencelist=("plain",)).get_content()
    assert message["Subject"] == "Re: Time to Connect"
    assert message["In-Reply-To"] == "<original@example.com>"
    assert message["References"] == "<root@example.com> <original@example.com>"
    assert "Jordan Lee <jordan@example.com>" in message["To"]
    assert "Jesse <jesse@example.com>" in message["Cc"]
    assert "Thursday works well for me." in body
    assert "On Thu, 2 Jul 2026 12:45:07 -0700 Jordan Lee <jordan@example.com> wrote:" in body
    assert "> Hi Casey," in body
    assert "> Here are a few times that work." in body


def test_build_reply_message_can_skip_visible_trail() -> None:
    message = build_reply_message(
        sender="casey@example.com",
        original_message=original_message(),
        body_text="Thursday works well for me.",
        include_quoted_history=False,
    )

    body = message.get_body(preferencelist=("plain",)).get_content()
    assert body.strip() == "Thursday works well for me."


def with_recipients(sender: str, to: str, cc: str = "") -> dict:
    original = original_message()
    values = {"From": sender, "To": to, "Cc": cc}
    for header in original["payload"]["headers"]:
        if header["name"] in values:
            header["value"] = values[header["name"]]
    return original


def test_reply_all_excludes_self_and_deduplicates_mailboxes_across_headers() -> None:
    message = build_reply_message(
        sender="casey@example.com",
        original_message=with_recipients(
            '"Lee, Jordan" <jordan@example.com>',
            '"Morgan, Casey" <CASEY@example.com>, Jordan <JORDAN@example.com>',
            'Casey <casey@example.com>, Jordan <jordan@example.com>, Jesse <jesse@example.com>',
        ),
        body_text="Following up.",
        reply_all=True,
    )

    assert str(message["To"]) == '"Lee, Jordan" <jordan@example.com>'
    assert str(message["Cc"]) == "Jesse <jesse@example.com>"


def test_follow_up_to_own_message_targets_original_recipients() -> None:
    original = with_recipients(
        "Casey Morgan <casey@example.com>",
        "Jordan <jordan@example.com>",
        "Casey <casey@example.com>, Jesse <jesse@example.com>",
    )
    for reply_all in (False, True):
        message = build_reply_message(
            sender="casey@example.com",
            original_message=original,
            body_text="Following up.",
            reply_all=reply_all,
        )
        assert str(message["To"]) == "Jordan <jordan@example.com>"
        assert message["Cc"] == ("Jesse <jesse@example.com>" if reply_all else None)


def test_direct_reply_to_incoming_message_only_targets_author() -> None:
    message = build_reply_message(
        sender="Casey Morgan <casey@example.com>",
        original_message=with_recipients(
            "Jordan <jordan@example.com>",
            "Casey <casey@example.com>, Jesse <jesse@example.com>",
        ),
        body_text="Thanks.",
    )
    assert str(message["To"]) == "Jordan <jordan@example.com>"
    assert message["Cc"] is None


def test_reply_preserves_long_paragraphs_without_hard_wrapping() -> None:
    paragraph = "A long paragraph should wrap visually in the email client. " * 8
    body = f"Hi Jordan,\n\n{paragraph.rstrip()}\n\nBest,\nCasey"
    message = build_reply_message(
        sender="casey@example.com",
        original_message=original_message(),
        body_text=body,
        include_quoted_history=False,
    )
    decoded = message_from_bytes(message.as_bytes(), policy=policy.default)
    assert decoded.get_body(preferencelist=("plain",)).get_content().rstrip("\n") == body
    assert_flowing_html(decoded, body)


def assert_flowing_html(message, body: str) -> None:
    html = message.get_body(preferencelist=("html",)).get_content()
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find("pre") is None
    assert soup.find("script") is None
    assert soup.find(attrs={"style": True}) is None
    for br in soup.find_all("br"):
        br.replace_with("\n")
    assert soup.div.get_text() == body.replace("\r\n", "\n").replace("\r", "\n")


def test_new_message_has_safe_flowing_html_and_plain_fallback_with_attachment() -> None:
    paragraph = 'Long prose with <script>not markup</script> & "quotes". ' * 10
    body = f"Hello,\r\n\r\n{paragraph.rstrip()}\r\n\r\nThanks,\r\nCasey"
    message = build_new_message(
        sender="casey@example.com",
        to="jordan@example.com",
        subject="Following up",
        body_text=body,
    )
    message.add_attachment(b"test pdf", maintype="application", subtype="pdf", filename="deck.pdf")
    decoded = message_from_bytes(message.as_bytes(), policy=policy.default)
    assert decoded.get_content_type() == "multipart/mixed"
    assert list(decoded.iter_parts())[0].get_content_type() == "multipart/alternative"
    plain = decoded.get_body(preferencelist=("plain",)).get_content()
    assert plain.rstrip("\n") == body.replace("\r\n", "\n")
    assert_flowing_html(decoded, body)
    assert next(decoded.iter_attachments()).get_payload(decode=True) == b"test pdf"


def test_reply_html_preserves_intentional_breaks_and_quoted_trail_as_text() -> None:
    message = build_reply_message(
        sender="casey@example.com",
        original_message=original_message(),
        body_text="First paragraph.\n\nSecond paragraph.\nThanks,\nCasey",
    )
    decoded = message_from_bytes(message.as_bytes(), policy=policy.default)
    body = decoded.get_body(preferencelist=("plain",)).get_content().rstrip("\n")
    assert "> Here are a few times that work." in body
    assert_flowing_html(decoded, body)
