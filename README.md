# Gmail, Outlook, and Apple Mail CLI Skill

A local email command line tool and agent skill with approval gates for drafts, sending, and approved-sender changes. Existing `gmail-cli` commands continue to use Gmail. Use `outlook-cli` for Microsoft 365 work/school accounts and Outlook.com, or select Outlook explicitly with `gmail-cli --provider outlook`.

Search results expose metadata without snippets or message bodies. Body reads require an approved sender. Each provider and named account has its own credentials and sender permissions; Gmail permissions do not carry over to Outlook.

## Install

```bash
uv sync --extra dev
uv run gmail-cli --help
uv run outlook-cli --help

# Install all three commands locally from this checkout:
uv tool install --editable .
```

## Apple Mail on macOS

Use `apple-mail-cli` (or `gmail-cli --provider apple-mail`) for an account already signed in and syncing in Apple's Mail app, including Exchange accounts. This uses Mail's local scripting interface, not Microsoft Graph, a browser, or an impersonated OAuth client. Mail owns the credentials. macOS may ask you to allow the calling terminal/app to control Mail under Privacy & Security → Automation. Complete account sign-in and any organization consent in Mail yourself.

```bash
apple-mail-cli auth accounts
apple-mail-cli auth login --account school --username user@school.edu
apple-mail-cli folders --account school
apple-mail-cli search '' --account school --max-results 10
apple-mail-cli search 'from:alice@example.com subject:"planning meeting"' --account school
apple-mail-cli message MESSAGE_ID --account school
apple-mail-cli message MESSAGE_ID --account school --include-body
```

Login binds the CLI alias to an exact enabled Mail account ID and email; it does not start OAuth or save tokens. Compose/send are off by default in the CLI. These are local safeguards, not restrictions on Mail's underlying Microsoft permissions. Add `--include-compose` and `--include-send` to `auth login` when needed; every write still uses the existing approval dashboard. Rebinding an alias to another Mail account is refused.

Search defaults to the mailbox named `Inbox`. Pass an opaque folder ID from `folders` with `--folder-id` to select another mailbox (including localized Inbox names). Queries match only sender/subject metadata: `from:`, `subject:`, and plain text, with all terms required. Unsupported operators are rejected. Each page scans at most 250 locally available messages, so an empty result page can still have a continuation token. Reuse exactly the same query, folder, and result limit with `--page-token`. Results follow Mail's current order; changes during pagination can shift offsets. Results reflect Mail's local sync, not a guaranteed complete server search. Message IDs are local to this Mac and account; after moving a message or rebuilding Mail's database, search again.

Approved senders are separate from Gmail and Graph/Outlook. Use `apple-mail-cli approved-senders add --account school alice@example.com` and approve the dashboard request. Bodies are fetched only after checking the sender and rechecking the exact header in Mail. Configuration lives under `~/.config/gmail-cli/apple-mail` (override with `APPLE_MAIL_CLI_CONFIG_DIR`); the optional sender environment variable is `APPLE_MAIL_CLI_APPROVED_SENDERS`.

Draft commands use the same syntax as other providers. On Apple Mail, `draft-reply` takes the original **message ID**, because Mail does not expose stable conversation IDs. `thread` and `search --threads` are unavailable. Replies use Mail's native reply operation and quote the original message after the approved-sender check; quoted content over 50,000 characters requires explicitly disabling quoting. The original sender must be approved even for an unquoted native reply.

Only drafts created through this CLI can be sent through it, while their compose objects remain available in Mail. Opaque draft IDs bind a local manifest to the exact draft content, recipients, and sender. Changed or closed drafts must be reviewed/sent manually in Mail. A send attempt is recorded before invoking Mail, and cannot be automatically repeated after a timeout or failure. Acceptance is not delivery confirmation. Account bindings and draft manifests are owner-readable only and contain no OAuth tokens; draft manifests store content hashes rather than message bodies.

Apple Mail account discovery, folder listing, search, pagination, and metadata reads have been checked against a live account. Draft/reply/send safeguards have automated test coverage; writes require separate live validation with an approved draft. This provider does not implement calendar access.

## Gmail authentication

Create a Google Cloud OAuth desktop client with the Gmail API enabled and save its downloaded client JSON to `~/.config/gmail-cli/credentials.json`.

```bash
gmail-cli auth login --account default
gmail-cli auth login --account work --include-compose --include-send
gmail-cli auth accounts
```

The default is read-only. Request compose, modify, or send scopes only when needed.

## Outlook authentication

Register your own application in [Microsoft Entra](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app). Choose the account types you need: your organization, multiple organizations, or organizations plus personal Microsoft accounts. Under Authentication, add the **Mobile and desktop applications** platform with `http://localhost` as a redirect URI. Copy the Application (client) ID. This is a public desktop client: no client secret is used.

```bash
outlook-cli auth login --account school --client-id YOUR_APPLICATION_ID --username user@school.edu
outlook-cli auth accounts
outlook-cli auth paths --account school
```

Browser login uses MSAL. For a terminal without a browser, enable **Allow public client flows** in the application registration and add `--device-code` to the command. Follow the Microsoft sign-in instructions printed to stderr; stdout remains JSON. A school or employer may require an administrator to approve the app or its delegated permissions. The CLI cannot bypass that policy.

