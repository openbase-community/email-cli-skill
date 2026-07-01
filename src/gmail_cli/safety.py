"""Small safety helpers for mutating Gmail operations."""

from __future__ import annotations


class ConfirmationRequiredError(RuntimeError):
    """Raised when a mutating tool was called without explicit confirmation."""


def require_confirmation(confirm: bool, action: str) -> None:
    if not confirm:
        raise ConfirmationRequiredError(
            f"{action} was not performed. Re-run through the CLI approval gate."
        )
