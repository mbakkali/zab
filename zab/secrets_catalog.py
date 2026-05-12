"""Noms de variables d'environnement suivies par l'onglet Sécurité (valeurs masquées)."""

from __future__ import annotations

# Connecteurs MCP / gateway
CONNECTOR_VARS: tuple[str, ...] = (
    "QONTO_API_KEY",
    "QONTO_ORGANIZATION_SLUG",
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
