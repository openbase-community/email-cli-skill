"""Invoke Mail's scripting interface without shell interpolation or credential extraction."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def call_mail(action: str, **payload) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("The Apple Mail provider requires macOS and a configured Mail account.")
    script = Path(__file__).with_name("apple_mail_bridge.js")
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", str(script)],
            input=json.dumps({"action": action, **payload}),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Apple Mail timed out. Check macOS Automation permission and Mail's connection. "
            "For writes, inspect Drafts/Sent before retrying; the result may be unknown."
        ) from exc
    if result.returncode:
        # Script errors contain no message bodies, arguments, or credentials.
        raise RuntimeError(f"Apple Mail: {result.stderr.strip()[:800]}")
    return json.loads(result.stdout)
