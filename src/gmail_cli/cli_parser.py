"""Shared Gmail/Outlook command-line arguments."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser(*, default_provider: str = "gmail") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Gmail and Outlook CLI with approval gates")
    add_provider_argument(parser, default=default_provider)
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser("auth", help="Manage local OAuth credentials")
    auth_subparsers = auth.add_subparsers(dest="auth_command", required=True)
    login = auth_subparsers.add_parser("login", help="Run local OAuth login and store a token")
    add_account_argument(login)
    login.add_argument("--include-compose", action="store_true", help="Allow creating drafts")
    login.add_argument(
        "--include-modify",
        action="store_true",
        help="Allow label/archive/read changes",
    )
    login.add_argument("--include-send", action="store_true", help="Allow sending drafts")
    login.add_argument("--client-id", help="Microsoft Entra public client application ID")
    login.add_argument("--tenant", help="Microsoft tenant ID/domain (default: common)")
    login.add_argument("--username", help="Expected Microsoft sign-in email")
    login.add_argument("--device-code", action="store_true", help="Use Microsoft device login")
    login.add_argument("--port", type=int, default=0, help="Local OAuth callback port")
    paths = auth_subparsers.add_parser("paths", help="Print credential and config paths")
    add_account_argument(paths)
    accounts = auth_subparsers.add_parser("accounts", help="List configured account tokens")
    add_provider_argument(accounts)

    labels = subparsers.add_parser("labels", aliases=["folders"], help="List labels or folders")
    add_account_argument(labels)

    search = subparsers.add_parser("search", help="Search messages or threads")
    add_account_argument(search)
    search.add_argument(
        "query", help="Gmail query or Outlook KQL query (empty string lists messages)"
    )
    search.add_argument("--threads", action="store_true", help="Search threads instead of messages")
    search.add_argument("--max-results", type=int, default=10)
    search.add_argument("--page-token")
    search.add_argument("--label-id", "--folder-id", action="append", dest="label_ids")

    get_message = subparsers.add_parser("message", help="Read a message by id")
    add_account_argument(get_message)
    get_message.add_argument("message_id")
    get_message.add_argument("--include-body", action="store_true")
    get_message.add_argument("--max-body-chars", type=int, default=4000)

    get_thread = subparsers.add_parser("thread", help="Read a thread by id")
    add_account_argument(get_thread)
    get_thread.add_argument("thread_id")
    get_thread.add_argument("--no-body", action="store_true")
    get_thread.add_argument("--max-body-chars", type=int, default=4000)

    approved = subparsers.add_parser(
        "approved-senders", help="Manage approved body-readable senders"
    )
    approved_subparsers = approved.add_subparsers(dest="approved_command", required=True)
    approved_list = approved_subparsers.add_parser("list", help="List approved senders")
    add_account_argument(approved_list)
    approved_add = approved_subparsers.add_parser("add", help="Add approved sender email addresses")
    add_account_argument(approved_add)
    approved_add.add_argument("senders", nargs="+")
    add_approval_argument(approved_add)
    approved_remove = approved_subparsers.add_parser("remove", help="Remove approved sender emails")
    add_account_argument(approved_remove)
    approved_remove.add_argument("senders", nargs="+")
    add_approval_argument(approved_remove)

    draft_new = subparsers.add_parser("draft-new", help="Create a new draft")
    add_account_argument(draft_new)
    draft_new.add_argument("--to", required=True)
    draft_new.add_argument("--subject", required=True)
    draft_new.add_argument("--body", help="Draft body text")
    draft_new.add_argument("--body-file", type=Path, help="Read draft body text from a file")
    draft_new.add_argument("--cc")
    draft_new.add_argument("--bcc")
    add_approval_argument(draft_new)

    draft_reply = subparsers.add_parser("draft-reply", help="Create a reply draft")
    add_account_argument(draft_reply)
    draft_reply.add_argument("thread_id")
    draft_reply.add_argument("--body", help="Draft body text")
    draft_reply.add_argument("--body-file", type=Path, help="Read draft body text from a file")
    draft_reply.add_argument("--reply-all", action="store_true")
    draft_reply.add_argument(
        "--no-quoted-history",
        action="store_true",
        help="Do not append the visible quoted email trail to the reply body",
    )
    add_approval_argument(draft_reply)

    send = subparsers.add_parser("send-draft", help="Send an existing draft")
    add_account_argument(send)
    send.add_argument("draft_id")
    add_approval_argument(send)

    return parser


def add_provider_argument(parser: argparse.ArgumentParser, *, default=argparse.SUPPRESS) -> None:
    parser.add_argument("--provider", choices=["gmail", "outlook"], default=default)


def add_account_argument(parser: argparse.ArgumentParser) -> None:
    add_provider_argument(parser)
    parser.add_argument("--account", default=None, help="Named account within this provider")


def add_approval_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--approved-by-user",
        action="store_true",
        help="Declare that the user approved this exact sensitive action",
    )
