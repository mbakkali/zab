"""Catalogue des capacités zab, lisible par humains et agents."""

from __future__ import annotations

from typing import Any


FEATURES: list[dict[str, Any]] = [
    {
        "id": "configuration",
        "category": "foundation",
        "summary": "Résout chemins, config YAML, local-tools et racines skills/projets.",
        "cli": ["zab config", "zab config --paths"],
        "api": ["/api/overview", "/api/config/files"],
        "files": ["~/.config/zab/config.yaml"],
    },
    {
        "id": "sync-state",
        "category": "foundation",
        "summary": "Reconstruit l'index Postgres régénérable de l'univers IA.",
        "cli": ["zab sync", "zab sync --json", "zab agent bootstrap --json"],
        "api": ["POST /api/sync", "GET /api/state", "GET /api/state/full"],
        "files": ["Postgres schema zab_core", "~/.config/zab/overrides.yaml"],
    },
    {
        "id": "skills",
        "category": "context",
        "summary": "Découvre les SKILL.md, leurs tags et dépendances frontmatter.",
        "cli": ["zab skill list --json", "zab inventory skills --json", "zab inspect skills <id> --json"],
        "api": ["GET /api/skills", "GET /api/skills/by-id/{skill_id}", "GET|PUT /api/skills/file"],
        "files": ["$ZAB_SKILLS_ROOT/**/SKILL.md", "projects_roots/**/SKILL.md"],
    },
    {
        "id": "connectors",
        "category": "context",
        "summary": "Agrège les connecteurs logiques et leurs formes MCP/API.",
        "cli": ["zab inventory connectors --json", "zab inspect connectors <slug> --json", "zab add mcp", "zab add api"],
        "api": ["GET /api/connectors", "GET /api/connectors/{slug}"],
        "files": ["configs/cursor-mcp.json", "configs/claude-desktop-mcp.json", "local-tools.yaml"],
    },
    {
        "id": "tools-catalog",
        "category": "context",
        "summary": "Catalogue les capacités actionnables Zab: recherche, inspect, validation et checks read-only.",
        "cli": ["zab tools list --json", "zab tools search <query> --json", "zab tools inspect <tool-id> --json"],
        "api": ["GET /api/tools/catalog", "GET /api/tools/{tool_id}", "GET /api/tools/validate"],
        "files": ["~/.config/zab/tools.yaml"],
    },
    {
        "id": "code-tools",
        "category": "context",
        "summary": "Indexe agents et outils de code locaux: Claude Code, Codex, Cursor, Gemini, Kimi, etc.",
        "cli": ["zab inventory code-tools --json", "zab inspect code-tools claude --json"],
        "api": ["GET /api/code-tools", "GET /api/code-tools/{tool_id}"],
        "files": ["~/.agentpipe.yaml", "~/.codexbar/config.json", "$PATH"],
    },
    {
        "id": "models",
        "category": "context",
        "summary": "Expose modèles/endpoints découverts via scan Agentpipe/CodexBar et proxies.",
        "cli": ["zab scan --persist", "zab inventory models --json"],
        "api": ["GET /api/models", "GET /api/config/models-discovery", "GET /api/tools/probe"],
        "files": ["~/.config/zab/config.yaml#models_discovery", "local-tools.yaml#proxies"],
    },
    {
        "id": "projects",
        "category": "workspace",
        "summary": "Liste les projets sous projects_roots avec skills, organisation inférée et métadonnées Git.",
        "cli": ["zab projects list", "zab projects list --json"],
        "api": ["GET /api/overview"],
        "files": ["~/.config/zab/config.yaml#projects_roots"],
    },
    {
        "id": "tasks",
        "category": "workspace",
        "summary": "Agrège tickets GitLab, Linear et Notion configurés dans task_sources.",
        "cli": ["zab pm-env sync"],
        "api": ["GET /api/tasks/inbox", "POST /api/tasks/pm-env/sync"],
        "files": ["~/.config/zab/config.yaml#task_sources", "~/.config/zab/.env"],
    },
    {
        "id": "memory",
        "category": "memory",
        "summary": "Vérifie MemPalace/Postgres et expose documents/chunks en lecture.",
        "cli": [
            "zab doctor",
            "zab mempalace doctor",
            "zab mempalace doctor --json",
            "zab mempalace mcp-json",
            "zab mempalace mcp-install -t cursor",
            "zab memory sync-agents --json",
            "zab memory search <query> --json",
            "zab memory show <document-id> --json",
            "zab scan --json",
        ],
        "api": [
            "GET /api/memory/status",
            "GET /api/memory/search?q=",
            "GET /api/memory/document/{document_id}",
            "GET /api/memory/documents",
            "GET /api/memory/chunks",
        ],
        "files": ["MEHDI_MEMORY_DATABASE_URL", "$ZAB_SKILLS_ROOT/.env"],
    },
    {
        "id": "context-pack",
        "category": "agent",
        "summary": "Génère un Markdown de contexte filtrable par org/projet pour agents web ou CLI.",
        "cli": ["zab context-pack --org flowmetrik", "zab context-pack --query billing --stdout", "zab agent handoff --project my-project --json"],
        "api": ["POST /api/context-pack"],
        "files": ["~/.local/share/zab/context-pack/*.md"],
    },
    {
        "id": "agent-contract",
        "category": "agent",
        "summary": "Point d'entrée stable pour Claude Code, Codex et MCP: bootstrap, search, inspect, handoff.",
        "cli": ["zab agent bootstrap --json", "zab search <query> --json", "zab agent handoff --project <project> --json", "zab mcp serve"],
        "api": ["GET /api/agent/bootstrap", "GET /api/search", "POST /api/agent/handoff"],
        "files": ["~/.local/share/zab/audit.log"],
    },
    {
        "id": "dashboard",
        "category": "ui",
        "summary": "Dashboard FastAPI + React pour explorer l'inventaire et lancer jobs/probes.",
        "cli": ["zab dashboard --no-open", "zab dashboard --dev"],
        "api": ["/api/*"],
        "files": ["zab-ui/dist", "ZAB_UI_DIST"],
    },
    {
        "id": "testing",
        "category": "quality",
        "summary": "CLI/API/UI smoke test loops for local validation.",
        "cli": ["./scripts/test-zab-cli-real.sh", "./scripts/test-zab-cli-scenarios.sh", "cd zab-ui && npm run test:e2e"],
        "api": ["/api/health"],
        "files": ["scripts/", "zab-ui/e2e/"],
    },
]


