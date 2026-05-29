# zab

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)

> **zab** is a local-first CLI and dashboard that unifies your AI workspace — skills, MCP servers, projects, connectors, and agent memory — into one searchable, agent-ready control plane.

## Why zab

If you run multiple AI coding tools (Cursor, Claude Code, Codex, Kimi, Hermes, …), your setup quickly fragments across skills folders, MCP configs, IDE settings, env files, and project roots.

**zab does not replace those tools.** It acts as a sovereign aggregation layer on your machine:

- scans and indexes what you already have
- exposes it through a CLI, a web dashboard, and a read-only MCP server
- helps coding agents bootstrap with structured local context

Your data stays local under XDG paths (`~/.config/zab`, `~/.local/share/zab`).

## Vision

**zab** is the local orchestrator for developers who run parallel AI workflows. Instead of reinventing agents or skills, it makes your existing toolchain coherent: discoverable, inspectable, and safe to hand off to any MCP-compatible client.

In practice, zab helps you:

- **Unify** scattered AI tooling into one regenerable local index
- **Bootstrap agents** with `agent bootstrap`, `search`, `inspect`, `context-pack`, and `mcp serve`
- **Stay local-first** with offline-capable caches and no cloud dependency for core workflows
- **Operate safely** with env tracking, security scans, and no raw secret echo
- **Bridge ecosystems** via skills broadcast, task aggregation, and optional Postgres memory

## Features

- Local index and full-text search across skills, MCP, projects, connectors, models
- FastAPI backend + React dashboard
- Agent bootstrap workflow for Claude Code, Codex, Cursor, and MCP clients
- Skills registry, broadcast, and cross-CLI sync helpers
- Security tab with OSV, npm audit, gitleaks presets
- Optional Postgres memory and conversation archive (`ZAB_MEMORY_DATABASE_URL`)
- Optional Composio connector aggregation, GCP workstation helpers, cron views

## Stack & external tools

zab is a thin orchestration layer: most capabilities come from **local CLIs and config files** on your machine, not from bundled SDKs.

### Python dependencies (core)

