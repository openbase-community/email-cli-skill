"""Local, account-scoped Apple Mail metadata search and approved body reads."""

from __future__ import annotations

import base64
import hashlib
import json
import shlex

from email_cli.apple_mail_drafts import AppleMailDrafts
from email_cli.apple_mail_transport import call_mail
from email_cli.approved_senders import ApprovedSenders, extract_sender_addresses


def encode_id(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, sort_keys=True).encode()).decode()


def decode_id(value: str) -> dict:
    if not isinstance(value, str) or len(value) > 16000:
        raise ValueError("Invalid Apple Mail identifier.")
    data = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
    if not isinstance(data, dict):
        raise ValueError("Invalid Apple Mail identifier.")
    return data


def search_terms(query: str) -> list[dict]:
    terms = []
    for term in shlex.split(query):
        field, sep, value = term.partition(":")
        if sep and field not in {"from", "subject"}:
            raise ValueError("Apple Mail supports only from:, subject:, and plain metadata text.")
        terms.append({"field": field if sep else "text", "value": (value if sep else term).lower()})
    return terms


class AppleMailClient(AppleMailDrafts):
    def __init__(
        self,
        account: dict,
        approved_senders: ApprovedSenders,
        *,
        account_name: str | None = None,
        transport=None,
    ):
        self.account = account
        self.account_name = account_name
        self.approved_senders = approved_senders
        self.transport = transport or call_mail

    def _call(self, action: str, **payload) -> dict:
        return self.transport(
            action, account_id=self.account["account_id"], email=self.account["email"], **payload
        )

    def _id(self, kind: str, **values) -> str:
        return encode_id({"kind": kind, "account_id": self.account["account_id"], **values})

    def _decode(self, value: str, kind: str) -> dict:
        data = decode_id(value)
        if data.get("kind") != kind or data.get("account_id") != self.account["account_id"]:
            raise ValueError("Identifier belongs to a different account or operation.")
        if kind in {"message", "folder"}:
            path = data.get("folder")
            if not isinstance(path, list) or not path or not all(isinstance(x, str) for x in path):
                raise ValueError("Invalid mailbox identifier.")
        if kind == "message" and (
            type(data.get("local_id")) is not int
            or not isinstance(data.get("internet_message_id"), str)
        ):
            raise ValueError("Invalid message identifier.")
        return data

    def _message_args(self, message_id: str) -> dict:
        data = self._decode(message_id, "message")
        return {k: data[k] for k in ("folder", "local_id", "internet_message_id")}

    def _approved(self, message: dict) -> bool:
        addresses = extract_sender_addresses(message.get("from"))
        return len(addresses) == 1 and addresses[0] in self.approved_senders.senders

    def _normalize(self, message: dict, folder: list[str]) -> dict:
        return {
            **message,
            "id": self._id(
                "message",
                folder=folder,
                local_id=message["local_id"],
                internet_message_id=message["internet_message_id"],
            ),
            "body_access_allowed": self._approved(message),
        }

    def list_labels(self) -> dict:
        response = self._call("folders")
        return {
            "folders": [
                {**f, "id": self._id("folder", folder=f["path"])} for f in response["folders"]
            ],
            "source": "apple_mail_local_sync",
        }

    def search_messages(
        self,
        *,
        query: str,
        max_results: int = 10,
        page_token: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        if label_ids and len(label_ids) != 1:
            raise ValueError("Apple Mail searches one folder at a time.")
        folder = self._decode(label_ids[0], "folder")["folder"] if label_ids else ["Inbox"]
        limit = min(max(max_results, 1), 100)
        terms = search_terms(query)
        binding = hashlib.sha256(json.dumps([folder, terms, limit]).encode()).hexdigest()
        offset = 0
        if page_token:
            page = self._decode(page_token, "page")
            offset = page.get("offset")
            if page.get("binding") != binding or type(offset) is not int or offset < 0:
                raise ValueError("Page token does not match the query, folder, or limit.")
        response = self._call("search", folder=folder, terms=terms, limit=limit, offset=offset)
        next_offset = response["next_offset"]
        return {
            "messages": [self._normalize(m, folder) for m in response["messages"]],
            "next_page_token": self._id("page", offset=next_offset, binding=binding)
            if next_offset is not None
            else None,
            "scanned": response["scanned"],
            "mailbox_message_count": response["mailbox_message_count"],
            "source": "apple_mail_local_sync",
        }

    def get_message(
        self, *, message_id: str, include_body: bool = False, max_body_chars: int = 4000
    ) -> dict:
        args = self._message_args(message_id)
        metadata = self._call("message", **args)
        result = self._normalize(metadata, args["folder"])
        if include_body:
            if self._approved(metadata):
                limit = min(max(max_body_chars, 0), 50000)
                body = self._call(
                    "body", **args, expected_sender=metadata["from"], max_chars=limit + 1
                )
                result["body"] = body["body"][:limit]
                result["body_truncated"] = len(body["body"]) > limit
            else:
                result["body_omitted_reason"] = "sender_not_approved"
        return result

    def search_threads(self, **kwargs) -> dict:
        raise ValueError(
            "Mail does not expose stable conversation IDs. Use search without --threads."
        )

    def get_thread(self, **kwargs) -> dict:
        raise ValueError(
            "Mail does not expose stable conversation IDs. Use message with a message ID."
        )
