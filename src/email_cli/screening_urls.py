"""Expose actual URL hosts to Jev and reject structurally deceptive locators."""

from __future__ import annotations

import html
import ipaddress
import json
import re
from difflib import SequenceMatcher
from urllib.parse import unquote, urlsplit

# These are impersonation targets, NOT an allowlist; Jev still judges their content.
IMPERSONATION_TARGETS = (
    "github.com",
    "google.com",
    "apple.com",
    "microsoft.com",
    "amazon.com",
    "paypal.com",
    "wikipedia.org",
    "npmjs.com",
    "python.org",
    "openai.com",
)
URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>\"'\\]+", re.IGNORECASE)


def inspect_urls(state: dict) -> tuple[list[dict], list[str]]:
    text = html.unescape(json.dumps(state, ensure_ascii=False))
    urls = sorted(set(URL_PATTERN.findall(text)))
    references = []
    reasons = set()
    for raw in urls:
        raw = raw.rstrip(".,;!)]}")
        try:
            parsed = urlsplit(raw if "://" in raw else "https://" + raw)
            host = (parsed.hostname or "").lower().rstrip(".")
            references.append({"url": raw, "actual_hostname": host, "path": parsed.path})
            if not host or parsed.username is not None or parsed.password is not None:
                reasons.add("ambiguous_url_authority")
            if "%" in host or not host.isascii() or "xn--" in host:
                reasons.add("encoded_or_unicode_hostname")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                reasons.add("ip_address_destination")
            for target in IMPERSONATION_TARGETS:
                if host == target or host.endswith("." + target):
                    continue
                # Known brand followed by a different registrable suffix, or a close spelling.
                if target in host or SequenceMatcher(None, host, target).ratio() >= 0.88:
                    reasons.add("lookalike_hostname")
            query = unquote(parsed.query).lower()
            if "http://" in query or "https://" in query:
                reasons.add("embedded_redirect_destination")
        except ValueError:
            reasons.add("malformed_url")
    return references, sorted(reasons)
