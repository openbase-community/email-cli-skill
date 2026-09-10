"""Native Graph drafts and replies with explicit approval and scope checks."""

from __future__ import annotations

from email.utils import getaddresses

from gmail_cli.approved_senders import normalize_email_address
from gmail_cli.drafts import quote_text
from gmail_cli.graph import item_path
from gmail_cli.outlook_auth import COMPOSE_SCOPE, SEND_SCOPE
from gmail_cli.outlook_parsing import address_header
from gmail_cli.outlook_parsing import body_text as extract_body_text
from gmail_cli.safety import require_confirmation


def recipients(value: str | None) -> list[dict]:
    if not value:
        return []
    result = []
    for name, address in getaddresses([value]):
        if not normalize_email_address(address):
            raise ValueError("Invalid recipient email address.")
        result.append({"emailAddress": {"name": name, "address": address}})
    if not result:
        raise ValueError("At least one valid recipient is required.")
    return result


def compact_draft(response: dict) -> dict:
    return {
        "draft_id": response["id"],
        "message_id": response["id"],
        "thread_id": response.get("conversationId"),
    }


class OutlookDrafts:
    """Draft operations for OutlookClient; metadata and sender gates live on the client."""

    def create_draft_new(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        cc: str | None = None,
        bcc: str | None = None,
        confirm_create: bool = False,
    ) -> dict:
        require_confirmation(confirm_create, "Outlook draft creation")
        self.credentials.require_scope(COMPOSE_SCOPE)
        to_recipients = recipients(to)
        if not to_recipients:
            raise ValueError("A draft recipient is required.")
        response = self.graph.request(
            "POST",
            "/me/messages",
            json={
                "subject": subject,
                "body": {"contentType": "Text", "content": body_text},
                "toRecipients": to_recipients,
                "ccRecipients": recipients(cc),
                "bccRecipients": recipients(bcc),
            },
        )
        return compact_draft(response)

    def create_draft_reply(
        self,
        *,
        thread_id: str,
        body_text: str,
        reply_all: bool = False,
        include_quoted_history: bool = True,
        confirm_create: bool = False,
    ) -> dict:
        require_confirmation(confirm_create, "Outlook reply draft creation")
        self.credentials.require_scope(COMPOSE_SCOPE)
        messages = [m for m in self._thread_metadata(thread_id) if not m.get("isDraft")]
        if not messages:
            raise ValueError("Conversation contains no non-draft messages to reply to.")
        original = messages[-1]
        content = body_text
        if include_quoted_history:
            original = self._with_body(original)
            quoted = quote_text(
                extract_body_text(original),
                original.get("sentDateTime") or original.get("receivedDateTime", ""),
                address_header([original.get("from") or {}]),
            )
            if quoted:
                content = f"{content.rstrip()}\n\n{quoted}"
        action = "createReplyAll" if reply_all else "createReply"
        response = self.graph.request(
            "POST",
            item_path("messages", original["id"]) + f"/{action}",
            json={"message": {"body": {"contentType": "Text", "content": content}}},
        )
        if response.get("conversationId") != thread_id:
            raise RuntimeError(
                f"Reply draft {response.get('id')!r} was created but its conversation differs. "
                "Inspect the draft in Outlook before continuing; do not retry automatically."
            )
        return {**compact_draft(response), "quoted_history_included": include_quoted_history}

    def send_draft(self, *, draft_id: str, confirm_send: bool = False) -> dict:
        require_confirmation(confirm_send, "Outlook draft sending")
        self.credentials.require_scope(SEND_SCOPE)
        message = self._metadata(draft_id)
        if not message.get("isDraft"):
            raise ValueError("The supplied Outlook message is not a draft.")
        self.graph.request("POST", item_path("messages", draft_id) + "/send")
        # Graph returns 202 without a sent-message ID; acceptance is not delivery confirmation.
        return {
            "draft_id": draft_id,
            "thread_id": message.get("conversationId"),
            "send_status": "accepted",
        }
