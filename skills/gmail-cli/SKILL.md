---
name: gmail-cli
description: >-
  Use this skill for Gmail or Outlook/Microsoft 365 email through the local CLI: authentication, search, message and thread reading, approved senders, draft creation, replies, and sending.
version: 0.2.0
---

# Gmail and Outlook CLI

Use the local CLI for Gmail and Outlook/Microsoft 365 email with Openbase Coder approval gates. `gmail-cli` defaults to Gmail; `outlook-cli` defaults to Outlook. `gmail-cli --provider outlook` is equivalent to `outlook-cli`. Do not infer that a connected Gmail account grants access to an Outlook account.

## Workflow

1. Use the CLI instead of the old Gmail MCP server. Select the provider and named account explicitly when handling multiple accounts.
2. Read/search operations may run directly. Bodies are fetched only for approved senders, including on Outlook conversation reads.
3. If a mutating command returns JSON with `status: "approval_required"`, it created a request in the Openbase Coder approvals dashboard and did not perform the mutation.
4. The user must manually approve or decline that request at `http://localhost:7999/dashboard/approvals`.
5. Rerun the same command only after the user says they approved it in the dashboard. Do not rerun a declined request.
6. Never mutate Openbase Coder approval state yourself. Do not edit request/decision files, call internal approval-state APIs, insert decisions, mark requests accepted, or otherwise simulate dashboard approval.
7. Do not use `--approved-by-user` unless the user explicitly asks to bypass the dashboard mechanism.
8. Do not send drafts, create drafts, or change approved senders without approval.

## Install and authenticate

```bash
uv sync --extra dev
uv run gmail-cli --help
uv run outlook-cli --help

gmail-cli auth paths
gmail-cli auth login --account default
gmail-cli auth login --account work --include-compose --include-send
gmail-cli auth accounts

outlook-cli auth paths --account school
outlook-cli auth login --account school --client-id YOUR_APPLICATION_ID --username user@school.edu
outlook-cli auth accounts
```

Outlook requires your own Microsoft Entra public-client application. Register the Mobile and desktop applications platform with `http://localhost` as a redirect URI; no client secret is needed. The default browser flow uses MSAL. For `--device-code`, enable public client flows in the app registration, then follow Microsoft's user sign-in instructions. Work/school tenants may require administrator consent; never bypass tenant policies or approve a new access grant on the user's behalf.

Read-only Outlook sign-in requests `User.Read` and `Mail.Read`. Add `--include-compose` for `Mail.ReadWrite` and `--include-send` for `Mail.Send` only when needed. Microsoft has no compose-only delegated permission. The app ID/tenant/identity are remembered for later sign-in, and tokens refresh silently. A named Outlook account cannot be rebound to a different Microsoft identity; use another account name.

## Search and read

```bash
gmail-cli search 'from:alice@example.com newer_than:30d' --account work --max-results 10
gmail-cli message MESSAGE_ID --account work --include-body
gmail-cli thread THREAD_ID --account work --max-body-chars 8000
gmail-cli labels --account work

outlook-cli search 'from:alice@example.com' --account school --max-results 10
outlook-cli search 'subject:meeting' --account school --threads
outlook-cli search '' --account school --folder-id inbox
outlook-cli folders --account school
outlook-cli message MESSAGE_ID --account school --include-body
outlook-cli thread CONVERSATION_ID --account school --max-body-chars 8000
```

Outlook queries use Microsoft Graph/KQL mail search, not Gmail syntax. Do not send Gmail-only operators such as `newer_than:` to Outlook. Empty queries list messages. Use at most one `--folder-id` (a returned ID or well-known name such as `inbox`). `labels` is also accepted on Outlook and returns folders; `--label-id` aliases its folder filter.

Search results contain metadata only, without snippets/body previews. Pass `next_page_token` back with `--page-token` and exactly the same query, folder, and result limit. Outlook thread search deduplicates within a page; conversation IDs can recur on subsequent pages. Microsoft mail search caps matches at 1,000, so narrow large queries. Outlook `thread` follows all conversation pages and applies the approved-sender gate separately to each message.

## Approved senders

```bash
gmail-cli approved-senders list --account work
gmail-cli approved-senders add --account work alice@example.com
outlook-cli approved-senders list --account school
outlook-cli approved-senders add --account school alice@example.com
```

`add` and `remove` require dashboard approval. Provider/account sender files are separate: Gmail approvals do not authorize Outlook reads. Approve your own address if you need bodies of your sent messages.

## Drafts and replies

```bash
gmail-cli draft-new --account work --to alice@example.com --subject "Hello" --body-file /tmp/body.txt
gmail-cli draft-reply THREAD_ID --account work --body-file /tmp/reply.txt
gmail-cli send-draft DRAFT_ID --account work

outlook-cli draft-new --account school --to alice@example.com --subject "Hello" --body-file /tmp/body.txt
outlook-cli draft-reply CONVERSATION_ID --account school --body-file /tmp/reply.txt
outlook-cli draft-reply CONVERSATION_ID --account school --reply-all --body-file /tmp/reply.txt
outlook-cli send-draft DRAFT_ID --account school
```

Use `draft-reply` for replies. Gmail preserves the thread ID/reply headers; Outlook uses native createReply/createReplyAll and verifies conversation membership. Both include the visible quoted trail by default unless `--no-quoted-history` is explicitly passed. Outlook replies target the latest non-draft message, and its sender must be approved before quoting. After creation, verify the returned `thread_id` and tell the user that the trail was included. Outlook also returns `quoted_history_included`.

All draft/send commands require approval. Outlook sending requires an existing draft and returns `send_status: "accepted"`; do not claim delivery from that alone. No automatic write retries occur. After an interrupted or timed-out write, check Drafts/Sent before retrying to avoid duplicates.

## Approval contract

An unapproved action exits 2 and prints `status`, `approval.action`, `approval.prompt`, `approval.details`, `approval.dashboard_url`, and `rerun_after_approval`. The shared dashboard request ID includes provider/account details; draft creation also binds the complete body by SHA-256, not only the displayed preview.

Manual user approval is required: only the user may click approve or decline in the dashboard. Do not edit files under `~/.super-agents`, forge/backfill decisions, or call internal acceptance APIs. Run the CLI to create a request, notify the user, and rerun only after they confirm manual approval.

## Configuration

Gmail retains `~/.config/gmail-cli` and the existing `GMAIL_CLI_CREDENTIALS_PATH`, `GMAIL_CLI_TOKEN_PATH`, `GMAIL_CLI_APPROVED_SENDERS`, and `GMAIL_CLI_APPROVED_SENDERS_PATH` variables, with legacy `GMAIL_MCP_*` fallbacks.

Outlook uses `~/.config/gmail-cli/outlook` or `OUTLOOK_CLI_CONFIG_DIR`. Each account has its own `token.json` and `approved_senders.json`. `OUTLOOK_CLI_CLIENT_ID` and `OUTLOOK_CLI_TENANT` configure initial Microsoft sign-in; `OUTLOOK_CLI_APPROVED_SENDERS` supplies optional comma-separated Outlook sender addresses. Gmail environment permissions are not used for Outlook. Tokens are stored with owner-only permissions. Never output token-cache contents or commit credentials, tokens, or approved-sender files.

This CLI covers email. It does not provide Outlook calendar operations. Consult the repository README for Microsoft app registration and provider differences.
