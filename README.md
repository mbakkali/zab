<p align="center">
  <img src="docs/assets/zab-logo.png" alt="zab logo" width="120" />
</p>

<h1 align="center">zab</h1>

<p align="center">
  <strong>One command center for your entire AI stack — skills · MCP · scan — Postgres-backed.</strong>
</p>

<p align="center">
  <em>Un seul poste de pilotage pour toute ta stack IA — skills · MCP · scan — mémoire Postgres.</em>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-green.svg" alt="License: Apache-2.0"></a>
</p>

<p align="center">
  <code>skills · MCP · scan</code>
</p>

---

## The story

You run **Cursor**, **Claude Code**, **Codex**, **Kimi**, **Hermes**, a pile of **MCP servers**, skills repos, `.env` files, and cloud crons. Each tool is great on its own — but nothing shares a map of your setup.

**zab does not replace your agents.** It is the **sovereign aggregation layer** on your machine:

1. **Scan** what you already have (skills, MCP, connectors, CLIs, projects).
2. **Index** it into the canonical Postgres schema (`zab_core`).
3. **Operate** through a CLI, a web dashboard, and a read-only MCP server so any agent can bootstrap without guessing paths or leaking secrets.

User intent stays under XDG config paths (`~/.config/zab/config.yaml`, `overrides.yaml`). Generated state, registries, tasks, channels, crons, and search live in Postgres.

→ Full brand voice: [docs/BRAND.md](docs/BRAND.md)

## Dashboard

| Overview — Postgres-backed index at a glance | Organizations — skills grouped by org |
|:---:|:---:|
| ![Overview](docs/assets/screenshots/overview.png) | ![Organizations](docs/assets/screenshots/organizations.png) |

| Projects — per-repo skills & security jobs | Skills registry — adopt, sync, broadcast |
|:---:|:---:|
| ![Projects](docs/assets/screenshots/projects.png) | ![Skills](docs/assets/screenshots/skills.png) |

| Conversations — aggregate CLI histories | Configuration — guided `config.yaml` |
|:---:|:---:|
| ![Conversations](docs/assets/screenshots/conversations.png) | ![Configuration](docs/assets/screenshots/configuration-cli-watchlist.png) |

*Postgres (`ZAB_MEMORY_DATABASE_URL`) is required. Zab stores operational state in `zab_core`; memory/RAG tables remain focused on conversations and documents.*

## Why zab

If you run multiple AI coding tools, your setup fragments across skills folders, MCP configs, IDE settings, env files, and project roots.

**zab** makes your existing toolchain **coherent**: discoverable, inspectable, and safe to hand off to any MCP-compatible client.

- **Unify** scattered AI tooling into one regenerable Postgres-backed index
- **Bootstrap agents** with `agent bootstrap`, `search`, `inspect`, `context-pack`, and `mcp serve`
- **Keep user intent local** in editable config files while generated state lives in Postgres
- **Operate safely** with env tracking, security scans, and no raw secret echo
- **Bridge ecosystems** via skills broadcast, task aggregation, MemPalace, CodexBar, Composio, Hermes

## Features

