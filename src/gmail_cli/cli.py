"""Command line interface for safe local Gmail workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build

from gmail_cli.approval import ApprovalRequiredError, require_user_approval
from gmail_cli.approved_senders import (
    add_approved_senders,
    approved_senders_path,
    load_approved_senders,
    remove_approved_senders,
)
from gmail_cli.auth import (
    credentials_path,
    list_accounts,
    load_credentials,
    run_oauth_flow_for_account,
    token_path,
)
from gmail_cli.client import GmailClient
from gmail_cli.scopes import (
    DEFAULT_SCOPES,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_MODIFY_SCOPE,
    GMAIL_SEND_SCOPE,
)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except ApprovalRequiredError as exc:
        print_json(exc.request.as_dict())
        raise SystemExit(2) from exc
    except Exception as exc:
        print_json({"status": "error", "error": str(exc)})
        raise SystemExit(1) from exc
    print_json({"status": "ok", **result})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Gmail CLI with approval-gated mutations")
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
    login.add_argument("--port", type=int, default=0, help="Local OAuth callback port")
    paths = auth_subparsers.add_parser("paths", help="Print credential and config paths")
    add_account_argument(paths)
    auth_subparsers.add_parser("accounts", help="List configured account tokens")

    labels = subparsers.add_parser("labels", help="List Gmail labels")
    add_account_argument(labels)

    search = subparsers.add_parser("search", help="Search Gmail messages or threads")
    add_account_argument(search)
    search.add_argument("query", help="Gmail search query")
    search.add_argument("--threads", action="store_true", help="Search threads instead of messages")
    search.add_argument("--max-results", type=int, default=10)
    search.add_argument("--page-token")
    search.add_argument("--label-id", action="append", dest="label_ids")

    get_message = subparsers.add_parser("message", help="Read a Gmail message by id")
    add_account_argument(get_message)
    get_message.add_argument("message_id")
    get_message.add_argument("--include-body", action="store_true")
    get_message.add_argument("--max-body-chars", type=int, default=4000)

    get_thread = subparsers.add_parser("thread", help="Read a Gmail thread by id")
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

    draft_new = subparsers.add_parser("draft-new", help="Create a new Gmail draft")
    add_account_argument(draft_new)
    draft_new.add_argument("--to", required=True)
    draft_new.add_argument("--subject", required=True)
    draft_new.add_argument("--body", help="Draft body text")
    draft_new.add_argument("--body-file", type=Path, help="Read draft body text from a file")
    draft_new.add_argument("--cc")
    draft_new.add_argument("--bcc")
    add_approval_argument(draft_new)

    draft_reply = subparsers.add_parser("draft-reply", help="Create a Gmail reply draft")
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

    send = subparsers.add_parser("send-draft", help="Send an existing Gmail draft")
    add_account_argument(send)
    send.add_argument("draft_id")
    add_approval_argument(send)

    return parser


def add_account_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", default=None, help="Named Gmail account")


def add_approval_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--approved-by-user",
        action="store_true",
        help="Declare that the user approved this exact sensitive action",
    )


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "auth":
        return dispatch_auth(args)
    if args.command == "labels":
        return configured_client(args.account).list_labels()
    if args.command == "search":
        max_results = min(max(args.max_results, 1), 100)
        client = configured_client(args.account)
        if args.threads:
            return client.search_threads(
                query=args.query,
                max_results=max_results,
                page_token=args.page_token,
                label_ids=args.label_ids,
            )
        return client.search_messages(
            query=args.query,
            max_results=max_results,
            page_token=args.page_token,
            label_ids=args.label_ids,
        )
    if args.command == "message":
        return configured_client(args.account).get_message(
            message_id=args.message_id,
            include_body=args.include_body,
            max_body_chars=clamp_body_chars(args.max_body_chars),
        )
    if args.command == "thread":
        return configured_client(args.account).get_thread(
            thread_id=args.thread_id,
            include_body=not args.no_body,
            max_body_chars=clamp_body_chars(args.max_body_chars),
        )
    if args.command == "approved-senders":
        return dispatch_approved_senders(args)
    if args.command == "draft-new":
        body_text = read_body_text(args)
        require_user_approval(
            args.approved_by_user,
            action="create_gmail_draft",
            prompt=f"Create a Gmail draft to {args.to!r} with subject {args.subject!r}?",
            details={
                "account": args.account or "default",
                "to": args.to,
                "cc": args.cc,
                "bcc": args.bcc,
                "subject": args.subject,
                "body_preview": body_text[:500],
            },
        )
        return configured_client(args.account).create_draft_new(
            to=args.to,
            subject=args.subject,
            body_text=body_text,
            cc=args.cc,
            bcc=args.bcc,
            confirm_create=True,
        )
    if args.command == "draft-reply":
        body_text = read_body_text(args)
        require_user_approval(
            args.approved_by_user,
            action="create_gmail_reply_draft",
            prompt=f"Create a Gmail reply draft in thread {args.thread_id!r}?",
            details={
                "account": args.account or "default",
                "thread_id": args.thread_id,
                "reply_all": args.reply_all,
                "include_quoted_history": not args.no_quoted_history,
                "body_preview": body_text[:500],
            },
        )
        return configured_client(args.account).create_draft_reply(
            thread_id=args.thread_id,
            body_text=body_text,
            reply_all=args.reply_all,
            include_quoted_history=not args.no_quoted_history,
            confirm_create=True,
        )
    if args.command == "send-draft":
        require_user_approval(
            args.approved_by_user,
            action="send_gmail_draft",
            prompt=f"Send Gmail draft {args.draft_id!r}?",
            details={
                "account": args.account or "default",
                "draft_id": args.draft_id,
            },
        )
        return configured_client(args.account).send_draft(
            draft_id=args.draft_id,
            confirm_send=True,
        )
    raise RuntimeError(f"Unsupported command {args.command!r}")


def dispatch_auth(args: argparse.Namespace) -> dict[str, Any]:
    if args.auth_command == "paths":
        return {
            "credentials_path": str(credentials_path()),
            "token_path": str(token_path(args.account)),
            "approved_senders_path": str(approved_senders_path(args.account)),
        }
    if args.auth_command == "accounts":
        return {"accounts": list_accounts()}
    if args.auth_command == "login":
        scopes = list(DEFAULT_SCOPES)
        if args.include_compose:
            scopes.append(GMAIL_COMPOSE_SCOPE)
        if args.include_modify:
            scopes.append(GMAIL_MODIFY_SCOPE)
        if args.include_send:
            scopes.append(GMAIL_SEND_SCOPE)
        creds = run_oauth_flow_for_account(scopes=scopes, port=args.port, account=args.account)
        return {
            "account": args.account or "default",
            "token_path": str(token_path(args.account)),
            "scopes": creds.scopes or scopes,
        }
    raise RuntimeError(f"Unsupported auth command {args.auth_command!r}")


def dispatch_approved_senders(args: argparse.Namespace) -> dict[str, Any]:
    if args.approved_command == "list":
        approved = load_approved_senders(args.account)
    elif args.approved_command == "add":
        require_user_approval(
            args.approved_by_user,
            action="add_gmail_approved_senders",
            prompt=f"Allow Gmail body access for sender(s): {', '.join(args.senders)}?",
            details={
                "account": args.account or "default",
                "senders": args.senders,
                "approved_senders_path": str(approved_senders_path(args.account)),
            },
        )
        approved = add_approved_senders(args.senders, args.account)
    elif args.approved_command == "remove":
        require_user_approval(
            args.approved_by_user,
            action="remove_gmail_approved_senders",
            prompt=f"Remove Gmail body access for sender(s): {', '.join(args.senders)}?",
            details={
                "account": args.account or "default",
                "senders": args.senders,
                "approved_senders_path": str(approved_senders_path(args.account)),
            },
        )
        approved = remove_approved_senders(args.senders, args.account)
    else:
        raise RuntimeError(f"Unsupported approved-senders command {args.approved_command!r}")
    return {
        "account": args.account or "default",
        "approved_senders_path": str(approved_senders_path(args.account)),
        **approved.as_dict(),
    }


def configured_client(account: str | None = None) -> GmailClient:
    creds = load_credentials(account=account)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return GmailClient(
        service=service,
        credentials=creds,
        approved_senders=load_approved_senders(account=account),
    )


def read_body_text(args: argparse.Namespace) -> str:
    if args.body_file and args.body:
        raise ValueError("Use either --body or --body-file, not both.")
    if args.body_file:
        return args.body_file.read_text(encoding="utf-8")
    if args.body is not None:
        return args.body
    raise ValueError("Provide draft text with --body or --body-file.")


def clamp_body_chars(value: int) -> int:
    return min(max(value, 0), 50000)


def print_json(value: dict[str, Any]) -> None:
    json.dump(value, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
