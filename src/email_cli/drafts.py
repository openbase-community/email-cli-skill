"""Helpers for building Gmail draft RFC 2822 messages."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from html import escape
from typing import Any

from email_cli.parsing import choose_body_text, extract_headers, extract_payload_content


def encode_message(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _set_body(message: EmailMessage, body_text: str) -> None:
    """Keep a plain fallback and a flowing HTML body for Gmail's composer."""
    message.set_content(body_text)
    # Plain-only drafts can acquire visible hard wraps after editing/sending in
    # Gmail. HTML carries the intended breaks without fixing the display width.
    # Treat every input character as text, never as caller-supplied HTML.
    normalized = body_text.replace("\r\n", "\n").replace("\r", "\n")
    html = '<div dir="ltr">' + escape(normalized).replace("\n", "<br>") + "</div>"
    message.add_alternative(html, subtype="html")


def build_new_message(
    *,
    sender: str,
    to: str,
    subject: str,
    body_text: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    _set_body(message, body_text)
    return message


def build_reply_message(
    *,
    sender: str,
    original_message: dict[str, Any],
    body_text: str,
    reply_all: bool = False,
    include_quoted_history: bool = True,
) -> EmailMessage:
    payload = original_message.get("payload") or {}
    headers = extract_headers(payload)
    original_from = headers.get("From", "")
    original_to = headers.get("To", "")
    original_cc = headers.get("Cc", "")
    subject = headers.get("Subject", "")
    message_id = headers.get("Message-ID", "")
    references = headers.get("References", "")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = _reply_to(original_from, original_to, sender, reply_all)
    cc = _reply_cc(original_cc, sender, reply_all, exclude=str(message["To"]))
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    if message_id:
        message["In-Reply-To"] = message_id
        message["References"] = f"{references} {message_id}".strip() if references else message_id
    _set_body(
        message,
        build_reply_body(
            body_text=body_text,
            original_message=original_message,
            include_quoted_history=include_quoted_history,
        )
    )
    return message


def build_reply_body(
    *,
    body_text: str,
    original_message: dict[str, Any],
    include_quoted_history: bool = True,
) -> str:
    if not include_quoted_history:
        return body_text

    quoted = quote_message(original_message)
    if not quoted:
        return body_text
    return f"{body_text.rstrip()}\n\n{quoted}"


def quote_message(message: dict[str, Any]) -> str:
    payload = message.get("payload") or {}
    headers = extract_headers(payload)
    text_parts, _attachments = extract_payload_content(payload)
    body_text = choose_body_text(text_parts).strip()
    if not body_text:
        return ""

    date = headers.get("Date", "").strip()
    sender = headers.get("From", "").strip()
    return quote_text(body_text, date, sender)


def quote_text(body_text: str, date: str, sender: str) -> str:
    """Render a visible plain-text email trail for either provider."""
    if not body_text.strip():
        return ""
    attribution_parts = [part for part in [date, sender] if part]
    attribution = " ".join(attribution_parts) if attribution_parts else "the previous message"
    quoted_lines = "\n".join(f"> {line}" if line else ">" for line in body_text.splitlines())
    return f"On {attribution} wrote:\n\n{quoted_lines}"


def _reply_to(original_from: str, original_to: str, sender: str, reply_all: bool) -> str:
    # A follow-up to our own sent message should go to its original recipients.
    author = _dedupe_recipients([original_from], sender)
    recipients = [author, original_to] if reply_all or not author else [author]
    return _dedupe_recipients(recipients, sender)


def _reply_cc(original_cc: str, sender: str, reply_all: bool, *, exclude: str = "") -> str:
    if not reply_all or not original_cc:
        return ""
    return _dedupe_recipients([original_cc], sender, exclude=exclude)


def _dedupe_recipients(values: list[str], sender: str, *, exclude: str = "") -> str:
    seen = {address.casefold() for _, address in getaddresses([sender, exclude]) if address}
    recipients: list[str] = []
    for name, address in getaddresses(values):
        key = address.casefold()
        if not address or key in seen:
            continue
        seen.add(key)
        recipients.append(formataddr((name, address)))
    return ", ".join(recipients)
