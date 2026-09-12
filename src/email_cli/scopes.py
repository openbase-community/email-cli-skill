"""OAuth scope definitions for Gmail access."""

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

DEFAULT_SCOPES = [GMAIL_READONLY_SCOPE]
COMPOSE_SCOPES = [GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE]
MODIFY_SCOPES = [GMAIL_READONLY_SCOPE, GMAIL_MODIFY_SCOPE]
SEND_SCOPES = [GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE, GMAIL_SEND_SCOPE]


def has_scope(granted_scopes: list[str] | tuple[str, ...] | None, required_scope: str) -> bool:
    """Return whether OAuth credentials include a required scope."""
    if not granted_scopes:
        return False
    return required_scope in set(granted_scopes)
