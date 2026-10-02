"""Account-scoped body access based on verified sent-message recipients."""

from __future__ import annotations

import json
import os
from pathlib import Path

from email_cli.accounts import normalize_account_name
from email_cli.approved_senders import extract_sender_addresses
from email_cli.parsing import extract_headers


def previous_recipient_reads_enabled(account: str | None) -> bool:
    path = Path(
        os.environ.get(
            "EMAIL_CLI_READ_ACCESS_CONFIG", "~/.config/email-cli/read-access.json"
        )
    ).expanduser()
    if not path.exists():
        return False
    config = json.loads(path.read_text(encoding="utf-8"))
    accounts = config.get("previous_recipients", {}).get("gmail", [])
    if not isinstance(accounts, list) or not all(isinstance(item, str) for item in accounts):
        raise ValueError("previous_recipients.gmail must be a list of account names.")
    return normalize_account_name(account) in accounts


def single_sender(message: dict) -> str | None:
    headers = extract_headers(message.get("payload") or {})
    addresses = extract_sender_addresses(headers.get("From"))
    return addresses[0] if len(addresses) == 1 else None


class GmailPriorRecipients:
    """Use metadata only; cache evidence for this client invocation, not permanently."""

    def __init__(self, service, user_id: str = "me"):
        self.messages = service.users().messages()
        self.user_id = user_id
        self._evidence: dict[str, str | None] = {}

    def evidence_for(self, message: dict) -> str | None:
        address = single_sender(message)
        if address is None:
            return None
        if address not in self._evidence:
            self._evidence[address] = self._find_sent_message(address)
        return self._evidence[address]

    def _find_sent_message(self, address: str) -> str | None:
        # Search narrows candidates; only parsed headers establish a match.
        quoted = json.dumps(address)
        query = "{" + " ".join(f"{field}:{quoted}" for field in ("to", "cc", "bcc")) + "}"
        page_token = None
        seen_pages: set[str] = set()
        while True:
            params = {
                "userId": self.user_id,
                "labelIds": ["SENT"],
                "q": query,
                "maxResults": 100,
            }
            if page_token:
                params["pageToken"] = page_token
            page = self.messages.list(**params).execute()
            for candidate in page.get("messages", []):
                sent = self.messages.get(
                    userId=self.user_id,
                    id=candidate["id"],
                    format="metadata",
                    metadataHeaders=["To", "Cc", "Bcc"],
                ).execute()
                labels = sent.get("labelIds", [])
                if sent.get("id") != candidate["id"] or "SENT" not in labels or "DRAFT" in labels:
                    continue
                headers = extract_headers(sent.get("payload") or {})
                recipients = {
                    recipient
                    for field in ("To", "Cc", "Bcc")
                    for recipient in extract_sender_addresses(headers.get(field))
                }
                if address in recipients:
                    return sent["id"]
            page_token = page.get("nextPageToken")
            if not page_token:
                return None
            if page_token in seen_pages:
                raise RuntimeError("Repeated sent-history page; body access refused.")
            seen_pages.add(page_token)
