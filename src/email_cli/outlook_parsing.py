"""Normalize only selected Outlook metadata; never return body previews implicitly."""

from __future__ import annotations

from email.utils import formataddr

from email_cli.approved_senders import ApprovedSenders, normalize_email_address
from email_cli.parsing import html_to_text, truncate_text

METADATA_FIELDS = (
    "id",
    "conversationId",
    "subject",
    "from",
    "toRecipients",
    "ccRecipients",
    "bccRecipients",
    "replyTo",
    "receivedDateTime",
    "sentDateTime",
    "internetMessageId",
    "parentFolderId",
    "isRead",
    "isDraft",
    "hasAttachments",
)
METADATA_SELECT = ",".join(METADATA_FIELDS)


def sender_approved(message: dict, approved: ApprovedSenders) -> bool:
    # Match the address field alone; a display name cannot authorize a different sender.
    address = (message.get("from") or {}).get("emailAddress", {}).get("address")
    return normalize_email_address(address) in approved.senders


def address_header(recipients: list[dict]) -> str:
    return ", ".join(
        formataddr(
            (
                r.get("emailAddress", {}).get("name", ""),
                r.get("emailAddress", {}).get("address", ""),
            )
        )
        for r in recipients
    )


def body_text(message: dict) -> str:
    body = message.get("body") or {}
    content = body.get("content", "")
    return html_to_text(content) if body.get("contentType", "").lower() == "html" else content


def normalize_message(
    message: dict,
    approved: ApprovedSenders,
    *,
    include_body: bool = False,
    max_body_chars: int = 4000,
    message_approved: bool = False,
) -> dict:
    allowed = sender_approved(message, approved) or message_approved
    result = {
        "id": message.get("id"),
        "thread_id": message.get("conversationId"),
        "folder_id": message.get("parentFolderId"),
        "is_read": message.get("isRead"),
        "is_draft": message.get("isDraft"),
        "has_attachments": message.get("hasAttachments"),
        "headers": {
            "From": address_header([message.get("from") or {}]),
            "To": address_header(message.get("toRecipients") or []),
            "Cc": address_header(message.get("ccRecipients") or []),
            "Bcc": address_header(message.get("bccRecipients") or []),
            "Subject": message.get("subject", ""),
            "Date": message.get("sentDateTime") or message.get("receivedDateTime", ""),
            "Message-ID": message.get("internetMessageId", ""),
        },
        "sender_approved": allowed,
        "content_redacted": not allowed,
    }
    if include_body and allowed:
        text = body_text(message)
        result["body"] = {
            "text": truncate_text(text, max_body_chars),
            "truncated": len(text) > max_body_chars,
        }
    else:
        result["body_available"] = allowed
    if not allowed:
        result["redaction_reason"] = "sender_not_approved"
    return result
