# Security Policy

## Supported versions

Security fixes are provided for the latest release on the default branch.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for sensitive security reports.

Instead, contact the maintainers privately with:

- a description of the issue
- steps to reproduce
- impact assessment
- suggested fix (if any)

We will acknowledge receipt and work on a fix as quickly as possible.

## Design principles

zab is a **local-first** tool:

- core workflows should not require sending workspace data to third parties
- the dashboard and CLI must not echo raw secret values
- generated indexes (`state.yaml`, scan snapshots) may contain paths and metadata — treat them as sensitive on shared machines
- optional integrations (Composio, Postgres memory, GCP workstation, Evolution API, etc.) use credentials from your local environment

## Before publishing a fork

Run the repository pre-publish check:

```bash
./scripts/publish-check.sh
```

Install the local pre-push hook once per clone:

```bash
git config core.hooksPath .githooks
```

The same guard is available through zab:

```bash
zab security publish-check --mode tracked
```

Also recommended:

```bash
brew install gitleaks
gitleaks detect --source . --redact
```

Never commit:

- `.env` files with real credentials
- API keys, bot tokens, database URLs with passwords
- personal session dumps, screenshots with private infrastructure
- absolute home paths tied to a specific operator

## Dependency security

Security scan presets are available from the dashboard and via jobs:

- `security_osv_zab`
- `security_npm_audit_zab_ui`
- `security_gitleaks_zab`

Install tools locally (`osv-scanner`, `gitleaks`, Node.js) before running those presets.
