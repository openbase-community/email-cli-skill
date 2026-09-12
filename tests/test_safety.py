from __future__ import annotations

import pytest

from email_cli.client import GmailClient
from email_cli.safety import ConfirmationRequiredError, require_confirmation


class ExplodingService:
    def users(self):  # noqa: ANN201
        raise AssertionError("Gmail service should not be called without confirmation")


def test_require_confirmation_blocks_false_value() -> None:
    with pytest.raises(ConfirmationRequiredError, match="CLI approval gate"):
        require_confirmation(False, "Dangerous action")


def test_create_draft_new_does_not_call_gmail_without_confirmation() -> None:
    client = GmailClient(service=ExplodingService())

    with pytest.raises(ConfirmationRequiredError):
        client.create_draft_new(
            to="recipient@example.com",
            subject="Hello",
            body_text="Draft body",
            confirm_create=False,
        )


def test_send_draft_does_not_call_gmail_without_confirmation() -> None:
    client = GmailClient(service=ExplodingService())

    with pytest.raises(ConfirmationRequiredError):
        client.send_draft(draft_id="draft-1", confirm_send=False)
