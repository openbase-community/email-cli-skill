"""Preserve all text alternatives and hidden HTML destinations for screening."""

from __future__ import annotations

import base64
import binascii
from email import policy
from email.parser import BytesParser

from email_cli.parsing import extract_headers
from email_cli.screening_policy import MAX_STATE_CHARS


def gmail_state(message: dict) -> dict:
    parts = []
    attachments = []
    incomplete = False

    def walk(part):
        nonlocal incomplete
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        if part.get("filename") or body.get("attachmentId"):
            attachments.append({"mime_type": mime, "filename": part.get("filename", "")})
        data = body.get("data")
        if data and mime in {"text/plain", "text/html"}:
            if len(data) > MAX_STATE_CHARS * 2:
                incomplete = True
                return
            try:
                text = base64.b64decode(
                    data + "=" * (-len(data) % 4), altchars=b"-_", validate=True
                ).decode("utf-8", errors="strict")
                parts.append({"mime_type": mime, "content": text})
            except (ValueError, UnicodeError, binascii.Error):
                incomplete = True
        elif mime and not mime.startswith("multipart/") and mime not in {"text/plain", "text/html"}:
            attachments.append({"mime_type": mime})
        elif body.get("size", 0) and not data and not body.get("attachmentId"):
            incomplete = True
        for child in part.get("parts") or []:
            walk(child)

    walk(message.get("payload") or {})
    return {
        "headers": extract_headers(message.get("payload") or {}),
        "parts": parts,
        "attachments": attachments,
        "incomplete": incomplete,
    }


def outlook_state(message: dict) -> dict:
    body = message.get("body") or {}
    return {
        "subject": message.get("subject", ""),
        "parts": [{"mime_type": body.get("contentType"), "content": body.get("content", "")}],
        "attachments": ["present"] if message.get("hasAttachments") else [],
        "incomplete": "content" not in body
        or body.get("contentType", "").lower() not in {"html", "text"},
    }


def apple_mail_state(source: str) -> dict:
    if len(source) > MAX_STATE_CHARS * 2:
        return {"incomplete": True}
    message = BytesParser(policy=policy.default).parsebytes(source.encode("utf-8"))
    parts = []
    attachments = []
    incomplete = bool(message.defects)
    for part in message.walk():
        incomplete |= bool(part.defects)
        if part.is_multipart():
            continue
        if part.is_attachment() or part.get_filename() or part.get_content_maintype() != "text":
            attachments.append({"mime_type": part.get_content_type()})
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            incomplete = True
            continue
        try:
            text = part.get_content(errors="strict")
        except (LookupError, ValueError, UnicodeError):
            incomplete = True
            continue
        parts.append({"mime_type": part.get_content_type(), "content": text})
    return {
        "subject": str(message.get("Subject", "")),
        "parts": parts,
        "attachments": attachments,
        "incomplete": incomplete,
    }
