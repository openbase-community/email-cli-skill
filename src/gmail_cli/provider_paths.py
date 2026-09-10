"""Keep provider credentials and sender permissions in separate namespaces."""

from __future__ import annotations

import os
from pathlib import Path

from gmail_cli.auth_paths import APP_CONFIG_DIR


def provider_config_dir(provider: str) -> Path:
    if provider == "gmail":
        return APP_CONFIG_DIR
    if provider == "outlook":
        return Path(
            os.environ.get("OUTLOOK_CLI_CONFIG_DIR", APP_CONFIG_DIR / "outlook")
        ).expanduser()
    raise ValueError(f"Unknown mail provider: {provider}")
