"""Approval gates for user-visible email side effects."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APPROVAL_STORE_ENV = "SUPER_AGENTS_APPROVAL_REQUESTS_FILE"
DEFAULT_APPROVAL_STORE = Path.home() / ".super-agents" / "approval-requests.json"
DASHBOARD_URL = "http://localhost:7999/dashboard/approvals"


@dataclass(frozen=True)
class ApprovalRequest:
    action: str
    prompt: str
    details: dict[str, Any]

    @property
    def id(self) -> str:
        payload = json.dumps(
            {"action": self.action, "details": self.details},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        # Retain existing IDs so pending approvals survive the package rename.
        return f"gmail-cli:{digest}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "approval_required",
            "approval": {
                "id": self.id,
                "action": self.action,
                "prompt": self.prompt,
                "details": self.details,
                "dashboard_url": DASHBOARD_URL,
                "rerun_after_approval": True,
                "integration": {
                    "kind": "openbase-coder-approval-dashboard",
                    "instruction": (
                        "Open the Openbase Coder approvals dashboard and ask the user to "
                        "accept or decline this request there. Rerun the same command "
                        "after the user accepts."
                    ),
                },
            },
        }

    def to_shared_request(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": "exec/requestApproval",
            "params": {
                "command": f"email-cli {self.action}",
                "description": self.prompt,
                "reason": self.prompt,
                "justification": self.prompt,
                "toolName": "email-cli",
                "action": self.action,
                "details": self.details,
                "dashboardUrl": DASHBOARD_URL,
            },
            "receivedAt": _iso_now(),
        }


class ApprovalRequiredError(RuntimeError):
    """Raised before a sensitive email action when user approval is missing."""

    def __init__(self, request: ApprovalRequest):
        super().__init__(request.prompt)
        self.request = request


def require_user_approval(
    approved_by_user: bool,
    *,
    action: str,
    prompt: str,
    details: dict[str, Any],
) -> None:
    if approved_by_user:
        return
    approval_request = ApprovalRequest(action=action, prompt=prompt, details=details)
    decision = pop_shared_approval_decision(approval_request.id)
    if decision == "accept":
        clear_shared_approval_request(approval_request.id)
        return
    if decision in {"decline", "cancel"}:
        clear_shared_approval_request(approval_request.id)
        raise ApprovalRequiredError(approval_request)
    record_shared_approval_request(approval_request)
    raise ApprovalRequiredError(approval_request)


def approval_store_path() -> Path:
    return Path(os.environ.get(APPROVAL_STORE_ENV) or DEFAULT_APPROVAL_STORE)


def record_shared_approval_request(approval_request: ApprovalRequest) -> None:
    store = read_approval_store()
    requests = _object(store.get("requests"))
    existing = _object(requests.get(approval_request.id))
    payload = approval_request.to_shared_request()
    if existing.get("receivedAt"):
        payload["receivedAt"] = existing["receivedAt"]
    requests[approval_request.id] = payload
    store["requests"] = requests
    store["decisions"] = _object(store.get("decisions"))
    write_approval_store(store)


def pop_shared_approval_decision(request_id: str) -> str | None:
    store = read_approval_store()
    decisions = _object(store.get("decisions"))
    raw = decisions.pop(request_id, None)
    if not isinstance(raw, dict):
        return None
    decision = raw.get("decision")
    if decision not in {"accept", "decline", "cancel"}:
        return None
    store["requests"] = _object(store.get("requests"))
    store["decisions"] = decisions
    write_approval_store(store)
    return decision


def clear_shared_approval_request(request_id: str) -> None:
    store = read_approval_store()
    requests = _object(store.get("requests"))
    decisions = _object(store.get("decisions"))
    requests.pop(request_id, None)
    decisions.pop(request_id, None)
    store["requests"] = requests
    store["decisions"] = decisions
    write_approval_store(store)


def read_approval_store() -> dict[str, Any]:
    path = approval_store_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"requests": {}, "decisions": {}}
    if not isinstance(raw, dict):
        return {"requests": {}, "decisions": {}}
    return {
        "requests": _object(raw.get("requests")),
        "decisions": _object(raw.get("decisions")),
    }


def write_approval_store(store: dict[str, Any]) -> None:
    path = approval_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "requests": _object(store.get("requests")),
            "decisions": _object(store.get("decisions")),
        },
        indent=2,
        sort_keys=True,
    )
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as tmp:
        tmp.write(payload + "\n")
        tmp_name = tmp.name
    os.replace(tmp_name, path)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
