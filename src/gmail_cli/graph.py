"""Small Microsoft Graph transport with constrained pagination and no mutation retries."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import requests

from gmail_cli.outlook_auth import OutlookCredentials

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


def item_path(collection: str, item_id: str) -> str:
    if not item_id or item_id in {".", ".."}:
        raise ValueError("A non-empty resource ID is required.")
    return f"/me/{collection}/{quote(item_id, safe='')}"


class GraphTransport:
    def __init__(self, credentials: OutlookCredentials, session=None):
        self.credentials = credentials
        self.session = session or requests.Session()

    def request(self, method: str, path: str, *, params=None, json=None) -> dict[str, Any]:
        if not path.startswith("/me/") or "?" in path or "#" in path:
            raise ValueError("Graph requests must target the signed-in mailbox.")
        return self._request(method, GRAPH_ROOT + path, params=params, json=json)

    def _request(self, method: str, url: str, *, params=None, json=None) -> dict[str, Any]:
        response = self.session.request(
            method,
            url,
            params=params,
            json=json,
            timeout=30,
            allow_redirects=False,
            headers={
                "Authorization": f"Bearer {self.credentials.access_token}",
                "Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"',
            },
        )
        if not 200 <= response.status_code < 300:
            # Raw errors may echo message contents, queries, or credentials.
            raise RuntimeError(
                f"Microsoft Graph returned HTTP {response.status_code}. "
                "Check account permissions, resource IDs, and Outlook query syntax. "
                "If a write timed out, inspect Drafts/Sent before retrying."
            )
        return response.json() if response.content else {}

    def page(self, path: str, params: dict, next_link: str | None = None) -> dict:
        if next_link is None:
            return self.request("GET", path, params=params)
        parsed = urlsplit(next_link)
        expected = urlsplit(GRAPH_ROOT + path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        fixed = {k: v for k, v in query.items() if k not in {"$skip", "$skiptoken"}}
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or parsed.path != expected.path
            or parsed.fragment
            or fixed != {k: [str(v)] for k, v in params.items()}
            or not ({"$skip", "$skiptoken"} & query.keys())
            or any(len(v) != 1 for v in query.values())
        ):
            raise ValueError("Page token does not match this mailbox query; repeat the search.")
        # Forward the entire validated nextLink without editing its paging values.
        return self._request("GET", next_link)

    def all_pages(self, path: str, params: dict) -> list[dict]:
        results = []
        next_link = None
        seen = set()
        for _ in range(100):
            response = self.page(path, params, next_link)
            results.extend(response.get("value", []))
            next_link = response.get("@odata.nextLink")
            if not next_link:
                return results
            if next_link in seen:
                raise RuntimeError("Microsoft Graph returned a repeated pagination link.")
            seen.add(next_link)
        raise RuntimeError("Mailbox result exceeds 100 pages; narrow the request.")
