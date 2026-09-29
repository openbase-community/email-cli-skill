"""Command line interface for safe local Gmail workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

from googleapiclient.discovery import build

from email_cli.approval import ApprovalRequiredError, require_user_approval
from email_cli.approved_senders import (
    add_approved_senders,
    approved_senders_path,
    load_approved_senders,
    remove_approved_senders,
)
from email_cli.auth import (
    credentials_path,
    list_accounts,
    load_credentials,
    run_oauth_flow_for_account,
    token_path,
)
from email_cli.cli_parser import build_parser
from email_cli.client import GmailClient
from email_cli.provider_paths import PROVIDER_NAMES
from email_cli.read_screening import configured_screener
from email_cli.scopes import (
    DEFAULT_SCOPES,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_MODIFY_SCOPE,
    GMAIL_SEND_SCOPE,
)


def main(argv: list[str] | None = None, *, default_provider: str = "gmail") -> None:
    parser = build_parser(default_provider=default_provider)
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


def outlook_main() -> None:
    main(default_provider="outlook")


def apple_mail_main() -> None:
    main(default_provider="apple-mail")


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    provider_name = PROVIDER_NAMES[args.provider]
    if args.command == "auth":
        return dispatch_auth(args)
    if args.command in {"labels", "folders"}:
        return configured_client(args.account, args.provider).list_labels()
    if args.command == "search":
        max_results = min(max(args.max_results, 1), 100)
        client = configured_client(args.account, args.provider)
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
        return configured_client(args.account, args.provider).get_message(
            message_id=args.message_id,
            include_body=args.include_body,
            max_body_chars=clamp_body_chars(args.max_body_chars),
        )
    if args.command == "thread":
        return configured_client(args.account, args.provider).get_thread(
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
            action=f"create_{args.provider}_draft",
            prompt=f"Create a {provider_name} draft to {args.to!r} with subject {args.subject!r}?",
            details={
                "account": args.account or "default",
                "provider": args.provider,
                "to": args.to,
                "cc": args.cc,
                "bcc": args.bcc,
                "subject": args.subject,
                "body_preview": body_text[:500],
                "body_sha256": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
            },
        )
        return configured_client(args.account, args.provider).create_draft_new(
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
            action=f"create_{args.provider}_reply_draft",
            prompt=f"Create a {provider_name} reply draft in thread {args.thread_id!r}?",
            details={
                "account": args.account or "default",
                "provider": args.provider,
                "thread_id": args.thread_id,
                "reply_all": args.reply_all,
                "include_quoted_history": not args.no_quoted_history,
                "body_preview": body_text[:500],
                "body_sha256": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
            },
        )
        return configured_client(args.account, args.provider).create_draft_reply(
            thread_id=args.thread_id,
            body_text=body_text,
            reply_all=args.reply_all,
            include_quoted_history=not args.no_quoted_history,
            confirm_create=True,
        )
    if args.command == "send-draft":
        require_user_approval(
            args.approved_by_user,
            action=f"send_{args.provider}_draft",
            prompt=f"Send {provider_name} draft {args.draft_id!r}?",
            details={
                "account": args.account or "default",
                "provider": args.provider,
                "draft_id": args.draft_id,
            },
        )
        return configured_client(args.account, args.provider).send_draft(
            draft_id=args.draft_id,
            confirm_send=True,
        )
    raise RuntimeError(f"Unsupported command {args.command!r}")


def dispatch_auth(args: argparse.Namespace) -> dict[str, Any]:
    if args.provider == "apple-mail":
        from email_cli.apple_mail_auth import dispatch_auth as apple_mail_auth

        return apple_mail_auth(args)
    if args.provider == "outlook":
        from email_cli.outlook_auth import dispatch_auth as outlook_auth

        return outlook_auth(args)
    if args.auth_command == "login" and (
        args.client_id or args.tenant or args.username or args.device_code
    ):
        raise ValueError("Microsoft login options require --provider outlook.")
    if args.auth_command == "paths":
        return {
            "credentials_path": str(credentials_path()),
            "token_path": str(token_path(args.account)),
            "approved_senders_path": str(
                approved_senders_path(args.account, provider=args.provider)
            ),
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
            "provider": args.provider,
            "token_path": str(token_path(args.account)),
            "scopes": creds.scopes or scopes,
        }
    raise RuntimeError(f"Unsupported auth command {args.auth_command!r}")


def dispatch_approved_senders(args: argparse.Namespace) -> dict[str, Any]:
    provider_name = PROVIDER_NAMES[args.provider]
    if args.approved_command == "list":
        approved = load_approved_senders(args.account, provider=args.provider)
    elif args.approved_command == "add":
        require_user_approval(
            args.approved_by_user,
            action=f"add_{args.provider}_approved_senders",
            prompt=f"Allow {provider_name} body access for sender(s): {', '.join(args.senders)}?",
            details={
                "account": args.account or "default",
                "provider": args.provider,
                "senders": args.senders,
                "approved_senders_path": str(
                    approved_senders_path(args.account, provider=args.provider)
                ),
            },
        )
        approved = add_approved_senders(args.senders, args.account, provider=args.provider)
    elif args.approved_command == "remove":
        require_user_approval(
            args.approved_by_user,
            action=f"remove_{args.provider}_approved_senders",
            prompt=f"Remove {provider_name} body access for sender(s): {', '.join(args.senders)}?",
            details={
                "account": args.account or "default",
                "provider": args.provider,
                "senders": args.senders,
                "approved_senders_path": str(
                    approved_senders_path(args.account, provider=args.provider)
                ),
            },
        )
        approved = remove_approved_senders(args.senders, args.account, provider=args.provider)
    else:
        raise RuntimeError(f"Unsupported approved-senders command {args.approved_command!r}")
    return {
        "account": args.account or "default",
        "provider": args.provider,
        "approved_senders_path": str(approved_senders_path(args.account, provider=args.provider)),
        **approved.as_dict(),
    }


def configured_client(account: str | None = None, provider: str = "gmail"):
    if provider == "apple-mail":
        from email_cli.apple_mail_auth import load_account
        from email_cli.apple_mail_client import AppleMailClient

        return AppleMailClient(
            load_account(account),
            load_approved_senders(account, provider=provider),
            account_name=account,
            read_screener=configured_screener(account, provider),
        )
    if provider == "outlook":
        from email_cli.outlook_auth import load_credentials as load_outlook_credentials
        from email_cli.outlook_client import OutlookClient

        return OutlookClient(
            credentials=load_outlook_credentials(account),
            approved_senders=load_approved_senders(account, provider=provider),
            read_screener=configured_screener(account, provider),
        )
    creds = load_credentials(account=account)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return GmailClient(
        service=service,
        credentials=creds,
        approved_senders=load_approved_senders(account=account),
        read_screener=configured_screener(account, provider),
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
