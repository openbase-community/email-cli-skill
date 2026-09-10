"""Keep provider credentials and sender permissions in separate namespaces."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from gmail_cli.auth_paths import APP_CONFIG_DIR

PROVIDER_NAMES = {"gmail": "Gmail", "outlook": "Outlook", "apple-mail": "Apple Mail"}


def provider_config_dir(provider: str) -> Path:
    if provider == "gmail":
        return APP_CONFIG_DIR
    if provider == "outlook":
        return Path(
            os.environ.get("OUTLOOK_CLI_CONFIG_DIR", APP_CONFIG_DIR / "outlook")
        ).expanduser()
    if provider == "apple-mail":
        return Path(
            os.environ.get("APPLE_MAIL_CLI_CONFIG_DIR", APP_CONFIG_DIR / "apple-mail")
        ).expanduser()
    raise ValueError(f"Unknown mail provider: {provider}")


def save_private(path: Path, data: dict) -> None:
    """Atomically replace JSON with owner-only permissions from creation."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
