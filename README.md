# Gmail CLI Skill

Skills repository for Gmail CLI Skill.

## Install with `vercel-labs/skills`

```bash
# List available skills
npx skills add gabemontague/gmail-cli-skill --list

# Install the included skill
npx skills add gabemontague/gmail-cli-skill --skill gmail-cli
```

Optional flags:

- `-g` to install globally
- `-a claude-code` (or other agent names) to target specific agents

## Included Skills

- `gmail-cli` - Use the local Gmail CLI for safe Gmail search, reading, approved-sender management, draft creation, and draft sending with Openbase Coder approval gates.