Default permissions are `User.Read` and `Mail.Read`. `--include-compose` (or `--include-modify`) adds `Mail.ReadWrite`; `--include-send` adds `Mail.Send`. Microsoft does not offer a compose-only delegated permission. Token refreshes happen silently from the local cache; interactive sign-in happens only through `auth login`.

```bash
outlook-cli auth login --account school --include-compose
outlook-cli auth login --account school --include-compose --include-send
```

The application ID, tenant, and username are remembered for that named account. `OUTLOOK_CLI_CLIENT_ID` and `OUTLOOK_CLI_TENANT` can supply initial defaults; `--tenant` accepts a tenant ID/domain or `common`. `--username` verifies the signed-in identity before saving. An existing account name cannot be rebound to a different Microsoft identity: choose another name to avoid transferring sender permissions. Microsoft cache files are stored with owner-only permissions; refreshes are serialized on macOS/Linux.

## Search and read

```bash
gmail-cli search 'from:alice@example.com newer_than:30d' --account work
outlook-cli search 'from:alice@example.com' --account school
outlook-cli search 'subject:meeting' --account school --max-results 10
outlook-cli search '' --account school --folder-id inbox
outlook-cli search 'from:alice@example.com' --account school --threads
outlook-cli folders --account school
outlook-cli message MESSAGE_ID --account school --include-body
outlook-cli thread CONVERSATION_ID --account school --max-body-chars 8000
```

Outlook uses [Microsoft Graph mail search](https://learn.microsoft.com/en-us/graph/search-query-parameter), not Gmail search operators. For example, `newer_than:` and Gmail label names are not portable. An empty query lists messages. A single `--folder-id` accepts a returned folder ID or a well-known folder such as `inbox`, `sentitems`, or `drafts`. `labels` aliases folder listing on Outlook, and `--label-id` aliases `--folder-id`.

Search returns `next_page_token` when another page is available. Pass it back with the same query, folder, and result limit using `--page-token`. Outlook validates continuation URLs against the original resource and metadata projection before forwarding them. Graph mail search returns at most 1,000 matches; use narrower searches for larger result sets. Thread search deduplicates conversation IDs within each message page, so a conversation can recur on a later page. `thread` reads the full conversation across pages, applying sender approval to each message. Folder listing includes nested folders.

## Approved senders

```bash
outlook-cli approved-senders list --account school
outlook-cli approved-senders add --account school alice@example.com
outlook-cli approved-senders remove --account school alice@example.com
```

Add/remove commands return `approval_required` and exit 2 before writing configuration. Approve the generated request manually in the Openbase Coder approvals dashboard, then rerun the exact command. Sender matching uses email addresses, never display names. To read your own sent messages, approve your own sender address as well.

## Draft and send

```bash
outlook-cli draft-new --account school --to alice@example.com --subject 'Hello' --body-file /tmp/body.txt
outlook-cli draft-reply CONVERSATION_ID --account school --body-file /tmp/reply.txt
outlook-cli draft-reply CONVERSATION_ID --account school --reply-all --body-file /tmp/reply.txt
outlook-cli send-draft DRAFT_ID --account school
```

These mutations use the same dashboard approval gates as Gmail. Approvals distinguish the provider, account, and full draft-body hash. The `--approved-by-user` escape hatch is for explicitly authorized manual bypasses; agents must not infer permission to use it.

Outlook reply drafts use Graph's native [createReply/createReplyAll](https://learn.microsoft.com/en-us/graph/api/message-createreply?view=graph-rest-1.0) operations, preserving conversation membership and native reply recipients. They reply to the latest non-draft message and include its visible text trail by default. The original sender must be approved before the CLI fetches that trail. Use `--no-quoted-history` only when intentionally omitting it. Replies return the conversation ID and `quoted_history_included` so the result can be checked.

`send-draft` verifies the message is still a draft. Microsoft returns an acceptance response, not delivery confirmation, reported as `send_status: "accepted"`. Writes are not automatically retried. After an interrupted/timed-out write, inspect Drafts or Sent before retrying to avoid duplicates.

## Configuration

Gmail keeps its existing configuration under `~/.config/gmail-cli`, including `credentials.json`, `token.json`, named `accounts/<account>/token.json`, and account-specific `approved_senders.json`. Existing `GMAIL_CLI_*` variables and legacy `GMAIL_MCP_*` fallbacks remain supported.

Outlook uses `~/.config/gmail-cli/outlook`, or `OUTLOOK_CLI_CONFIG_DIR`. Default and named account directories contain `token.json` (MSAL cache plus account metadata) and `approved_senders.json`. `OUTLOOK_CLI_APPROVED_SENDERS` adds explicit comma-separated addresses across Outlook accounts. Gmail sender environment variables are ignored by Outlook. Keep all tokens, OAuth files, and sender configurations out of git.

## Skill install

```bash
npx skills add openbase-community/gmail-cli-skill --skill gmail-cli
```

The `gmail-cli` skill covers both providers. The package and existing command name remain compatible with previous installations.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Tests mock Google/Microsoft services and sign-in. Live tenant consent and API behavior require a separately authenticated account. The CLI supports email operations; it does not add Outlook calendar commands.
