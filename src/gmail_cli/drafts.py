"""Helpers for building Gmail draft RFC 2822 messages."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from gmail_cli.parsing import extract_headers


def encode_message(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


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
    message.set_content(body_text)
    return message


def build_reply_message(
    *,
    sender: str,
    original_message: dict[str, Any],
    body_text: str,
    reply_all: bool = False,
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
    cc = _reply_cc(original_cc, sender, reply_all)
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    if message_id:
        message["In-Reply-To"] = message_id
        message["References"] = f"{references} {message_id}".strip() if references else message_id
    message.set_content(body_text)
    return message


def _reply_to(original_from: str, original_to: str, sender: str, reply_all: bool) -> str:
    if not reply_all:
        return original_from
    recipients = [original_from, original_to]
    return _dedupe_recipients(recipients, sender)


def _reply_cc(original_cc: str, sender: str, reply_all: bool) -> str:
    if not reply_all or not original_cc:
        return ""
    return _dedupe_recipients([original_cc], sender)


def _dedupe_recipients(values: list[str], sender: str) -> str:
    seen: set[str] = set()
    recipients: list[str] = []
    sender_lower = sender.lower()
    for value in values:
        for recipient in value.split(","):
            recipient = recipient.strip()
            if not recipient:
                continue
            key = recipient.lower()
            if key == sender_lower or key in seen:
                continue
            seen.add(key)
            recipients.append(recipient)
    return ", ".join(recipients)
