# zab — Brand & storytelling

## One-liner (hero)

> **One command center for your entire AI stack — skills · MCP · scan — local-first.**

French:

> **Un seul poste de pilotage pour toute ta stack IA — skills · MCP · scan — 100 % local.**

## Tagline

`skills · MCP · scan`

Short descriptor under the logo in the dashboard and README.

## Positioning (30 seconds)

You run **Cursor**, **Claude Code**, **Codex**, **Kimi**, **Hermes**, a dozen **MCP servers**, skills repos, env files, and cloud crons. Nothing talks to each other. You lose context every time you switch tools.

**zab does not replace your agents.** It is the **souverain aggregation layer** on your machine: it scans what you already have, rebuilds a regenerable index, and exposes it through a CLI, a dashboard, and a read-only MCP server so any agent can bootstrap safely.

## Story arc

| Act | Problem | zab answer |
|-----|---------|------------|
| **1 — Scatter** | Skills in `~/.hermes`, `~/.claude`, projects, org folders | One registry: adopt, ignore, sync, broadcast |
| **2 — Blind spots** | Is Gmail connected? Is CodexBar saturated? Which MCP is broken? | Connectors + system check + env presence (never raw secrets) |
| **3 — Handoff** | New session = re-explaining the workspace | `zab agent bootstrap`, `search`, `inspect`, `context-pack`, `mcp serve` |
| **4 — Memory** | Conversations trapped in each IDE | Optional Postgres archive + MemPalace mining |
| **5 — Ops** | Hermes crons here, GCP Scheduler there | Unified crons registry + comparable execution logs |

## Voice & tone

- **Direct**, developer-to-developer — no marketing fluff
- **Local-first** — offline-capable, no phone-home for core flows
- **Sovereign** — your paths, your keys, your machine
- **Agent-ready** — JSON outputs, stable CLI contract, MCP read-only by default

## Visual identity

| Element | Value |
|---------|--------|
| Mark | Rounded square `zinc-900` (#18181b), three white sparkle glyphs (hub / constellation) |
| Wordmark | `zab` lowercase, semibold, tight tracking |
| UI reference | Dashboard sidebar — see [screenshots](assets/screenshots/) |
| Assets | `docs/assets/zab-icon.svg`, `docs/assets/zab-logo.png`, `zab-ui/public/favicon.svg` |

## Elevator pitches

**OSS README:** Local-first CLI + dashboard that unifies skills, MCP, projects, connectors, and agent memory into one searchable control plane.

**To a teammate:** "Run `zab dashboard`, sync once, and stop grep-ing twelve config files before every agent session."

**To an agent:** "`zab agent bootstrap --json` then `search` / `inspect` — never echo secrets, treat `state.yaml` as cache."