def catalog() -> dict[str, Any]:
    return {
        "product": "zab",
        "positioning": "Postgres-backed AI context command center",
        "features": FEATURES,
    }


def agent_guide() -> dict[str, Any]:
    return {
        "purpose": "Let Claude Code, Codex or another agent discover local context, skills, connectors and safe commands without reading the whole workspace first.",
        "bootstrap_commands": [
            "zab agent bootstrap --json",
            "zab agent skills --json",
            "zab tools list --json",
            "zab features --json",
            "zab mempalace doctor --json",
            "zab memory search <topic> --json",
            "zab inventory skills --json --limit 50",
            "zab inventory connectors --json --limit 50",
            "zab inventory code-tools --json",
        ],
        "common_workflows": [
            {
                "goal": "Search prior agent memory before making architectural decisions",
                "commands": [
                    "zab memory sync-agents --json",
                    "zab memory search <topic> --wing <project-or-org> --json",
                    "zab memory show <document-id> --json",
                ],
            },
            {
                "goal": "Find relevant skills before acting",
                "commands": [
                    "zab agent skills --json",
                    "zab search <topic> --section skills --json",
                    "zab inspect skills <skill-id> --json",
                ],
            },
            {
                "goal": "Discover actionable tools before choosing an implementation",
                "commands": [
                    "zab tools list --json",
                    "zab tools search <topic> --json",
                    "zab tools inspect <tool-id> --json",
                ],
            },
            {
                "goal": "Discover available connectors and required env vars",
                "commands": ["zab inventory connectors --json", "zab inspect connectors <slug> --json"],
            },
            {
                "goal": "Prepare context for a web agent",
                "commands": ["zab context-pack --query <topic> --stdout", "zab agent handoff --project <project> --json"],
            },
            {
                "goal": "Wire MemPalace MCP into Cursor or Claude Desktop (stdio via skills JSON)",
                "commands": [
                    "zab mempalace mcp-install -t cursor --force",
                    "zab mempalace mcp-json -t desktop",
                    "zab mempalace mcp-install -t desktop --name mempalace",
                ],
            },
            {
                "goal": "Use MemPalace from Claude Code (official CLI, not cursor-mcp.json)",
                "commands": [
                    "mempalace mcp",
                    "# then follow printed line, e.g. claude mcp add mempalace -- mempalace-mcp",
                ],
            },
            {
                "goal": "Understand local agent/model tooling",
                "commands": ["zab inventory code-tools --json", "zab scan --persist --json"],
            },
        ],
        "safety_rules": [
            "Prefer JSON commands for automation.",
            "Run `zab sync --json` before relying on inventory.",
            "Do not read or print raw secret values; use security/env API or masked dashboard views.",
            "Treat Postgres zab_core as generated state and config.yaml/overrides.yaml as user-controlled intent.",
        ],
    }


def agent_guide_markdown() -> str:
    guide = agent_guide()
    lines = [
        "# zab Agent Guide",
        "",
        str(guide["purpose"]),
        "",
        "## Bootstrap",
        "",
    ]
    lines.extend(f"- `{cmd}`" for cmd in guide["bootstrap_commands"])
    lines.extend(["", "## Workflows", ""])
    for wf in guide["common_workflows"]:
        lines.append(f"### {wf['goal']}")
        lines.append("")
        lines.extend(f"- `{cmd}`" for cmd in wf["commands"])
        lines.append("")
    lines.extend(["## Safety", ""])
    lines.extend(f"- {rule}" for rule in guide["safety_rules"])
    return "\n".join(lines).rstrip() + "\n"
