from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
import requests
from test_read_screening import gmail_client, response

from email_cli.flagged_summary import FlaggedSummarizer, configured_summarizer
from email_cli.read_screening import ReadScreener
from email_cli.screening_policy import MAX_STATE_CHARS
from email_cli.summary_policy import QUESTIONS as SUMMARY_QUESTIONS


def summarizer(text="The sender requests feedback on an external project brief.", **overrides):
    transport = Mock()
    transport.post.return_value.status_code = 200
    payload = {
        "status": "completed",
        "usage": {"input_tokens": 500, "output_tokens": 30},
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps({"summary": text})},
                ],
            }
        ],
        **overrides,
    }
    transport.post.return_value.json.return_value = payload
    return FlaggedSummarizer("test-only", transport=transport)


def test_request_is_tool_free_bounded_and_not_stored():
    s = summarizer()
    result = s.summarize({"parts": [{"content": "PRIVATE ORIGINAL"}]})
    assert result["status"] == "generated"
    assert "PRIVATE ORIGINAL" not in json.dumps(result)
    args = s.transport.post.call_args.kwargs
    assert not args["allow_redirects"]
    assert args["json"]["tools"] == []
    assert args["json"]["store"] is False
    assert args["json"]["max_output_tokens"] == 512
    assert args["json"]["reasoning"] == {"effort": "minimal"}


@pytest.mark.parametrize("state", [{"incomplete": True}, {"body": "x" * MAX_STATE_CHARS}])
def test_no_truncated_summary_of_incomplete_content(state):
    s = summarizer()
    assert s.summarize(state)["status"] == "unavailable"
    s.transport.post.assert_not_called()


def test_attachments_explicitly_excluded():
    assert summarizer().summarize({"attachments": ["brief.pdf"]})["coverage"] == (
        "body_only_attachments_excluded"
    )


@pytest.mark.parametrize("status", [301, 401, 429, 500])
def test_http_failure_does_not_release_error_body(status):
    s = summarizer()
    s.transport.post.return_value.status_code = status
    result = s.summarize({})
    assert result["status"] == "unavailable" and "text" not in result


@pytest.mark.parametrize("text", [None, 42, "", "x" * 601, "word " * 71, "a\nb"])
def test_invalid_summary_is_withheld(text):
    result = summarizer(text).summarize({})
    assert result["status"] == "unavailable" and "text" not in result


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "incomplete"},
        {"output": []},
        {"output": None},
        {"usage": None},
        {"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]},
    ],
)
def test_incomplete_refused_and_malformed_responses_are_withheld(payload):
    result = summarizer(**payload).summarize({})
    assert result["status"] == "unavailable" and "text" not in result


def test_timeout_does_not_leak_content():
    s = summarizer()
    s.transport.post.side_effect = requests.Timeout("SECRET ORIGINAL")
    assert "SECRET ORIGINAL" not in json.dumps(s.summarize({}))


def test_summary_opt_in_is_separate_and_account_provider_specific(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = {"enabled_accounts": {"gmail": ["work"]}}
    assert configured_summarizer(config, "work", "gmail") is None
    config["flagged_summaries"] = {"enabled_accounts": {"gmail": ["work"]}}
    assert configured_summarizer(config, "personal", "gmail") is None
    assert configured_summarizer(config, "work", "outlook") is None
    assert configured_summarizer(config, "work", "gmail").summarize({})["reason"] == (
        "missing_openai_key"
    )


@pytest.mark.parametrize("summary_risk", [0, 0.9])
def test_summary_cannot_unblock_body_or_grant_sender_and_audit_has_no_preview(
    tmp_path, summary_risk
):
    gate_transport = Mock()
    gate_transport.post.return_value.status_code = 200
    gate_transport.post.return_value.json.side_effect = [
        response(unfamiliar_site=0.9),
        {
            **response(),
            "answers": {name: {"type": "noul", "noul": summary_risk} for name in SUMMARY_QUESTIONS},
        },
    ]
    s = ReadScreener(
        "test-only", audit_path=tmp_path, transport=gate_transport, summarizer=summarizer()
    )
    client = gmail_client(False)
    client.read_screener = s
    result = client.get_message(message_id="m", include_body=True)
    assert result["content_redacted"] and not result["sender_approved"]
    assert "PRIVATE BODY" not in json.dumps(result)
    summary = result["read_screening"]["review_summary"]
    assert ("text" in summary) is (summary_risk == 0)
    for path in tmp_path.glob("*.json"):
        assert "external project brief" not in path.read_text()
        assert "PRIVATE BODY" not in path.read_text()


def test_allowed_mail_does_not_invoke_summarizer():
    transport = Mock()
    transport.post.return_value.status_code = 200
    transport.post.return_value.json.return_value = response()
    summary = Mock()
    gate = ReadScreener("test-only", transport=transport, summarizer=summary)
    assert gate.evaluate({}).approved
    summary.summarize.assert_not_called()


def test_even_recognized_url_is_withheld_from_summary():
    transport = Mock()
    gate = ReadScreener(
        "test-only",
        transport=transport,
        summarizer=summarizer("The sender suggests https://www.wikipedia.org."),
    )
    decision = gate.evaluate({"attachments": ["brief.pdf"]})
    assert decision.review_summary["status"] == "withheld"
    assert "text" not in decision.review_summary
    transport.post.assert_not_called()


def test_summary_guard_failure_cannot_release_preview():
    transport = Mock()
    transport.post.side_effect = requests.Timeout("SECRET")
    gate = ReadScreener("test-only", transport=transport, summarizer=summarizer())
    decision = gate.evaluate({"attachments": ["brief.pdf"]})
    assert not decision.approved
    assert decision.review_summary["status"] == "withheld"
    assert "text" not in decision.review_summary
