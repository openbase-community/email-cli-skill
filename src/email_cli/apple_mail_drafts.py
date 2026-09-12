"""Approval-gated native Mail drafts; never automatically retry ambiguous writes."""

from __future__ import annotations

import hashlib
import json
import uuid
from email.utils import getaddresses

from email_cli.apple_mail_auth import config_path
from email_cli.approved_senders import normalize_email_address
from email_cli.drafts import quote_text
from email_cli.provider_paths import save_private
from email_cli.safety import require_confirmation


def recipients(value: str | None) -> list[str]:
    result = [address for _, address in getaddresses([value])] if value else []
    if value and (not result or any(not normalize_email_address(a) for a in result)):
        raise ValueError("Invalid recipient email address.")
    return result


def fingerprint(draft: dict) -> str:
    return hashlib.sha256(json.dumps(draft, sort_keys=True).encode()).hexdigest()


class AppleMailDrafts:
    def _require_write(self, capability: str, confirmed: bool) -> None:
        require_confirmation(confirmed, f"Apple Mail {capability}")
        if not self.account.get(capability):
            raise PermissionError(
                f"Run apple-mail-cli auth login with --include-{capability} first."
            )

    def _save_draft(self, response: dict, **extra) -> dict:
        if (
            normalize_email_address(response["sender"].split("<")[-1].rstrip(">"))
            != self.account["email"]
        ):
            raise RuntimeError(
                "Draft was created with an unexpected sender; inspect Mail before retrying."
            )
        identifier = str(uuid.uuid4())
        save_private(
            config_path(self.account_name).parent / "drafts" / f"{identifier}.json",
            {
                "account_id": self.account["account_id"],
                "local_id": response["local_id"],
                "fingerprint": fingerprint(response),
                "state": "ready",
            },
        )
        return {"draft_id": identifier, "provider": "apple-mail", **extra}

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
        self._require_write("compose", confirm_create)
        to_values = recipients(to)
        if not to_values:
            raise ValueError("A recipient is required.")
        response = self._call(
            "draft-new",
            to=to_values,
            cc=recipients(cc),
            bcc=recipients(bcc),
            subject=subject,
            body=body_text,
        )
        return self._save_draft(response)

    def create_draft_reply(
        self,
        *,
        thread_id: str,
        body_text: str,
        reply_all: bool = False,
        include_quoted_history: bool = True,
        confirm_create: bool = False,
    ) -> dict:
        self._require_write("compose", confirm_create)
        # The shared command accepts an original message ID on this provider.
        args = self._message_args(thread_id)
        original = self.get_message(
            message_id=thread_id, include_body=include_quoted_history, max_body_chars=50000
        )
        if not self._approved(original):
            raise PermissionError("Native Mail reply creation requires an approved sender.")
        if original.get("body_truncated"):
            raise ValueError("Original exceeds quote limit; explicitly use --no-quoted-history.")
        content = body_text
        if include_quoted_history:
            quoted = quote_text(original["body"], original["received"], original["from"])
            content = f"{content.rstrip()}\n\n{quoted}"
        response = self._call(
            "draft-reply",
            **args,
            expected_sender=original["from"],
            reply_all=reply_all,
            body=content,
        )
        return self._save_draft(
            response, reply_to_message_id=thread_id, quoted_history_included=include_quoted_history
        )

    def send_draft(self, *, draft_id: str, confirm_send: bool = False) -> dict:
        self._require_write("send", confirm_send)
        identifier = str(uuid.UUID(draft_id))
        path = config_path(self.account_name).parent / "drafts" / f"{identifier}.json"
        # Hold an exclusive lock through validation, state transition, and sending.
        import fcntl

        with path.open("r+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            manifest = json.load(f)
            if manifest["account_id"] != self.account["account_id"] or manifest["state"] != "ready":
                raise ValueError(
                    "Draft belongs to another account or was already attempted; inspect Mail."
                )
            draft = self._call("draft", local_id=manifest["local_id"])
            if fingerprint(draft) != manifest["fingerprint"]:
                raise ValueError("Draft changed since creation; inspect Mail and send it manually.")
            # Persist before sending: interruption must not cause a duplicate send on retry.
            manifest["state"] = "send_attempted"
            f.seek(0)
            json.dump(manifest, f)
            f.truncate()
            f.flush()
            import os

            os.fsync(f.fileno())
            result = self._call("send", local_id=manifest["local_id"], expected_draft=draft)
            if not result["accepted"]:
                raise RuntimeError(
                    "Mail did not confirm send acceptance; inspect Outbox/Sent before retrying."
                )
        return {"draft_id": identifier, "send_status": "accepted"}
