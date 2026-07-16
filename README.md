# Gmail CLI Skill

A local Gmail command line tool plus an agent skill for using it safely.

The CLI is `gmail-cli`. It supports Gmail OAuth setup, search, label listing, message/thread
reading, approved-sender management, draft creation, and draft sending. Sensitive operations create
an approval request and refuse to run until the user approves the exact action.

## Why a Custom CLI/Skill

Gmail is high-sensitivity infrastructure: message bodies, drafts, recipient lists, and send actions
all need stronger boundaries than a broad always-on MCP surface. This skill keeps the agent contract
small and auditable by exposing explicit JSON CLI commands, using the minimum OAuth scopes needed for
the requested operation, stripping body-like fields from search results, and requiring approved
senders before message bodies can be read. Draft creation, draft sending, and approved-sender changes
stay behind an explicit approval gate.

## Quick Start

```bash
uv sync
uv run gmail-cli --help
```

To install as an editable Python package:

```bash
python -m pip install -e ".[dev]"
gmail-cli --help
```

## Gmail OAuth Setup

Create a Google Cloud OAuth desktop client with the Gmail API enabled, download the client JSON, and
place it at:

```text
~/.config/gmail-cli/credentials.json
```

Then authenticate a read-only account:

```bash
gmail-cli auth login --account default
```

Add only the extra scopes you need:

```bash
gmail-cli auth login --account default --include-compose
gmail-cli auth login --account default --include-compose --include-send
```

## Common Commands

```bash
gmail-cli search 'from:alice@example.com newer_than:30d' --max-results 10
gmail-cli labels
gmail-cli approved-senders list
gmail-cli approved-senders add alice@example.com
gmail-cli message MESSAGE_ID --include-body
gmail-cli draft-new --to alice@example.com --subject "Hello" --body-file /tmp/body.txt
gmail-cli send-draft DRAFT_ID
```

Message and thread body access is restricted to approved senders. Search results intentionally strip
snippet/body-like fields.

Draft creation, draft sending, and approved-sender changes require explicit approval. In Openbase
Coder, approve the generated request in the approvals dashboard and rerun the same command. For
manual local testing outside that dashboard, rerun the reviewed command with `--approved-by-user`.

## Skill Install

```bash
# List available skills
npx skills add montaguegabe/gmail-cli-skill --list

# Install the included skill
npx skills add montaguegabe/gmail-cli-skill --skill gmail-cli
```

Optional flags:

- `-g` to install globally
- `-a claude-code` (or other agent names) to target specific agents

## Included Skills

- `gmail-cli` - Use the local Gmail CLI for safe Gmail search, reading, approved-sender management, draft creation, and draft sending with Openbase Coder approval gates.

## Configuration

Default files live under `~/.config/gmail-cli`:

- `credentials.json`: Google OAuth desktop client JSON
- `token.json`: default account token
- `accounts/<account>/token.json`: named account tokens
- `approved_senders.json`: default account body-readable senders

The CLI also honors legacy `GMAIL_MCP_*` environment variables while preferring `GMAIL_CLI_*`.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

OAuth credentials, tokens, approved-sender files, virtual environments, caches, and local env files
are ignored by git.
