---
name: gmail-cli
description: >-
  Use this skill when users ask about Gmail CLI workflows, Gmail search or reading, Gmail approved senders, Gmail draft creation, or Gmail draft sending through the local CLI.
version: 0.1.0
---

# Gmail CLI

Use the local Gmail CLI for safe Gmail search, reading, approved-sender management, draft creation, and draft sending with Openbase Coder approval gates.

## When To Use

Use this skill when:

- the user is working on Gmail CLI workflows, Gmail search or reading, Gmail approved senders, Gmail draft creation, or Gmail draft sending through the local CLI
- the task needs repo-specific guidance, commands, or conventions
- the same workflow would otherwise need to be re-explained repeatedly

## Workflow

1. Use `gmail-cli` for Gmail work instead of MCP tools from the old Gmail MCP server.
2. Read/search operations may be run directly, but message and thread bodies are only returned for approved senders.
3. If a mutating command returns JSON with `status: "approval_required"`, it has created a request in the Openbase Coder approvals dashboard.
4. The user must manually approve or decline the request at `http://localhost:7999/dashboard/approvals`.
5. Rerun the same command only after the user says they approved it in the dashboard.
6. Never mutate Openbase Coder approval state yourself. Do not edit approval request files, insert decisions, mark requests accepted, or otherwise simulate dashboard approval.
7. Do not use `--approved-by-user` unless the user explicitly asks to bypass the dashboard mechanism.
8. Do not send drafts, create drafts, or change approved senders without approval.

## Commands

Install or run from the skill repo:

```bash
uv sync
uv run gmail-cli --help
```

Authenticate:

```bash
gmail-cli auth paths
gmail-cli auth login --account default
gmail-cli auth login --account work --include-compose
gmail-cli auth login --account work --include-compose --include-send
gmail-cli auth accounts
```

Search and read:

```bash
gmail-cli search 'from:alice@example.com newer_than:30d' --max-results 10
gmail-cli search --threads 'subject:(invoice)' --max-results 5
gmail-cli message MESSAGE_ID --include-body
gmail-cli thread THREAD_ID --max-body-chars 8000
gmail-cli labels
```

Manage approved senders:

```bash
gmail-cli approved-senders list --account work
gmail-cli approved-senders add --account work alice@example.com
```

The `add` and `remove` forms intentionally return `approval_required` unless rerun after approval:

```json
{
  "status": "approval_required",
  "approval": {
    "action": "add_gmail_approved_senders",
    "dashboard_url": "http://localhost:7999/dashboard/approvals",
    "rerun_after_approval": true
  }
}
```

Draft and send:

```bash
gmail-cli draft-new --to alice@example.com --subject "Hello" --body-file /tmp/body.txt
gmail-cli draft-reply THREAD_ID --body-file /tmp/reply.txt
gmail-cli send-draft DRAFT_ID
```

These commands also require approval from the Openbase Coder approvals dashboard before rerunning.

## Openbase Coder Approval Contract

The CLI does not perform a sensitive action when approval is missing. It exits with code `2` and
creates a pending request in `http://localhost:7999/dashboard/approvals`. It also
prints structured JSON containing:

- `status: "approval_required"`
- `approval.action`
- `approval.prompt`
- `approval.details`
- `approval.dashboard_url`

When acting as an Openbase Coder agent, tell the user to approve or decline the request in the
dashboard. Manual user approval is required: the user must be the actor who clicks approve or
decline in the dashboard. If the user approves, rerun the same command. The CLI consumes the
dashboard decision and continues. If the user declines, do not rerun.

Agents must never mutate the Openbase Coder approval state directly. Do not edit approval request
or decision files under `~/.super-agents`, do not call internal approval-state APIs to accept a
request, and do not forge, backfill, or patch approval decisions. The only acceptable agent action
is to create the request by running the Gmail CLI command, notify the user that approval is needed,
and rerun the same command after the user confirms they approved it manually.

## Configuration

Default config lives under `~/.config/gmail-cli`. Supported environment variables:

- `GMAIL_CLI_CREDENTIALS_PATH`
- `GMAIL_CLI_TOKEN_PATH`
- `GMAIL_CLI_APPROVED_SENDERS`
- `GMAIL_CLI_APPROVED_SENDERS_PATH`

Legacy `GMAIL_MCP_*` names are still honored as fallbacks during migration.

## Safety Notes

- Search results strip snippet/body-like fields.
- Bodies are fetched only for approved senders.
- Approved-sender changes are local config writes and require approval.
- Draft creation and sending mutate Gmail state and require approval.
- Sending requires an OAuth token with `gmail.send`; draft creation requires `gmail.compose`.
