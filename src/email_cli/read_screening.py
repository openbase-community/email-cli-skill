"""Opt-in per-message screening. No sender grants or dashboard decisions are written."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from email_cli.accounts import normalize_account_name
from email_cli.provider_paths import save_private
from email_cli.screening_policy import (
    MAX_RISK,
    MAX_STATE_CHARS,
    MODEL,
    POLICY_VERSION,
    QUESTIONS,
)
from email_cli.screening_urls import inspect_urls

CONFIG_PATH = Path.home() / ".config/email-cli/read-screening.json"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"


@dataclass
class ScreeningDecision:
    approved: bool
    reasons: list[str]
    probabilities: dict[str, float] = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    model: str = MODEL

    def as_dict(self) -> dict:
        return {
            "decision": "auto_approved" if self.approved else "flagged",
            "reasons": self.reasons,
            "probabilities": self.probabilities,
            "model": self.model,
            "policy_version": POLICY_VERSION,
            "usage": self.usage,
        }


class ReadScreener:
    def __init__(self, key: str, *, audit_path: Path | None = None, transport=None):
        self._key = key
        self.audit_path = audit_path
        self.transport = transport or requests.Session()

    def evaluate(self, state: dict, *, message_id: str = "") -> ScreeningDecision:
        references, url_reasons = inspect_urls(state)
        state = {**state, "parsed_url_destinations": references}
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True)
        if state.get("incomplete") or len(encoded) > MAX_STATE_CHARS:
            result = ScreeningDecision(False, ["incomplete_or_oversized_message"])
        elif state.get("attachments"):
            result = ScreeningDecision(False, ["uninspected_attachment"])
        elif url_reasons:
            result = ScreeningDecision(False, url_reasons)
        elif not self._key:
            result = ScreeningDecision(False, ["missing_typesafe_key"])
        else:
            result = self._evaluate(state)
        if self.audit_path:
            # One atomic record per exact content and message; no private body or credentials.
            digest = hashlib.sha256((message_id + "\n" + encoded).encode()).hexdigest()
            record = {"message_id": message_id, "content_sha256": digest, **result.as_dict()}
            save_private(self.audit_path / f"{digest}.json", record)
        return result

    def _evaluate(self, state: dict) -> ScreeningDecision:
        try:
            response = self.transport.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": MODEL, "state": state, "questions": QUESTIONS},
                timeout=(5, 30),
                allow_redirects=False,
            )
            if response.status_code != 200:
                return ScreeningDecision(False, [f"jev_http_{response.status_code}"])
            payload = response.json()
            if payload.get("model") != MODEL:
                return ScreeningDecision(False, ["unexpected_model_version"])
            answers = payload["answers"]
            probabilities = {}
            for name in QUESTIONS:
                answer = answers[name]
                value = answer["noul"]
                if (
                    answer.get("type") != "noul"
                    or type(value) not in (int, float)
                    or not math.isfinite(value)
                    or not 0 <= value <= 1
                ):
                    return ScreeningDecision(False, ["invalid_jev_response"])
                probabilities[name] = value
            reasons = [name for name, risk in probabilities.items() if risk > MAX_RISK]
            return ScreeningDecision(
                not reasons,
                reasons or ["all_risks_below_threshold"],
                probabilities,
                payload.get("usage", {}),
                payload["model"],
            )
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
            # The fallback is intentional: keep the body withheld and require manual review.
            return ScreeningDecision(False, ["jev_unavailable_or_invalid_response"])


def configured_screener(account: str | None, provider: str) -> ReadScreener | None:
    path = Path(os.environ.get("EMAIL_CLI_SCREENING_CONFIG", CONFIG_PATH)).expanduser()
    if not path.exists():
        return None
    config = json.loads(path.read_text())
    name = normalize_account_name(account)
    if name not in config.get("enabled_accounts", {}).get(provider, []):
        return None
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key and config.get("api_key_file"):
        key_path = Path(config["api_key_file"]).expanduser()
        if key_path.exists():
            key = key_path.read_text().strip()
    audit = path.parent / "screening-audit" / provider / name
    return ReadScreener(key, audit_path=audit)


def screened_result(result: dict[str, Any], decision: ScreeningDecision) -> dict[str, Any]:
    """Describe a per-message grant without falsely claiming sender approval."""
    result["read_screening"] = decision.as_dict()
    result["sender_approved"] = False
    if not decision.approved:
        result["redaction_reason"] = "message_flagged_for_review"
    return result