- Postgres full-text search across skills, MCP, projects, connectors, models
- FastAPI backend + React dashboard
- Agent bootstrap workflow for Claude Code, Codex, Cursor, and MCP clients
- Skills registry, broadcast, and cross-CLI sync helpers
- Security tab with OSV, npm audit, gitleaks presets
- Required Postgres memory and conversation archive (`ZAB_MEMORY_DATABASE_URL`)
- Local daily conversation digest to Obsidian, with project/org attribution
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
| [PyYAML](https://pyyaml.org/) | `config.yaml`, `overrides.yaml`, Agentpipe |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | Load skills / zab `.env` at startup |
| [psycopg](https://www.psycopg.org/) | Canonical Postgres store, memory & conversation archive |

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

These are **planned or in progress** (see `vision.md`, `docs/`, `.hermes/plans/`). Nothing here is required for the core Postgres-backed workflow.

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
uv tool install --editable . --python "$(command -v python3.11)"
./scripts/install-zab-shell.sh   # optional shell wrapper
```

If you move the checkout or switch Python architectures, refresh the global CLI:

```bash
uv tool install --reinstall --editable . --python "$(command -v python3.11)"
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

### Required Postgres

```bash
uv sync --extra memory
```

Set in `~/.config/zab/.env` or your skills `.env`:

```bash
ZAB_MEMORY_DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/zab_memory
```

Legacy alias `MEHDI_MEMORY_DATABASE_URL` is still supported.

Create/migrate Zab’s operational schema, then import the previous local caches:

```bash
zab db migrate --json
zab db import-legacy --json
```

The import command reads the previous SQLite database (`~/.local/share/zab/zab.db`) and remaining JSON/YAML caches into Postgres. SQLite databases owned by external tools such as Hermes/Cursor may still be read as source data, but SQLite is no longer a Zab runtime fallback.

## CLI overview

| Command | Description |
|---------|-------------|
| `zab doctor` | Check toolchain and optional config |
| `zab sync` | Rebuild the Postgres-backed index (`zab_core`) |
| `zab dashboard` | Start API + SPA on port 8742 |
| `zab features --json` | List capabilities, commands, and API routes |
| `zab agent bootstrap --json` | Recommended agent entrypoint |
| `zab search QUERY --json` | Cross-index search |
| `zab inspect SECTION KEY --json` | Inspect one indexed item |
| `zab context-pack --stdout` | Export a Markdown context pack |
| `zab mcp serve` | Read-only MCP stdio server for agents |
| `zab security status --json` | Local security status without raw secrets |
| `zab conversations obsidian-daily --yesterday` | Write yesterday's local agent conversation digest to Obsidian |
| `zab vm status` / `zab vm cost` / `zab vm sync` | Remote dev VM: state, real spend and runtime hours, file sync |
| `zab vm serve` | Serve the token-protected control PWA (see below) |

Run `zab features` for the full command catalog.

## Remote dev VM

`zab vm` monitors a remote development VM configured under `remote_vm` in
`config.yaml`: Compute Engine state, running hours and real spend derived from
the resource-level billing export, live SSH connections, and per-session file
sync status. It renders on the dashboard's *Workstation* page.

### Control app (PWA)

`zab vm serve` exposes a deliberately narrow surface — status, start, and sync
actions, plus read-only cost data — as an installable mobile web app. There is
no remote stop action; shutdown stays local through `vmctl.sh stop`. It is a
**separate application from the dashboard**: publishing the full zab API would
hand anyone who gets past authentication the keys to the whole workspace.

```bash
zab vm token --show          # create the bearer token (0600 in the config dir)
zab vm serve                 # loopback by default; put a tunnel or VPN in front
zab vm link https://vm.example.com   # one-time pairing link for a phone
```

Properties worth knowing:

- every action is **asynchronous** — starting a VM outlives any HTTP timeout, so
  the request records a job and the client polls;
- one action at a time, so a double tap cannot launch two starts;
- the pairing token travels in the URL **fragment**, never reaching the server or
  a proxy log, and the page strips it from the address bar on first load;
- the app shell is cached by a service worker, API responses never are.

Never expose this port directly. Serve it behind a VPN (Tailscale, WireGuard) or
an authenticated tunnel; the token is a second line of defence, not the first.

Daily conversation digests are documented in
[docs/conversation-daily-obsidian.md](docs/conversation-daily-obsidian.md).

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

Rules: use JSON outputs, never print raw secrets, treat Postgres `zab_core` as generated state and `config.yaml` / `overrides.yaml` as user intent.

## Security model

- Core workflows are **local-only**; zab does not phone home
- The dashboard tracks env var **presence**, not values
- Security scans run via local jobs (OSV, npm audit, gitleaks)
- Before publishing forks, run `./scripts/publish-check.sh` or `zab security publish-check --mode tracked`
- To block risky pushes locally, run `git config core.hooksPath .githooks` once per clone

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## Development

```bash
uv run pytest zab/tests -v
cd zab-ui && npm run test:e2e
./scripts/test-zab-cli-real.sh
./scripts/publish-check.sh
```

## Documentation

- [Brand & storytelling](docs/BRAND.md)
- [Skills broadcast](docs/skills-broadcast.md)
- [Skills registry migration](docs/skills-registry-migration.md)
- [Composio integration notes](docs/composio-integration.md)
- [Agentic project orchestration](docs/AGENTIC-PROJECT-ORCHESTRATION.md)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
