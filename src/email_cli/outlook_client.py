"""Outlook mailbox operations through delegated Microsoft Graph permissions."""

from __future__ import annotations

import json

from email_cli.approved_senders import ApprovedSenders
from email_cli.graph import GraphTransport, item_path
from email_cli.outlook_drafts import OutlookDrafts
from email_cli.outlook_parsing import METADATA_SELECT, normalize_message, sender_approved


class OutlookClient(OutlookDrafts):
    def __init__(self, credentials, approved_senders: ApprovedSenders, transport=None):
        self.credentials = credentials
        self.approved_senders = approved_senders
        self.graph = transport or GraphTransport(credentials)

    def search_messages(
        self,
        *,
        query: str,
        max_results: int = 10,
        page_token: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        if label_ids and len(label_ids) != 1:
            raise ValueError("Outlook supports one --folder-id per search.")
        path = item_path("mailFolders", label_ids[0]) + "/messages" if label_ids else "/me/messages"
        params = {"$select": METADATA_SELECT, "$top": min(max(max_results, 1), 100)}
        if query:
            params["$search"] = json.dumps(query)
        response = self.graph.page(path, params, page_token)
        return {
            "messages": [
                normalize_message(m, self.approved_senders) for m in response.get("value", [])
            ],
            "next_page_token": response.get("@odata.nextLink"),
        }

    def search_threads(self, **kwargs) -> dict:
        response = self.search_messages(**kwargs)
        threads = {}
        for message in response["messages"]:
            thread_id = message["thread_id"]
            if thread_id:
                threads.setdefault(thread_id, {"id": thread_id})
        return {"threads": list(threads.values()), "next_page_token": response["next_page_token"]}

    def list_labels(self) -> dict:
        """The labels compatibility command returns Outlook folders, including child folders."""
        folders = []
        pending = ["/me/mailFolders"]
        seen = set()
        params = {"$select": "id,displayName,parentFolderId,childFolderCount", "$top": 100}
        while pending:
            path = pending.pop()
            for folder in self.graph.all_pages(path, params):
                if folder["id"] in seen:
                    continue
                seen.add(folder["id"])
                folders.append(
                    {
                        "id": folder["id"],
                        "name": folder.get("displayName"),
                        "parent_id": folder.get("parentFolderId"),
                    }
                )
                if folder.get("childFolderCount", 0):
                    pending.append(item_path("mailFolders", folder["id"]) + "/childFolders")
        return {"folders": sorted(folders, key=lambda f: f["name"] or "")}

    def _metadata(self, message_id: str) -> dict:
        return self.graph.request(
            "GET", item_path("messages", message_id), params={"$select": METADATA_SELECT}
        )

    def _with_body(self, metadata: dict) -> dict:
        if not sender_approved(metadata, self.approved_senders):
            raise PermissionError("Message body access requires an approved Outlook sender.")
        message = self.graph.request(
            "GET",
            item_path("messages", metadata["id"]),
            params={"$select": METADATA_SELECT + ",body"},
        )
        if not sender_approved(message, self.approved_senders):
            raise PermissionError("Message sender changed; body access refused.")
        return message

    def get_message(
        self, *, message_id: str, include_body: bool = False, max_body_chars: int = 4000
    ) -> dict:
        message = self._metadata(message_id)
        if include_body and sender_approved(message, self.approved_senders):
            message = self._with_body(message)
        return normalize_message(
            message, self.approved_senders, include_body=include_body, max_body_chars=max_body_chars
        )

    def _thread_metadata(self, thread_id: str) -> list[dict]:
        if not thread_id:
            raise ValueError("A conversation ID is required.")
        escaped = thread_id.replace("'", "''")
        messages = self.graph.all_pages(
            "/me/messages",
            {
                "$select": METADATA_SELECT,
                "$filter": f"conversationId eq '{escaped}'",
                "$top": 100,
            },
        )
        if any(m.get("conversationId") != thread_id for m in messages):
            raise RuntimeError("Microsoft returned messages outside the requested conversation.")
        return sorted(
            messages, key=lambda m: m.get("sentDateTime") or m.get("receivedDateTime", "")
        )

    def get_thread(
        self, *, thread_id: str, include_body: bool = True, max_body_chars: int = 4000
    ) -> dict:
        messages = []
        for metadata in self._thread_metadata(thread_id):
            message = metadata
            if include_body and sender_approved(metadata, self.approved_senders):
                message = self._with_body(metadata)
            messages.append(
                normalize_message(
                    message,
                    self.approved_senders,
                    include_body=include_body,
                    max_body_chars=max_body_chars,
                )
            )
        return {"id": thread_id, "message_count": len(messages), "messages": messages}
