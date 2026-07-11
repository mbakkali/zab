"""Noms de variables d'environnement suivies par l'onglet Sécurité (valeurs masquées)."""

from __future__ import annotations

# Connecteurs MCP / gateway
CONNECTOR_VARS: tuple[str, ...] = (
    "QONTO_API_KEY",
    "QONTO_ORGANIZATION_SLUG",
    "QONTO_ID",
    "QONTO_SECRET_KEY",
    "PENNYLANE_API_KEY",
    "EVOLUTION_API_URL",
    "EVOLUTION_API_KEY",
    "EVOLUTION_INSTANCE",
    "EVOLUTION_NOTIFY_NUMBER",
    "MEHDI_MEMORY_DATABASE_URL",
    "FLOWMETRIK_MCP_ID_TOKEN",
    "MCP_URL",
    "MCP_USE_GCLOUD_ID_TOKEN",
    "FMETRIK_SKILLS_ROOT",
    "MCP_TRANSPORT",
    "COMPOSIO_MCP",
    "COMPOSIO_X_CONSUMER_API_KEY",
    "COMPOSIO_API_KEY",
)

# Google / contexte agent
GOOGLE_VARS: tuple[str, ...] = (
    "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
)

# Proxies LLM
LLM_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "LITELLM_MASTER_KEY",
)

# Dashboard « Tâches (multi-outils) » — tokens lus depuis le processus ou skills/.env
PM_VARS: tuple[str, ...] = (
    "GITLAB_TOKEN",
    "LINEAR_API_KEY",
    "NOTION_TOKEN",
)

ALL_TRACKED: tuple[str, ...] = tuple(dict.fromkeys(CONNECTOR_VARS + GOOGLE_VARS + LLM_VARS + PM_VARS))

SECRET_ALIASES: dict[str, tuple[str, ...]] = {
    # Legacy bridge naming used by flowmetrik-cowork/compta/bridge.
    "QONTO_API_KEY": ("QONTO_SECRET_KEY",),
    "QONTO_ORGANIZATION_SLUG": ("QONTO_ID",),
    # Common project-management env names found in local/project .env files.
    "GITLAB_TOKEN": ("GITLAB_PROJECT_MANAGEMENT_TOKEN", "GITLAB_ISSUE_BOT_TOKEN"),
    "NOTION_TOKEN": ("NOTION_API_KEY", "NOTION_NOTION_SECRET", "NOTION_NOTION_SECRET_DEV"),
    # Composio exposes multiple key names depending on CLI/MCP setup.
    "COMPOSIO_API_KEY": ("COMPOSIO_X_CONSUMER_API_KEY",),
}

SECRET_GROUPS: dict[str, tuple[str, ...]] = {
    "connectors": CONNECTOR_VARS,
    "project_management": PM_VARS,
    "google": GOOGLE_VARS,
    "memory": ("MEHDI_MEMORY_DATABASE_URL",),
    "llm": LLM_VARS,
}
