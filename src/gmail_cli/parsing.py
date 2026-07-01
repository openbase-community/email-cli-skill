"""Normalize Gmail API message payloads into compact JSON-safe dictionaries."""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup

INTERESTING_HEADERS = (
    "From",
    "To",
    "Cc",
    "Bcc",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "References",
)


@dataclass
class BodyPart:
    mime_type: str
    text: str


def normalize_message(
    message: dict[str, Any],
    *,
    include_body: bool = True,
    max_body_chars: int = 4000,
    approved_senders: Any | None = None,
) -> dict[str, Any]:
    """Return a compact, normalized representation of a Gmail Message resource."""
    payload = message.get("payload") or {}
    headers = extract_headers(payload)
    sender_approved = (
        True
        if approved_senders is None
        else approved_senders.is_sender_approved(headers.get("From"))
    )
    content_redacted = approved_senders is not None and not sender_approved
    text_parts: list[BodyPart] = []
    attachments: list[dict[str, Any]] = []
    body_text = ""
    if not content_redacted:
        text_parts, attachments = extract_payload_content(payload)
        body_text = choose_body_text(text_parts)
    body = (
        truncate_text(body_text, max_body_chars) if include_body and not content_redacted else None
    )

    normalized: dict[str, Any] = {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds", []),
        "snippet": None if content_redacted else message.get("snippet"),
        "history_id": message.get("historyId"),
        "internal_date": normalize_internal_date(message.get("internalDate")),
        "headers": headers,
        "attachments": attachments,
        "sender_approved": sender_approved,
        "content_redacted": content_redacted,
    }
    if content_redacted:
        normalized["body_available"] = False
        normalized["redaction_reason"] = "sender_not_approved"
    elif include_body:
        normalized["body"] = {
            "text": body,
            "truncated": len(body_text) > max_body_chars,
            "mime_preference": "text/plain" if has_plain_text(text_parts) else "text/html",
        }
    else:
        normalized["body_available"] = bool(body_text)
    return normalized


def normalize_thread(
    thread: dict[str, Any],
    *,
    include_body: bool = True,
    max_body_chars: int = 4000,
    approved_senders: Any | None = None,
) -> dict[str, Any]:
    messages = [
        normalize_message(
            message,
            include_body=include_body,
            max_body_chars=max_body_chars,
            approved_senders=approved_senders,
        )
        for message in thread.get("messages", [])
    ]
    return {
        "id": thread.get("id"),
        "history_id": thread.get("historyId"),
        "message_count": len(messages),
        "messages": messages,
    }


def extract_headers(payload: dict[str, Any]) -> dict[str, str]:
    raw_headers = payload.get("headers") or []
    headers_by_lower = {
        item.get("name", "").lower(): item.get("value", "")
        for item in raw_headers
        if item.get("name")
    }
    return {
        header: headers_by_lower[header.lower()]
        for header in INTERESTING_HEADERS
        if header.lower() in headers_by_lower
    }


def extract_payload_content(payload: dict[str, Any]) -> tuple[list[BodyPart], list[dict[str, Any]]]:
    text_parts: list[BodyPart] = []
    attachments: list[dict[str, Any]] = []
    walk_payload(payload, text_parts, attachments)
    return text_parts, attachments


def walk_payload(
    part: dict[str, Any],
    text_parts: list[BodyPart],
    attachments: list[dict[str, Any]],
) -> None:
    mime_type = part.get("mimeType", "")
    filename = part.get("filename") or ""
    body = part.get("body") or {}
    data = body.get("data")
    attachment_id = body.get("attachmentId")

    if attachment_id or filename:
        attachments.append(
            {
                "filename": filename,
                "mime_type": mime_type,
                "attachment_id": attachment_id,
                "size": body.get("size"),
                "part_id": part.get("partId"),
            }
        )

    if data and mime_type in {"text/plain", "text/html"} and not attachment_id:
        decoded = decode_base64url(data)
        if mime_type == "text/html":
            decoded = html_to_text(decoded)
        text_parts.append(BodyPart(mime_type=mime_type, text=decoded))

    for child in part.get("parts") or []:
        walk_payload(child, text_parts, attachments)


def decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def html_to_text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    return normalize_whitespace(html.unescape(text))


def normalize_whitespace(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    compact_lines: list[str] = []
    last_blank = False
    for line in lines:
        blank = not line
        if blank and last_blank:
            continue
        compact_lines.append(line)
        last_blank = blank
    return "\n".join(compact_lines).strip()


def choose_body_text(parts: list[BodyPart]) -> str:
    plain = [part.text for part in parts if part.mime_type == "text/plain" and part.text.strip()]
    if plain:
        return normalize_whitespace("\n\n".join(plain))
    html_parts = [
        part.text for part in parts if part.mime_type == "text/html" and part.text.strip()
    ]
    return normalize_whitespace("\n\n".join(html_parts))


def has_plain_text(parts: list[BodyPart]) -> bool:
    return any(part.mime_type == "text/plain" and part.text.strip() for part in parts)


def truncate_text(value: str, max_chars: int) -> str:
    if max_chars < 0:
        raise ValueError("max_body_chars must be non-negative")
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip()


def normalize_internal_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def parsed_email_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
