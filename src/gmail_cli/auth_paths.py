"""Shared filesystem paths for Gmail CLI configuration."""

from __future__ import annotations

from pathlib import Path

APP_CONFIG_DIR = Path.home() / ".config" / "gmail-cli"
DEFAULT_CREDENTIALS_PATH = APP_CONFIG_DIR / "credentials.json"
DEFAULT_TOKEN_PATH = APP_CONFIG_DIR / "token.json"
