"""Gmail API client wrapper used by the CLI."""

from __future__ import annotations

from typing import Any

from google.oauth2.credentials import Credentials

from email_cli.approved_senders import ApprovedSenders
from email_cli.drafts import build_new_message, build_reply_message, encode_message
from email_cli.parsing import (
    INTERESTING_HEADERS,
    extract_headers,
    normalize_message,
    normalize_thread,
)
from email_cli.read_screening import screened_result
from email_cli.safety import require_confirmation
from email_cli.scopes import GMAIL_COMPOSE_SCOPE, GMAIL_SEND_SCOPE
from email_cli.screening_content import gmail_state


class GmailClient:
    """Small wrapper around the google-api-python-client Gmail service."""

    def __init__(
        self,
        service: Any,
        credentials: Credentials | None = None,
        user_id: str = "me",
        approved_senders: ApprovedSenders | None = None,
        read_screener=None,
    ):
        self.service = service
        self.credentials = credentials
        self.user_id = user_id
        self.approved_senders = approved_senders
        self.read_screener = read_screener

    def search_messages(
        self,
        *,
        query: str,
        max_results: int = 10,
        page_token: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        params = _drop_none(
            {
                "userId": self.user_id,
                "q": query,
                "maxResults": max_results,
                "pageToken": page_token,
                "labelIds": label_ids,
            }
        )
        request = self.service.users().messages().list(**params)
        response = request.execute()
        return {
            "messages": [
                _strip_content_fields(message) for message in response.get("messages", [])
            ],
            "next_page_token": response.get("nextPageToken"),
            "result_size_estimate": response.get("resultSizeEstimate"),
        }

    def search_threads(
        self,
        *,
        query: str,
        max_results: int = 10,
        page_token: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        params = _drop_none(
            {
                "userId": self.user_id,
                "q": query,
                "maxResults": max_results,
                "pageToken": page_token,
                "labelIds": label_ids,
            }
        )
        request = self.service.users().threads().list(**params)
        response = request.execute()
        return {
            "threads": [_strip_content_fields(thread) for thread in response.get("threads", [])],
            "next_page_token": response.get("nextPageToken"),
            "result_size_estimate": response.get("resultSizeEstimate"),
        }

    def list_labels(self) -> dict[str, Any]:
        response = self.service.users().labels().list(userId=self.user_id).execute()
        labels = sorted(response.get("labels", []), key=lambda item: item.get("name", ""))
        return {"labels": labels}

    def get_message(
        self,
        *,
        message_id: str,
        include_body: bool = False,
        max_body_chars: int = 4000,
    ) -> dict[str, Any]:
        if self.approved_senders is None:
            response = self._get_message(message_id=message_id, message_format="full")
            return normalize_message(
                response,
                include_body=include_body,
                max_body_chars=max_body_chars,
            )

        metadata = self._get_message(message_id=message_id, message_format="metadata")
        return self._read_metadata(metadata, include_body, max_body_chars)

    def _read_metadata(self, metadata, include_body, max_body_chars):
        if include_body and self._message_sender_approved(metadata):
            response = self._get_message(message_id=metadata["id"], message_format="full")
            return normalize_message(
                response,
                include_body=True,
                max_body_chars=max_body_chars,
                approved_senders=self.approved_senders,
            )
        if include_body and self.read_screener:
            response = self._get_message(message_id=metadata["id"], message_format="full")
            if response.get("id") != metadata.get("id"):
                raise PermissionError("Message identity changed; body access refused.")
            decision = self.read_screener.evaluate(gmail_state(response), message_id=response["id"])
            result = normalize_message(
                response if decision.approved else metadata,
                include_body=decision.approved,
                max_body_chars=max_body_chars,
                approved_senders=None if decision.approved else self.approved_senders,
            )
            return screened_result(result, decision)
        return normalize_message(
            metadata,
            include_body=False,
            max_body_chars=max_body_chars,
            approved_senders=self.approved_senders,
        )

    def get_thread(
        self,
        *,
        thread_id: str,
        include_body: bool = True,
        max_body_chars: int = 4000,
    ) -> dict[str, Any]:
        if self.approved_senders is None:
            response = (
                self.service.users()
                .threads()
                .get(userId=self.user_id, id=thread_id, format="full")
                .execute()
            )
            return normalize_thread(
                response,
                include_body=include_body,
                max_body_chars=max_body_chars,
            )

        metadata = (
            self.service.users()
            .threads()
            .get(
                userId=self.user_id,
                id=thread_id,
                format="metadata",
                metadataHeaders=list(INTERESTING_HEADERS),
            )
            .execute()
        )
        messages = [
            self._read_metadata(message, include_body, max_body_chars)
            for message in metadata.get("messages") or []
        ]
        return {
            "id": metadata.get("id"),
            "history_id": metadata.get("historyId"),
            "message_count": len(messages),
            "messages": messages,
        }

    def create_draft_new(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        cc: str | None = None,
        bcc: str | None = None,
        confirm_create: bool = False,
    ) -> dict[str, Any]:
        require_confirmation(confirm_create, "Draft creation")
        self._require_scope(GMAIL_COMPOSE_SCOPE)
        profile = self.service.users().getProfile(userId=self.user_id).execute()
        message = build_new_message(
            sender=profile["emailAddress"],
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
        )
        response = (
            self.service.users()
            .drafts()
            .create(userId=self.user_id, body={"message": {"raw": encode_message(message)}})
            .execute()
        )
        return _compact_draft(response)

    def create_draft_reply(
        self,
        *,
        thread_id: str,
        body_text: str,
        reply_all: bool = False,
        include_quoted_history: bool = True,
        confirm_create: bool = False,
    ) -> dict[str, Any]:
        require_confirmation(confirm_create, "Draft reply creation")
        self._require_scope(GMAIL_COMPOSE_SCOPE)
        thread = (
            self.service.users()
            .threads()
            .get(
                userId=self.user_id,
                id=thread_id,
                format="metadata",
                metadataHeaders=list(INTERESTING_HEADERS),
            )
            .execute()
        )
        messages = thread.get("messages") or []
        if not messages:
            raise RuntimeError(f"Thread {thread_id} did not contain any messages.")
        original_message = messages[-1]
        if include_quoted_history:
            original_message = self._get_message(
                message_id=original_message["id"],
                message_format="full",
            )
        profile = self.service.users().getProfile(userId=self.user_id).execute()
        message = build_reply_message(
            sender=profile["emailAddress"],
            original_message=original_message,
            body_text=body_text,
            reply_all=reply_all,
            include_quoted_history=include_quoted_history,
        )
        response = (
            self.service.users()
            .drafts()
            .create(
                userId=self.user_id,
                body={"message": {"threadId": thread_id, "raw": encode_message(message)}},
            )
            .execute()
        )
        return _compact_draft(response)

    def send_draft(self, *, draft_id: str, confirm_send: bool = False) -> dict[str, Any]:
        require_confirmation(confirm_send, "Draft sending")
        self._require_scope(GMAIL_SEND_SCOPE)
        response = (
            self.service.users().drafts().send(userId=self.user_id, body={"id": draft_id}).execute()
        )
        return {
            "id": response.get("id"),
            "thread_id": response.get("threadId"),
            "label_ids": response.get("labelIds", []),
        }

    def _require_scope(self, scope: str) -> None:
        if self.credentials is None:
            return
        if hasattr(self.credentials, "has_scopes") and self.credentials.has_scopes([scope]):
            return
        granted = set(getattr(self.credentials, "scopes", None) or [])
        if scope in granted:
            return
        raise PermissionError(
            f"This operation requires OAuth scope {scope}. Re-run `gmail-cli auth login` "
            "with the matching scope option."
        )

    def _get_message(self, *, message_id: str, message_format: str) -> dict[str, Any]:
        params = {
            "userId": self.user_id,
            "id": message_id,
            "format": message_format,
        }
        if message_format == "metadata":
            params["metadataHeaders"] = list(INTERESTING_HEADERS)
        return self.service.users().messages().get(**params).execute()

    def _message_sender_approved(self, message: dict[str, Any]) -> bool:
        if self.approved_senders is None:
            return True
        headers = extract_headers(message.get("payload") or {})
        return self.approved_senders.is_sender_approved(headers.get("From"))


def _compact_draft(response: dict[str, Any]) -> dict[str, Any]:
    message = response.get("message") or {}
    return {
        "draft_id": response.get("id"),
        "message_id": message.get("id"),
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds", []),
    }


def _drop_none(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


def _strip_content_fields(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item for key, item in value.items() if key not in {"snippet", "body", "payload", "raw"}
    }
