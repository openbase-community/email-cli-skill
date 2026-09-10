from __future__ import annotations

from unittest.mock import Mock
from urllib.parse import urlencode

import pytest

from gmail_cli.graph import GRAPH_ROOT, GraphTransport, item_path
from gmail_cli.outlook_auth import OutlookCredentials


@pytest.fixture
def graph():
    session = Mock()
    session.request.return_value = Mock(status_code=200, content=b"{}")
    session.request.return_value.json.return_value = {"value": []}
    return GraphTransport(OutlookCredentials("test-only", ["Mail.Read"], "a@example.com"), session)


def test_graph_headers_timeout_and_no_redirects(graph):
    graph.request("GET", "/me/messages", params={"$select": "id"})
    kwargs = graph.session.request.call_args.kwargs
    assert not kwargs["allow_redirects"] and kwargs["timeout"] == 30
    assert "ImmutableId" in kwargs["headers"]["Prefer"]


def test_preserves_full_valid_pagination_url(graph):
    params = {"$select": "id,from", "$top": 10}
    link = GRAPH_ROOT + "/me/messages?" + urlencode({**params, "$skip": 23})
    graph.page("/me/messages", params, link)
    assert graph.session.request.call_args.args[1] == link


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example/me/messages?$select=id&$skip=10",
        "https://graph.microsoft.com.evil.example/v1.0/me/messages?$select=id&$skip=10",
        "https://graph.microsoft.com/v1.0/me/messages?$select=body&$skip=10",
        "https://graph.microsoft.com/v1.0/me/messages?$select=id&$expand=attachments&$skip=10",
        "https://graph.microsoft.com/v1.0/users/other/messages?$select=id&$skip=10",
        "http://graph.microsoft.com/v1.0/me/messages?$select=id&$skip=10",
        "https://graph.microsoft.com/v1.0/me/messages?$select=id&$select=body&$skip=10",
    ],
)
def test_invalid_page_tokens_cannot_leak_bodies_or_credentials(graph, link):
    with pytest.raises(ValueError):
        graph.page("/me/messages", {"$select": "id"}, link)
    graph.session.request.assert_not_called()


def test_all_pages_follows_next_link(graph):
    params = {"$select": "id"}
    link = GRAPH_ROOT + "/me/messages?" + urlencode({**params, "$skip": 10})
    graph.session.request.return_value.json.side_effect = [
        {"value": [{"id": "one"}], "@odata.nextLink": link},
        {"value": [{"id": "two"}]},
    ]
    assert graph.all_pages("/me/messages", params) == [{"id": "one"}, {"id": "two"}]


def test_graph_errors_never_echo_server_body_or_retry(graph):
    graph.session.request.return_value = Mock(status_code=429, content=b"secret")
    with pytest.raises(RuntimeError, match="HTTP 429") as exc:
        graph.request("POST", "/me/messages", json={"body": "secret"})
    assert "secret" not in str(exc.value)
    assert graph.session.request.call_count == 1


def test_resource_ids_cannot_inject_path_or_query():
    assert item_path("messages", "a/b?x#y") == "/me/messages/a%2Fb%3Fx%23y"
    with pytest.raises(ValueError):
        item_path("messages", "..")