| Package | Role |
|---------|------|
| [Typer](https://typer.tiangolo.com/) | CLI |
| [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) | Dashboard API |
| [Pydantic](https://docs.pydantic.dev/) | Request/response models |
| [httpx](https://www.python-httpx.org/) | HTTP probes (proxies, Composio REST) |
| [google-auth](https://googleapis.dev/python/google-auth/) | Vertex OpenAI-compatible proxy (SA token refresh) |
| [PyYAML](https://pyyaml.org/) | `config.yaml`, `state.yaml`, Agentpipe |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | Load skills / zab `.env` at startup |
| [psycopg](https://www.psycopg.org/) *(optional `memory` extra)* | Postgres memory & conversation archive |

### External CLIs & ecosystems (optional, detected at runtime)

| Tool | Role in zab |
|------|-------------|
| **MemPalace** (`mempalace`, `mempalace-mcp`) | Local memory palace, MCP snippet install, batch mining of agent transcripts (`uv tool install mempalace`) |
| **CodexBar** (`codexbar`, `~/.codexbar/config.json`) | Provider quotas, usage probes, fusion with Agentpipe in « Modèles & agents » |
| **Agentpipe** (`~/.agentpipe.yaml`) | Declarative routing between coding agents (Claude, Codex, Kimi, Cursor, …) |
| **Hermes Agent** (`~/.hermes/`) | Local crons, skills `external_dirs`, gateway deploy, model sync targets |
| **[Composio](https://composio.dev/)** (`composio` CLI) | Toolkit connectors (Gmail, Firecrawl, …) aggregated in the dashboard |
| **[gog (gogcli)](https://github.com/steipete/gogcli)** | Gmail / Google Workspace for communication channels setup |
| **LiteLLM / OpenRouter** | Model proxies probed via `local-tools.yaml` |
| **GCP** (`gcloud`) | Cloud Scheduler & Cloud Run crons, workstation sync, Stackdriver log reads |
| **Obsidian** | Vault list/read/search and quick-capture from agent context tools |
| **[Open WebUI](https://github.com/open-webui/open-webui)** | `flowmetrik-openwebui/` — bridge to Hermes profiles (compose jobs in dashboard) |
| **Security scanners** | OSV Scanner, `npm audit`, Gitleaks, `pip audit` (preset jobs, no secret echo) |
| **PM / Git** | `gh`, GitLab / Linear / Notion via `task_sources` in config |
| **Coding agents** | Cursor, Claude Code, Codex, Kimi, Gemini CLI — indexed as code-tools, skills broadcast targets |

Install only what you use; `zab doctor` and the dashboard **System check** tab report presence without failing the whole app.

## Roadmap — upcoming integrations

These are **planned or in progress** (see `vision.md`, `docs/`, `.hermes/plans/`). Nothing here is required for the core local-first workflow.

| Area | Planned work |
|------|----------------|
| **Skills broadcast** | MCP zab for **Gemini CLI** and **Antigravity**; per-org exclusion per CLI; broadcast status + manual trigger in the dashboard UI |
| **Composio** | Developer-project workflow (`composio dev init`), REST multi-account routing, local audit log, richer `zab composio hint` per connector (e.g. Gmail, Firecrawl) |
| **Crons** | More schedulers in the same registry model: **GitHub Actions**, **Vercel Cron**, other cloud/local runners |
| **Hermes ↔ zab** | Models discovery sync to Hermes config (optional future `--prune` for stale models) |
| **Agentic projects** | Deeper GitLab orchestration (ticket → agent run → CI/MR evidence → merge), notifications |
| **Channels** | End-to-end flows (email → Obsidian task, Evolution API WhatsApp) hardened in UI and API |
| **Memory** | Stronger MemPalace ↔ Postgres alignment, conversation archive UX in dashboard |

Contributions welcome on any row — open an issue or PR with the area tag.

## Quickstart (5 minutes)

```bash
git clone https://github.com/YOUR_ORG/zab.git
cd zab
uv sync

mkdir -p ~/.config/zab
cp config.example.yaml ~/.config/zab/config.yaml
# Edit skills_roots to point at your skills repository

uv run zab doctor
uv run zab sync --json
uv run zab agent bootstrap --json
uv run zab dashboard --no-open
```

- API: `http://127.0.0.1:8742/api/health`
- Full dashboard UI: build the SPA once (see below), then open `http://127.0.0.1:8742/`

## Installation

### Requirements

- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) (recommended) or pip/pipx
- Node.js **20+** (only for building the dashboard UI)

### Option A — Developer install (recommended)

```bash
git clone https://github.com/YOUR_ORG/zab.git
cd zab
uv sync
./scripts/install-zab-shell.sh   # optional shell wrapper
```

### Option B — pip / pipx (CLI + API)

```bash
pipx install .
# or: pip install .
export ZAB_SKILLS_ROOT=~/skills
zab doctor
zab dashboard --no-open
```

The wheel ships the Python package only. For the dashboard UI, either:

1. build from source and set `ZAB_UI_DIST`, or
2. run `./scripts/build-ui-for-wheel.sh` before packaging to embed `zab/ui_dist`

```bash
cd zab-ui && npm ci && npm run build && cd ..
export ZAB_UI_DIST="$PWD/zab-ui/dist"
uv run zab dashboard
```

## Configuration

zab resolves your skills root in this order:

1. `ZAB_SKILLS_ROOT` environment variable
2. `skills_roots` / `skills_root` in `~/.config/zab/config.yaml`
3. `ZAB_INVOCATION_CWD` (when using the shell wrapper)
4. current working directory

Copy [`config.example.yaml`](config.example.yaml) to `~/.config/zab/config.yaml` and adjust paths.

At startup, the API loads `$SKILLS_ROOT/.env` and `~/.config/zab/.env` without overriding variables already set in your shell.

### Optional memory (Postgres)

```bash
uv sync --extra memory
```

Set in `~/.config/zab/.env` or your skills `.env`:

```bash
ZAB_MEMORY_DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/zab_memory
```

Legacy alias `MEHDI_MEMORY_DATABASE_URL` is still supported.

## CLI overview

| Command | Description |
|---------|-------------|
| `zab doctor` | Check toolchain and optional config |
| `zab sync` | Rebuild local index (`~/.local/share/zab/state.yaml`) |
| `zab dashboard` | Start API + SPA on port 8742 |
| `zab features --json` | List capabilities, commands, and API routes |
| `zab agent bootstrap --json` | Recommended agent entrypoint |
| `zab search QUERY --json` | Cross-index search |
| `zab inspect SECTION KEY --json` | Inspect one indexed item |
| `zab context-pack --stdout` | Export a Markdown context pack |
| `zab mcp serve` | Read-only MCP stdio server for agents |
| `zab security status --json` | Local security status without raw secrets |

Run `zab features` for the full command catalog.

## For coding agents

Recommended flow:

```bash
zab agent bootstrap --json
zab search "postgres memory" --json
zab inspect skills my-skill --json
zab agent handoff --project my-app --json
zab context-pack --query "deployment" --stdout
```

For MCP clients, run `zab mcp serve` and use the read-only tools (`search`, `inspect`).

Rules: use JSON outputs, never print raw secrets, treat `state.yaml` as generated cache and `config.yaml` as user intent.

## Security model

- Core workflows are **local-only**; zab does not phone home
- The dashboard tracks env var **presence**, not values
- Security scans run via local jobs (OSV, npm audit, gitleaks)
- Before publishing forks, run `./scripts/publish-check.sh`

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## Development

```bash
uv run pytest zab/tests -v
cd zab-ui && npm run test:e2e
./scripts/test-zab-cli-real.sh
./scripts/publish-check.sh
```

## Documentation

- [Skills broadcast](docs/skills-broadcast.md)
- [Skills registry migration](docs/skills-registry-migration.md)
- [Composio integration notes](docs/composio-integration.md)
- [Agentic project orchestration](docs/AGENTIC-PROJECT-ORCHESTRATION.md)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
