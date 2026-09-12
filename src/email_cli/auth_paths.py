"""Compatibility paths for Email CLI account configuration."""

from __future__ import annotations

from pathlib import Path

# Preserve the existing directory so tokens and account permissions remain valid.
APP_CONFIG_DIR = Path.home() / ".config" / "gmail-cli"
DEFAULT_CREDENTIALS_PATH = APP_CONFIG_DIR / "credentials.json"
DEFAULT_TOKEN_PATH = APP_CONFIG_DIR / "token.json"
