"""Keep ordinary unit tests isolated from a user's paid screening configuration."""

import pytest


@pytest.fixture(autouse=True)
def isolate_live_screening(monkeypatch, tmp_path):
    monkeypatch.setenv("EMAIL_CLI_SCREENING_CONFIG", str(tmp_path / "disabled-screening.json"))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
