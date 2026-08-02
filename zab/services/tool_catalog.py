"""Catalogue des outils actionnables de Zab.

Le catalogue reste séparé du catalogue de skills :
un *tool* décrit une capacité exploitable, ses implémentations techniques,
ses références de skills et sa posture de sécurité.
"""

from __future__ import annotations

import math
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.paths import config_dir, tools_catalog_config_path
from zab.services import communication_channels, connectors_aggregate, memory_db, obsidian_vault, tools_scan
from zab.services import connectors_check
from zab.services.composio_connectors import composio_cli_path
from zab.user_config import cli_watchlist_from_user_config, load_user_config

TOOLS_CATALOG_CONTRACT = "tools-catalog"
TOOLS_CATALOG_CONTRACT_VERSION = "1.0"
_SAFE_COMMAND_RISKY_TOKENS = (
    "rm -rf",
    "sudo ",
    "curl | sh",
    "wget | sh",
    " --write",
    " --delete",
    " --remove",
    " --force",
    " post ",
    " patch ",
    " put ",
    " delete ",
    " drop ",
    " truncate ",
)
_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    return [value]


def _string_list(value: Any) -> list[str]:
    out: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str):
            text = item.strip()
            if text and text not in out:
                out.append(text)
    return out


def _dict_list(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _dedupe(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in seq:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _titleize(value: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_\s]+", value.strip()) if part)


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, nested in value.items():
            lk = str(key).lower()
            if any(token in lk for token in ("secret", "token", "password")):
                continue
            out[str(key)] = _sanitize_payload(nested)
        return out
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {"_error": "yaml_invalid", "_path": str(path)}
    return raw if isinstance(raw, dict) else {"_error": "yaml_invalid", "_path": str(path)}


def _merged_cli_watchlist_names() -> list[str]:
    names: list[str] = []
    local_tools_path = config_dir() / "local-tools.yaml"
    local_doc = _read_yaml(local_tools_path)
    raw_local = local_doc.get("cli_watchlist") if isinstance(local_doc, dict) else None
    if isinstance(raw_local, list):
        for item in raw_local:
            name = str(item).strip()
            if name and name not in names:
                names.append(name)
    for item in cli_watchlist_from_user_config():
        name = item.strip()
        if name and name not in names:
            names.append(name)
    return names


def _normalize_impl(impl: dict[str, Any]) -> dict[str, Any]:
    out = dict(impl)
    out["id"] = str(out.get("id") or "").strip()
    out["kind"] = str(out.get("kind") or "").strip().lower()
    out["provider"] = str(out.get("provider") or "").strip()
    out["role"] = str(out.get("role") or "primary").strip().lower()
    out["priority"] = int(out.get("priority") or 50)
    out["command"] = str(out.get("command") or "").strip()
    out["coverage"] = str(out.get("coverage") or "unknown").strip().lower()
    if "smoke_command" in out and isinstance(out["smoke_command"], list):
        out["smoke_command"] = [str(x) for x in out["smoke_command"] if str(x).strip()]
    out["fallback_when"] = _string_list(out.get("fallback_when"))
    return _sanitize_payload(out)


def _merge_lists(base: list[Any], override: list[Any]) -> list[Any]:
    if not override:
        return list(base)
    if not base:
        return list(override)
    out: list[Any] = []
    seen: set[str] = set()
    for item in [*override, *base]:
        if isinstance(item, str):
            key = item.casefold()
        elif isinstance(item, dict):
            key = str(item.get("id") or item.get("key") or item.get("label") or item).casefold()
        else:
            key = str(item).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _merge_implementations(base: list[dict[str, Any]], override: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not override:
        return [_normalize_impl(item) for item in base]
    if not base:
        return [_normalize_impl(item) for item in override]
    by_id: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for item in base:
        normalized = _normalize_impl(item)
        key = normalized.get("id") or f"impl-{len(ordered)}"
        if key not in by_id:
            ordered.append(key)
        by_id[key] = normalized
    for item in override:
        normalized = _normalize_impl(item)
        key = normalized.get("id") or f"impl-{len(ordered)}"
        if key not in by_id:
            ordered.append(key)
            by_id[key] = normalized
            continue
        merged = dict(by_id[key])
        for field in ("kind", "provider", "role", "priority", "command", "coverage", "check", "smoke_command"):
            if field in normalized and normalized[field] not in (None, "", [], {}):
                merged[field] = normalized[field]
        if normalized.get("fallback_when"):
            merged["fallback_when"] = _merge_lists(_as_list(merged.get("fallback_when")), _as_list(normalized.get("fallback_when")))
        by_id[key] = _normalize_impl(merged)
    return [by_id[key] for key in ordered]


def _merge_tool(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for field in (
        "label",
        "kind",
        "coverage",
        "status",
        "safety",
        "notes",
        "probe",
        "primary_connector",
        "primary_channel",
        "primary_env_keys",
        "fallback_connector",
        "fallback_toolkit",
    ):
        if field in override and override[field] not in (None, "", [], {}):
            out[field] = _sanitize_payload(override[field])
    for field in ("keywords", "examples", "skill_refs", "commands", "origin_refs"):
        if field in override:
            out[field] = _merge_lists(_as_list(override.get(field)), _as_list(out.get(field)))
    if "implementations" in override:
        out["implementations"] = _merge_implementations(
            _dict_list(out.get("implementations")),
            _dict_list(override.get("implementations")),
        )
    if "aliases" in override:
        out["aliases"] = _merge_lists(_as_list(override.get("aliases")), _as_list(out.get("aliases")))
    return _sanitize_payload(out)


def _implementation_summary(impl: dict[str, Any] | None) -> str:
    if not impl:
        return "—"
    command = str(impl.get("command") or "").strip()
    provider = str(impl.get("provider") or "").strip()
    kind = str(impl.get("kind") or "").strip()
    if command:
        return command
    if provider and kind:
        return f"{kind} · {provider}"
    return provider or kind or "—"


def _primary_impl(tool: dict[str, Any]) -> dict[str, Any] | None:
    impls = [item for item in _dict_list(tool.get("implementations")) if item.get("role") != "fallback"]
    if impls:
        return sorted(impls, key=lambda x: int(x.get("priority") or 50))[0]
    impls = _dict_list(tool.get("implementations"))
    if impls:
        return sorted(impls, key=lambda x: int(x.get("priority") or 50))[0]
    return None


def _fallback_impls(tool: dict[str, Any]) -> list[dict[str, Any]]:
    impls = _dict_list(tool.get("implementations"))
    return sorted([item for item in impls if str(item.get("role") or "").lower() == "fallback"], key=lambda x: int(x.get("priority") or 50))


def _tool_search_haystack(tool: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("id", "label", "kind", "coverage", "status", "safety", "notes", "primary", "fallback", "origin", "primary_status_reason"):
        val = tool.get(key)
        if isinstance(val, str):
            parts.append(val)
    for field in ("keywords", "examples", "commands", "skill_refs", "aliases"):
        for item in _as_list(tool.get(field)):
            parts.append(str(item))
    for ref in _as_list(tool.get("origin_refs")):
        if isinstance(ref, dict):
            parts.extend(str(v) for v in ref.values())
    for impl in _dict_list(tool.get("implementations")):
        parts.extend(str(impl.get(k) or "") for k in ("id", "kind", "provider", "command", "role"))
    return " ".join(parts).lower()


def _resolve_skill_lookup(state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if state is None:
        try:
            from zab.services import state_index

            state = state_index.load_state()
        except Exception:
            state = {}
    skills = state.get("skills") if isinstance(state, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    if isinstance(skills, dict):
        for key, item in skills.items():
            if not isinstance(item, dict):
                continue
            aliases = {
                str(key).casefold(),
                str(item.get("id") or "").casefold(),
                str(item.get("key") or "").casefold(),
            }
            for alias in aliases:
                if alias:
                    out[alias] = dict(item)
    return out


def _resolve_skill_refs(skill_refs: list[str], state: dict[str, Any] | None) -> list[dict[str, Any]]:
    lookup = _resolve_skill_lookup(state)
    resolved: list[dict[str, Any]] = []
    for ref in skill_refs:
        hit = lookup.get(ref.casefold())
        resolved.append(
            {
                "id": ref,
                "found": bool(hit),
                "path": hit.get("path") if hit else None,
                "org": hit.get("org") if hit else None,
                "project": hit.get("project") if hit else None,
            }
        )
    return resolved


def _generic_tool(
    *,
    tool_id: str,
    label: str,
    kind: str,
    keywords: list[str],
    examples: list[str],
    implementations: list[dict[str, Any]],
    skill_refs: list[str] | None = None,
    safety: str = "read_first",
    coverage: str = "unknown",
    origin_refs: list[dict[str, Any]] | None = None,
    notes: str | None = None,
    aliases: list[str] | None = None,
    probe: dict[str, Any] | None = None,
    commands: list[str] | None = None,
    status_hint: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": tool_id,
        "label": label,
        "kind": kind,
        "coverage": coverage,
        "keywords": _dedupe([kw.strip() for kw in keywords if kw.strip()]),
        "examples": _dedupe([ex.strip() for ex in examples if ex.strip()]),
        "skill_refs": _dedupe([ref.strip() for ref in (skill_refs or []) if ref.strip()]),
        "safety": safety,
        "implementations": [_normalize_impl(item) for item in implementations],
        "origin_refs": _dict_list(origin_refs or []),
    }
    if notes:
        payload["notes"] = notes
    if aliases:
        payload["aliases"] = _dedupe([alias.strip() for alias in aliases if alias.strip()])
    if probe:
        payload["probe"] = _sanitize_payload(probe)
    if commands:
        payload["commands"] = _dedupe([cmd.strip() for cmd in commands if cmd.strip()])
    if status_hint:
        payload["status_hint"] = status_hint
    return payload


def _domain_tools(state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    scan = tools_scan.scan_tools()
    zab_cli_examples = [item.get("name") for item in scan.get("cli_commands") or [] if isinstance(item, dict) and item.get("name")]
    return [
        _generic_tool(
            tool_id="security-secret-locate",
            label="Localisation secrets .env",
            kind="security_query",
            keywords=[
                "secret",
                "secrets",
                "api key",
                "apikey",
                "token",
                "env",
                ".env",
                "variable environnement",
                "clé api",
                "cle api",
                "payfit",
                "qonto",
                "pennylane",
                "security",
                "locate",
            ],
            examples=[
                "trouve moi l'api key PayFit",
                "localise la clé API Qonto sans afficher la valeur",
                "cherche le token Pennylane dans les .env connus",
            ],
            skill_refs=["zab-orchestrator"],
            safety="read_first",
            coverage="full",
            origin_refs=[
                {"section": "capabilities", "key": "security.locate"},
                {"section": "security", "key": "env"},
            ],
            implementations=[
                {
                    "id": "zab-security-locate-cli",
                    "kind": "cli",
                    "provider": "zab",
                    "role": "primary",
                    "priority": 5,
                    "command": "zab security locate <query> --json",
                    "smoke_command": ["zab", "security", "locate", "payfit", "--json"],
                    "coverage": "full",
                }
            ],
            probe={"kind": "cli", "binary": "zab", "smoke_command": ["zab", "security", "locate", "payfit", "--json"]},
            commands=[
                "zab security locate <query> --json",
                "zab security status --json",
            ],
        ),
        _generic_tool(
            tool_id="gmail-search",
            label="Recherche Gmail",
            kind="communication_search",
            keywords=[
                "mail",
                "email",
                "gmail",
                "boite mail",
                "boîte mail",
                "chercher dans mes mails",
                "piece jointe",
                "pièce jointe",
                "thread",
            ],
            examples=[
                "retrouve l'échange avec un client",
                "trouve une facture SaaS dans mes mails",
                "cherche le mail avec la pièce jointe",
            ],
            skill_refs=["email-mehdi", "google-workspace"],
            safety="read_first",
            coverage="full",
            origin_refs=[
                {"section": "communication_channels", "key": "gmail"},
                {"section": "connectors", "key": "gmail"},
                {"section": "code_tools", "key": "gog"},
            ],
            implementations=[
                {
                    "id": "gmail-gog",
                    "kind": "cli",
                    "provider": "gog",
                    "role": "primary",
                    "priority": 10,
                    "command": "gog gmail messages search '<query>' -a <account> -j --no-input",
                    "smoke_command": ["gog", "gmail", "messages", "search", "is:unread", "-a", "<account>", "-j", "--no-input", "--max", "1"],
                    "coverage": "full",
                },
                {
                    "id": "gmail-composio",
                    "kind": "composio",
                    "provider": "composio",
                    "role": "fallback",
                    "priority": 90,
                    "command": "zab composio gmail search --query '<query>' --limit 5",
                    "fallback_when": ["primary_missing", "primary_auth_failed", "primary_timeout"],
                    "coverage": "partial",
                },
            ],
            probe={"kind": "gmail", "channel_connector": "gmail"},
            commands=[
                "gog gmail messages search '<query>' -a <account> -j --no-input",
                "zab composio gmail search --query '<query>' --limit 5",
            ],
        ),
        _generic_tool(
            tool_id="fireflies-search",
            label="Recherche Fireflies",
            kind="meeting_search",
            keywords=[
                "meeting",
                "compte rendu",
                "compte-rendu",
                "transcript",
                "transcription",
                "fireflies",
                "reunion",
                "réunion",
                "call",
            ],
            examples=[
                "retrouve la note d'une réunion client",
                "cherche les transcripts Fireflies sur le budget",
                "trouve le compte rendu du call client",
            ],
            skill_refs=["fireflies-video-to-notion-recap", "teams-meeting-pipeline"],
            safety="read_first",
            coverage="partial",
            origin_refs=[
                {"section": "connectors", "key": "fireflies"},
                {"section": "skills", "key": "fireflies-video-to-notion-recap"},
            ],
            implementations=[
                {
                    "id": "fireflies-api",
                    "kind": "api",
                    "provider": "fireflies",
                    "role": "primary",
                    "priority": 10,
                    "command": "GET/POST Fireflies API",
                    "coverage": "partial",
                },
                {
                    "id": "fireflies-composio",
                    "kind": "composio",
                    "provider": "composio",
                    "role": "fallback",
                    "priority": 90,
                    "command": "zab composio fireflies search --query '<query>' --limit 5",
                    "fallback_when": ["primary_missing", "primary_auth_failed", "primary_timeout"],
                    "coverage": "partial",
                },
            ],
            probe={"kind": "connector", "slug": "fireflies", "env_keys": ["FIREFLIES_API_KEY"]},
            commands=[
                "zab composio fireflies search --query '<query>' --limit 5",
            ],
        ),
        _generic_tool(
            tool_id="whatsapp-search",
            label="Recherche WhatsApp",
            kind="communication_search",
            keywords=[
                "whatsapp",
                "whats app",
                "message",
                "messages",
                "evolution",
                "conversation",
                "chat",
                "threads",
            ],
            examples=[
                "retrouve un message WhatsApp récent",
                "cherche la conversation Evolution sur le chiffrage",
                "trouve le dernier échange client sur WhatsApp",
            ],
            skill_refs=["mehdi-cowork-whatsapp"],
            safety="read_first",
            coverage="full",
            origin_refs=[
                {"section": "communication_channels", "key": "whatsapp"},
                {"section": "connectors", "key": "evolution-api"},
            ],
            implementations=[
                {
                    "id": "whatsapp-evolution",
                    "kind": "channel",
                    "provider": "evolution-api",
                    "role": "primary",
                    "priority": 10,
                    "command": "Evolution API read-only fetch",
                    "coverage": "full",
                }
            ],
            probe={"kind": "channel", "type": "whatsapp", "connector": "evolution-api"},
            commands=["zab channels --json", "zab channels sync --json"],
        ),
        _generic_tool(
            tool_id="qonto-transactions",
            label="Transactions Qonto",
            kind="finance_query",
            keywords=[
                "qonto",
                "banque",
                "transactions",
                "transaction",
                "justificatif",
                "reconciliation",
                "rapprochement",
                "compta",
                "budget",
            ],
            examples=[
                "liste les transactions Qonto du mois",
                "retrouve le justificatif d'un débit SaaS",
                "cherche un paiement client",
            ],
            skill_refs=["flowmetrik-compta"],
            safety="read_first",
            coverage="partial",
            origin_refs=[
                {"section": "connectors", "key": "qonto"},
                {"section": "skills", "key": "flowmetrik-compta"},
            ],
            implementations=[
                {
                    "id": "qonto-api",
                    "kind": "api+skill",
                    "provider": "qonto",
                    "role": "primary",
                    "priority": 10,
                    "command": "Qonto API read-only transactions",
                    "coverage": "partial",
                }
            ],
            probe={"kind": "connector", "slug": "qonto", "skill_refs": ["flowmetrik-compta"]},
            commands=["zab inspect connectors qonto --json", "zab search qonto --json"],
        ),
        _generic_tool(
            tool_id="pennylane-invoices",
            label="Factures Pennylane",
            kind="finance_query",
            keywords=[
                "pennylane",
                "facture",
                "factures",
                "invoice",
                "invoices",
                "compta",
                "devis",
                "paiement",
                "encaissement",
            ],
            examples=[
                "retrouve la facture Pennylane du client",
                "cherche le devis validé",
                "liste les factures de la semaine",
            ],
            skill_refs=["pennylane-pilot", "flowmetrik-compta"],
            safety="read_first",
            coverage="partial",
            origin_refs=[
                {"section": "connectors", "key": "pennylane"},
                {"section": "skills", "key": "pennylane-pilot"},
            ],
            implementations=[
                {
                    "id": "pennylane-api",
                    "kind": "api+skill",
                    "provider": "pennylane",
                    "role": "primary",
                    "priority": 10,
                    "command": "Pennylane API read-only invoices",
                    "coverage": "partial",
                }
            ],
            probe={"kind": "connector", "slug": "pennylane", "skill_refs": ["pennylane-pilot"]},
            commands=["zab inspect connectors pennylane --json", "zab search pennylane --json"],
        ),
        _generic_tool(
            tool_id="attio-cockpit",
            label="Cockpit Attio",
            kind="crm_query",
            keywords=[
                "attio",
                "crm",
                "company",
                "companies",
                "contact",
                "contacts",
                "deal",
                "deals",
                "pipeline",
            ],
            examples=[
                "cherche le deal client dans Attio",
                "retrouve une fiche company",
                "liste les contacts liés à un deal",
            ],
            skill_refs=["crm-stakeholder-enrichment"],
            safety="read_first",
            coverage="partial",
            origin_refs=[
                {"section": "connectors", "key": "attio"},
                {"section": "skills", "key": "crm-stakeholder-enrichment"},
            ],
            implementations=[
                {
                    "id": "attio-api",
                    "kind": "api+skill",
                    "provider": "attio",
                    "role": "primary",
                    "priority": 10,
                    "command": "Attio API read-only",
                    "coverage": "partial",
                }
            ],
            probe={"kind": "connector", "slug": "attio", "skill_refs": ["crm-stakeholder-enrichment"]},
            commands=["zab inspect connectors attio --json", "zab search attio --json"],
        ),
        _generic_tool(
            tool_id="hubspot-cockpit",
            label="Cockpit HubSpot",
            kind="crm_query",
            keywords=[
                "hubspot",
                "crm",
                "company",
                "companies",
                "contact",
                "contacts",
                "deal",
                "deals",
                "pipeline",
            ],
            examples=[
                "cherche le contact HubSpot",
                "retrouve un deal synchronisé",
                "liste les companies HubSpot récentes",
            ],
            skill_refs=["crm-stakeholder-enrichment"],
            safety="read_first",
            coverage="partial",
            origin_refs=[
                {"section": "connectors", "key": "hubspot"},
            ],
            implementations=[
                {
                    "id": "hubspot-api",
                    "kind": "api",
                    "provider": "hubspot",
                    "role": "primary",
                    "priority": 10,
                    "command": "HubSpot API read-only",
                    "coverage": "partial",
                }
            ],
            probe={"kind": "connector", "slug": "hubspot"},
            commands=["zab inspect connectors hubspot --json", "zab search hubspot --json"],
        ),
        _generic_tool(
            tool_id="obsidian-search",
            label="Recherche Obsidian",
            kind="knowledge_search",
            keywords=[
                "obsidian",
                "vault",
                "note",
                "notes",
                "knowledge",
                "second brain",
                "second-brain",
                "markdown",
                "daily",
            ],
            examples=[
                "cherche la note sur le cockpit",
                "retrouve une daily note qui parle de Qonto",
                "liste les notes liées à un projet",
            ],
            skill_refs=["obsidian", "research-knowledge-sources"],
            safety="read_first",
            coverage="full",
            origin_refs=[
                {"section": "knowledge_sources", "key": "obsidian"},
            ],
            implementations=[
                {
                    "id": "obsidian-mcp",
                    "kind": "mcp",
                    "provider": "zab",
                    "role": "primary",
                    "priority": 10,
                    "command": "zab mcp tool vault_search",
                    "coverage": "full",
                }
            ],
            probe={"kind": "obsidian"},
            commands=["zab agent bootstrap --json", "zab search obsidian --json"],
        ),
        _generic_tool(
            tool_id="memory-search",
            label="Recherche Mémoire",
            kind="memory_search",
            keywords=[
                "memory",
                "mémoire",
                "postgres",
                "recherche",
                "transcript",
                "conversations",
                "agent",
                "historique",
                "notes",
            ],
            examples=[
                "cherche un ancien transcript agent",
                "retrouve une conversation sur le pitch",
                "liste les mémoires liées à un projet",
            ],
            skill_refs=["research-knowledge-sources"],
            safety="read_first",
            coverage="full",
            origin_refs=[
                {"section": "memory_sources", "key": "postgres_memory"},
            ],
            implementations=[
                {
                    "id": "postgres-memory",
                    "kind": "memory",
                    "provider": "postgres",
                    "role": "primary",
                    "priority": 10,
                    "command": "zab memory search <query>",
                    "coverage": "full",
                }
            ],
            probe={"kind": "memory"},
            commands=["zab memory search <query> --json", "zab memory status --json"],
        ),
        _generic_tool(
            tool_id="google-calendar-search",
            label="Recherche Calendar",
            kind="calendar_search",
            keywords=[
                "calendar",
                "agenda",
                "calendar search",
                "meeting",
                "meeting notes",
                "calendar",
                "google calendar",
                "agenda google",
            ],
            examples=[
                "retrouve le rendez-vous MIPIM",
                "cherche le calendrier partagé",
                "liste les prochains meetings",
            ],
            skill_refs=["mehdi-calendar-sync", "google-workspace"],
            safety="read_first",
            coverage="partial",
            origin_refs=[
                {"section": "connectors", "key": "googlecalendar"},
            ],
            implementations=[
                {
                    "id": "google-calendar-api",
                    "kind": "api",
                    "provider": "googlecalendar",
                    "role": "primary",
                    "priority": 10,
                    "command": "Google Calendar API read-only",
                    "coverage": "partial",
                }
            ],
            probe={"kind": "connector", "slug": "googlecalendar", "skill_refs": ["mehdi-calendar-sync"]},
            commands=["zab inspect connectors googlecalendar --json", "zab search calendar --json"],
        ),
        _generic_tool(
            tool_id="google-drive-search",
            label="Recherche Drive",
            kind="drive_search",
            keywords=[
                "drive",
                "google drive",
                "documents",
                "docs",
                "files",
                "fichiers",
                "shared drive",
                "search",
                "document",
            ],
            examples=[
                "retrouve le dossier MIPIM",
                "cherche un deck commercial",
                "trouve le document de proposition",
            ],
            skill_refs=["google-workspace"],
            safety="read_first",
            coverage="partial",
            origin_refs=[
                {"section": "connectors", "key": "googledrive"},
            ],
            implementations=[
                {
                    "id": "google-drive-api",
                    "kind": "api",
                    "provider": "googledrive",
                    "role": "primary",
                    "priority": 10,
                    "command": "Google Drive API read-only",
                    "coverage": "partial",
                }
            ],
            probe={"kind": "connector", "slug": "googledrive"},
            commands=["zab inspect connectors googledrive --json", "zab search drive --json"],
        ),
        _generic_tool(
            tool_id="zab-cli",
            label="CLI Zab",
            kind="developer_cli",
            keywords=[
                "zab",
                "sync",
                "search",
                "inspect",
                "tools",
                "catalog",
                "dashboard",
                "agent",
                "state",
            ],
            examples=[
                "zab tools search gmail --json",
                "zab sync --json",
                "zab search qonto --json",
            ],
            skill_refs=["zab-orchestrator"],
            safety="read_first",
            coverage="full",
            origin_refs=[
                {"section": "code_tools", "key": "zab"},
                {"section": "cli_watchlist", "key": "zab"},
            ],
            implementations=[
                {
                    "id": "zab-cli",
                    "kind": "cli",
                    "provider": "zab",
                    "role": "primary",
                    "priority": 5,
                    "command": "python -m zab.cli",
                    "smoke_command": ["python", "-m", "zab.cli", "--help"],
                    "coverage": "full",
                }
            ],
            probe={"kind": "cli", "binary": "zab", "smoke_command": ["python", "-m", "zab.cli", "--help"]},
            commands=zab_cli_examples[:8] if zab_cli_examples else ["python -m zab.cli --help"],
        ),
    ]


def _code_tool_examples(binary: str) -> list[str]:
    mapping: dict[str, list[str]] = {
        "gh": ["gh auth status", "gh pr list", "gh issue list"],
        "gcloud": ["gcloud auth list", "gcloud projects list", "gcloud config list"],
        "composio": ["composio connections --active", "composio search gmail", "composio whoami --toolkit gmail"],
        "gog": ["gog gmail messages search is:unread -a <account> -j --no-input --max 1"],
        "claude": ["claude --version", "claude mcp list"],
        "codex": ["codex --version", "codex login"],
        "cursor": ["cursor --help"],
        "gemini": ["gemini --help"],
        "kimi": ["kimi --help"],
        "qwen": ["qwen --help"],
        "factory": ["factory --help"],
        "continue": ["continue --help"],
        "hermes": ["hermes --help"],
    }
    return mapping.get(binary, [f"{binary} --help"])


def _code_tool_keywords(binary: str, provider: str, kind: str, *, extra: list[str] | None = None) -> list[str]:
    base = [
        binary,
        provider,
        kind,
        "cli",
        "code tool",
    ]
    if extra:
        base.extend(extra)
    return _dedupe([item for item in base if item])


def _code_tool_spec(binary: str, meta: dict[str, Any], *, source: str, watchlisted: bool) -> dict[str, Any]:
    provider = str(meta.get("provider") or binary).strip() or binary
    kind = str(meta.get("kind") or "cli").strip() or "cli"
    display_name = str(meta.get("display_name") or _titleize(binary)).strip()
    installed = bool(meta.get("installed"))
    commands = _code_tool_examples(binary)
    tool = _generic_tool(
        tool_id=f"code-{binary}",
        label=display_name,
        kind="developer_cli",
        keywords=_code_tool_keywords(binary, provider, kind, extra=[display_name.lower()]),
        examples=commands[:3],
        skill_refs=[],
        safety="read_first",
        coverage="unknown",
        origin_refs=[{"section": "code_tools", "key": binary}, {"section": source, "key": binary}],
        implementations=[
            {
                "id": f"code-{binary}-cli",
                "kind": "cli",
                "provider": provider,
                "role": "primary",
                "priority": 10,
                "command": binary,
                "smoke_command": [binary, "--help"],
                "coverage": "unknown",
            }
        ],
        probe={"kind": "cli", "binary": binary, "smoke_command": [binary, "--help"]},
        commands=commands,
    )
    tool["installed"] = installed
    tool["source_kind"] = source
    tool["watchlisted"] = watchlisted
    return tool


def _code_tools(state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if state is None:
        try:
            from zab.services import state_index

            state = state_index.load_state()
        except Exception:
            state = {}
    raw_tools = state.get("code_tools") if isinstance(state, dict) else {}
    by_binary: dict[str, dict[str, Any]] = {}
    if isinstance(raw_tools, dict):
        for binary, item in raw_tools.items():
            if not isinstance(item, dict):
                continue
            by_binary[str(binary)] = dict(item)
    for name in _merged_cli_watchlist_names():
        key = name.strip()
        if not key:
            continue
        by_binary.setdefault(
            key,
            {
                "id": key,
                "display_name": _titleize(key),
                "provider": key,
                "kind": "cli",
                "binary": shutil.which(key),
                "installed": bool(shutil.which(key)),
            },
        )
    tool_map: dict[str, dict[str, Any]] = {}
    for binary, meta in by_binary.items():
        tool = _code_tool_spec(
            binary,
            meta,
            source="cli_watchlist" if binary in _merged_cli_watchlist_names() else "code_tools",
            watchlisted=binary in _merged_cli_watchlist_names(),
        )
        tool_map[tool["id"]] = tool
    return sorted(tool_map.values(), key=lambda x: str(x.get("label") or x.get("id") or "").casefold())


def _materialize_tool(tool: dict[str, Any], *, state: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(tool)
    out["keywords"] = _dedupe(_string_list(out.get("keywords")))
    out["examples"] = _dedupe(_string_list(out.get("examples")))
    out["skill_refs"] = _dedupe(_string_list(out.get("skill_refs")))
    out["commands"] = _dedupe(_string_list(out.get("commands")))
    out["origin_refs"] = _dict_list(out.get("origin_refs"))
    out["implementations"] = [_normalize_impl(item) for item in _dict_list(out.get("implementations"))]
    out["providers"] = _dedupe([str(impl.get("provider") or "").strip() for impl in out["implementations"] if str(impl.get("provider") or "").strip()])
    primary = _primary_impl(out)
    fallbacks = _fallback_impls(out)
    out["primary"] = _implementation_summary(primary)
    out["fallback"] = _implementation_summary(fallbacks[0] if fallbacks else None)
    out["has_fallback"] = bool(fallbacks)
    out["primary_implementation_id"] = primary.get("id") if primary else None
    out["fallback_implementation_ids"] = [fb.get("id") for fb in fallbacks if fb.get("id")]
    out["origin"] = ", ".join(
        _dedupe(
            [
                str(ref.get("section") or "").replace("_", " ")
                for ref in out["origin_refs"]
                if isinstance(ref, dict) and ref.get("section")
            ]
        )
    )
    if not out["origin"]:
        out["origin"] = "local"
    out["linked_skills"] = _resolve_skill_refs(out["skill_refs"], state)
    out["search_text"] = _tool_search_haystack(out)
    out["status"] = _probe_status(out, state=state)
    out["availability_tag"] = _availability_tag(out)
    out["status_reason"] = _status_reason(out, state=state)
    out["last_checked_at_utc"] = _now()
    return _sanitize_payload(out)


def _availability_tag(tool: dict[str, Any]) -> str:
    status = str(tool.get("status") or "skipped")
    if status == "ok":
        return "primary"
    if status == "warn" and tool.get("has_fallback"):
        return "fallback"
    if status == "warn":
        return "degraded"
    if status == "fail":
        return "missing"
    return "degraded"


def _status_reason(tool: dict[str, Any], state: dict[str, Any] | None = None) -> str:
    probe = tool.get("probe") if isinstance(tool.get("probe"), dict) else {}
    probe_kind = str(probe.get("kind") or "").lower()
    if probe_kind == "cli":
        binary = str(probe.get("binary") or "").strip()
        if binary:
            return f"{binary} {'present' if shutil.which(binary) else 'missing'}"
        return "CLI probe"
    if probe_kind == "memory":
        st = memory_db.fetch_status()
        if st.get("connected"):
            return "Mémoire Postgres connectée"
        if st.get("configured"):
            return str(st.get("error") or "Mémoire configurée mais non connectée")
        return "Mémoire non configurée"
    if probe_kind == "obsidian":
        doc = obsidian_vault.doctor_payload()
        if doc.get("exists"):
            return "Vault Obsidian présent"
        return str(doc.get("error") or "Vault Obsidian absent")
    if probe_kind == "channel":
        ch = _find_channel(tool)
        if ch:
            return f"Canal {ch.get('label') or ch.get('id')} configuré"
        return "Canal non configuré"
    if probe_kind == "connector":
        slug = str(probe.get("slug") or "").strip()
        if not slug:
            return "Connector probe"
        detail = connectors_aggregate.get_connector(slug)
        if detail:
            forms = detail.get("forms") if isinstance(detail.get("forms"), list) else []
            enabled = [f for f in forms if isinstance(f, dict) and bool(f.get("enabled"))]
            if enabled:
                return f"Connector {slug} disponible"
            return f"Connector {slug} trouvé mais désactivé"
        return f"Connector {slug} absent"
    return "Probe inconnue"


def _probe_status(tool: dict[str, Any], state: dict[str, Any] | None = None) -> str:
    probe = tool.get("probe") if isinstance(tool.get("probe"), dict) else {}
    probe_kind = str(probe.get("kind") or "").lower()
    if probe_kind == "cli":
        binary = str(probe.get("binary") or "").strip()
        smoke = probe.get("smoke_command")
        if binary == "zab":
            return "ok"
        if binary and shutil.which(binary):
            return "ok" if smoke else "ok"
        return "fail"
    if probe_kind == "memory":
        st = memory_db.fetch_status()
        if st.get("connected"):
            return "ok"
        if st.get("configured"):
            return "warn"
        return "fail"
    if probe_kind == "obsidian":
        doc = obsidian_vault.doctor_payload()
        if doc.get("exists"):
            missing = doc.get("validation", {}).get("missing_dirs") if isinstance(doc.get("validation"), dict) else []
            return "warn" if missing else "ok"
        return "fail"
    if probe_kind == "channel":
        ch = _find_channel(tool)
        if not ch:
            return "fail"
        connector = str(probe.get("connector") or "").strip()
        if connector == "evolution-api" and _channel_has_required_credentials(ch):
            return "ok"
        return "warn"
    if probe_kind == "connector":
        slug = str(probe.get("slug") or "").strip()
        if not slug:
            return "skipped"
        detail = connectors_aggregate.get_connector(slug)
        if not detail:
            env_keys = _string_list(probe.get("env_keys"))
            if (shutil.which("composio") or composio_cli_path()) and env_keys:
                return "warn"
            return "fail"
        forms = detail.get("forms") if isinstance(detail.get("forms"), list) else []
        non_composio = [f for f in forms if isinstance(f, dict) and str(f.get("kind") or "").lower() != "composio" and bool(f.get("enabled"))]
        composio_forms = [f for f in forms if isinstance(f, dict) and str(f.get("kind") or "").lower() == "composio" and bool(f.get("enabled"))]
        env_keys = _string_list(probe.get("env_keys"))
        env_ready = any((os.environ.get(key) or "").strip() for key in env_keys) if env_keys else False
        if non_composio or env_ready:
            return "ok"
        if composio_forms:
            return "warn"
        return "warn"
    return "skipped"


def _find_channel(tool: dict[str, Any]) -> dict[str, Any] | None:
    probe = tool.get("probe") if isinstance(tool.get("probe"), dict) else {}
    probe_type = str(probe.get("type") or "").lower()
    connector = str(probe.get("connector") or "").lower()
    for channel in communication_channels.load_channels_config():
        if not isinstance(channel, dict):
            continue
        if probe_type and str(channel.get("type") or "").lower() != probe_type:
            continue
        if connector and str(channel.get("connector") or "").lower() != connector:
            continue
        return channel
    return None


def _channel_has_required_credentials(channel: dict[str, Any]) -> bool:
    creds = channel.get("credentials") if isinstance(channel.get("credentials"), dict) else {}
    url = str(creds.get("evolution_api_url") or channel.get("evolution_api_url") or "").strip()
    key = str(creds.get("evolution_api_key") or channel.get("evolution_api_key") or "").strip()
    instance = str(creds.get("evolution_instance") or channel.get("evolution_instance") or "").strip()
    return bool(url and key and instance)


def _validate_commands(tool: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    commands = _string_list(tool.get("commands"))
    for impl in _dict_list(tool.get("implementations")):
        commands.extend(_string_list(impl.get("command")))
        smoke = impl.get("smoke_command")
        if isinstance(smoke, list):
            commands.extend(str(x) for x in smoke if str(x).strip())
    for command in commands:
        lower = command.lower()
        if any(token in lower for token in _SAFE_COMMAND_RISKY_TOKENS):
            issues.append(
                {
                    "tool_id": tool.get("id"),
                    "severity": "warn",
                    "code": "unsafe_command",
                    "message": f"commande potentiellement mutante : {command[:120]}",
                }
            )
            break
    return issues


def _summarize_tools(tools: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(tool.get("status") or "skipped") for tool in tools)
    kinds = Counter(str(tool.get("kind") or "unknown") for tool in tools)
    providers = Counter()
    for tool in tools:
        for provider in _as_list(tool.get("providers")):
            if isinstance(provider, str) and provider.strip():
                providers[provider.strip()] += 1
    return {
        "total": len(tools),
        "ok": statuses.get("ok", 0),
        "warn": statuses.get("warn", 0),
        "fail": statuses.get("fail", 0),
        "skipped": statuses.get("skipped", 0),
        "kinds": dict(sorted(kinds.items(), key=lambda x: x[0])),
        "providers": dict(sorted(providers.items(), key=lambda x: x[0])),
        "with_skill_refs": sum(1 for tool in tools if tool.get("skill_refs")),
        "with_fallback": sum(1 for tool in tools if tool.get("has_fallback")),
    }


def _collect_raw_tools(state: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Assemble les specs brutes (domaine + code tools + annotations) avant matérialisation."""

    raw_tools: list[dict[str, Any]] = []
    raw_tools.extend(_domain_tools(state))
    raw_tools.extend(_code_tools(state))

    annotations_doc = _read_yaml(tools_catalog_config_path())
    annotations = annotations_doc.get("tools") if isinstance(annotations_doc, dict) else {}
    if isinstance(annotations, dict):
        for tool_id, override in annotations.items():
            if not isinstance(override, dict):
                continue
            override_doc = dict(override)
            override_doc.setdefault("id", tool_id)
            raw_tools.append(_merge_tool({"id": str(tool_id)}, override_doc))
    elif isinstance(annotations, list):
        for item in annotations:
            if not isinstance(item, dict):
                continue
            tool_id = str(item.get("id") or "").strip()
            if not tool_id:
                continue
            raw_tools.append(_merge_tool({"id": tool_id}, item))

    by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    for tool in raw_tools:
        tid = str(tool.get("id") or "").strip()
        if not tid:
            continue
        if tid in by_id:
            duplicate_ids.append(tid)
            by_id[tid] = _merge_tool(by_id[tid], tool)
        else:
            by_id[tid] = dict(tool)
    return by_id, duplicate_ids


def recheck_tool(
    tool_id: str,
    *,
    state: dict[str, Any] | None = None,
    persist: bool = False,
) -> dict[str, Any] | None:
    """Re-matérialise un seul tool *en direct* (relance les probes de connexion),
    en contournant le chemin rapide de l'index. Relit aussi les annotations sur disque.

    Si ``persist`` est vrai, écrit le tool re-matérialisé dans l'index local-first pour
    que le statut fraîchement sondé survive à un rechargement (sans ``zab sync`` complet)."""

    if state is None:
        try:
            from zab.services import state_index

            state = state_index.load_state()
        except Exception:
            state = {}
    by_id, _ = _collect_raw_tools(state)
    key = tool_id.strip().lower()
    match = next((tool for tid, tool in by_id.items() if str(tid).lower() == key), None)
    if not match:
        return None
    materialized = _materialize_tool(match, state=state)
    if persist:
        try:
            from zab.services import postgres_store as state_store

            state_store.upsert_state_item("tools", str(materialized.get("id") or tool_id), materialized)
        except Exception:
            pass
    return materialized


_EDITABLE_STRING_FIELDS = ("label", "kind", "coverage", "safety", "notes")
_EDITABLE_LIST_FIELDS = ("keywords", "examples", "skill_refs", "commands")


def editable_tool_fields(tool_id: str, *, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Valeurs effectives éditables d'un tool (pour préremplir le formulaire)."""

    tool = recheck_tool(tool_id, state=state)
    if not tool:
        return None
    fields: dict[str, Any] = {field: tool.get(field) for field in _EDITABLE_STRING_FIELDS}
    for field in _EDITABLE_LIST_FIELDS:
        fields[field] = _string_list(tool.get(field))
    return fields


def _clean_annotation_patch(patch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in _EDITABLE_STRING_FIELDS:
        if field in patch and patch[field] is not None:
            out[field] = str(patch[field]).strip()
    for field in _EDITABLE_LIST_FIELDS:
        if field in patch and patch[field] is not None:
            out[field] = _string_list(patch[field])
    return out


def update_tool_annotations(tool_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    """Écrit/merge les champs éditables d'un tool dans ``~/.config/zab/tools.yaml``
    puis renvoie le tool re-matérialisé en direct. Retourne ``None`` si tool inconnu."""

    tid = tool_id.strip()
    if not tid:
        return None
    # Refuser un id inconnu : on ne crée pas de tool ex nihilo depuis l'UI.
    if recheck_tool(tid) is None:
        return None

    cleaned = _clean_annotation_patch(patch)
    path = tools_catalog_config_path()
    doc = _read_yaml(path)
    if not isinstance(doc, dict) or doc.get("_error"):
        doc = {}
    tools_section = doc.get("tools")
    if not isinstance(tools_section, dict):
        tools_section = {}
    existing = tools_section.get(tid)
    existing = dict(existing) if isinstance(existing, dict) else {}
    existing.update(cleaned)
    existing.setdefault("id", tid)
    tools_section[tid] = existing
    doc["tools"] = tools_section

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    updated = recheck_tool(tid)
    # Refléter immédiatement l'édition dans l'index local-first (chemin rapide de
    # lecture) sans attendre un ``zab sync`` complet.
    if updated is not None:
        try:
            from zab.services import postgres_store as state_store

            key = str(updated.get("id") or tid)
            state_store.upsert_state_item("tools", key, _sanitize_payload(updated))
        except Exception:
            pass
    return updated


def build_tools_catalog(*, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Construit le catalogue canonique des tools Zab."""

    loaded_from_index = False
    if state is None:
        try:
            from zab.services import state_index

            state = state_index.load_state()
            loaded_from_index = True
        except Exception:
            state = {}

    # Chemin rapide (lecture) : réutiliser les tools déjà matérialisés par
    # ``zab sync`` dans l'index plutôt que de re-matérialiser à chaque appel
    # (~3 s de _materialize_tool). Le build canonique reste inchangé quand un
    # ``state`` explicite est fourni (cas de state_index.build_state).
    if loaded_from_index and isinstance(state, dict):
        prebuilt = state.get("tools")
        if isinstance(prebuilt, dict) and prebuilt:
            reused_by_id = {
                str(t.get("id") or key): dict(t)
                for key, t in prebuilt.items()
                if isinstance(t, dict) and str(t.get("id") or key).strip()
            }
            for tool in _domain_tools(state):
                tid = str(tool.get("id") or "").strip()
                if tid and tid not in reused_by_id:
                    reused_by_id[tid] = _materialize_tool(tool, state=state)
            reused = list(reused_by_id.values())
            reused = sorted(reused, key=lambda x: str(x.get("label") or x.get("id") or "").casefold())
            payload = {
                "contract": TOOLS_CATALOG_CONTRACT,
                "contract_version": TOOLS_CATALOG_CONTRACT_VERSION,
                "generated_at_utc": state.get("last_sync_at") or _now(),
                "annotations_path": str(tools_catalog_config_path()),
                "duplicate_ids": [],
                "summary": _summarize_tools(reused),
                "tools": reused,
            }
            return _sanitize_payload(payload)

    by_id, duplicate_ids = _collect_raw_tools(state)

    tools = [_materialize_tool(tool, state=state) for tool in by_id.values()]
    tools = sorted(tools, key=lambda x: str(x.get("label") or x.get("id") or "").casefold())
    summary = _summarize_tools(tools)
    payload: dict[str, Any] = {
        "contract": TOOLS_CATALOG_CONTRACT,
        "contract_version": TOOLS_CATALOG_CONTRACT_VERSION,
        "generated_at_utc": _now(),
        "annotations_path": str(tools_catalog_config_path()),
        "duplicate_ids": _dedupe(duplicate_ids),
        "summary": summary,
        "tools": tools,
    }
    return _sanitize_payload(payload)


def list_tools(
    *,
    page: int = 1,
    limit: int = 50,
    q: str = "",
    kind: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    has_skill_refs: bool | None = None,
    has_fallback: bool | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = build_tools_catalog(state=state)
    rows = list(catalog.get("tools") or [])
    qn = q.strip().lower()
    kind_n = kind.strip().lower() if kind else None
    status_n = status.strip().lower() if status else None
    provider_n = provider.strip().lower() if provider else None
    filtered: list[dict[str, Any]] = []
    for tool in rows:
        if kind_n and str(tool.get("kind") or "").lower() != kind_n:
            continue
        if status_n and str(tool.get("status") or "").lower() != status_n:
            continue
        if provider_n:
            providers = [str(item).lower() for item in _as_list(tool.get("providers"))]
            if provider_n not in providers and provider_n != str(tool.get("primary_implementation_id") or "").lower():
                continue
        if has_skill_refs is not None and bool(tool.get("skill_refs")) is not has_skill_refs:
            continue
        if has_fallback is not None and bool(tool.get("has_fallback")) is not has_fallback:
            continue
        if qn and qn not in _tool_search_haystack(tool):
            continue
        filtered.append(tool)
    total = len(filtered)
    capped = max(1, min(200, int(limit or 50)))
    page = max(1, int(page or 1))
    total_pages = max(1, math.ceil(total / capped)) if total else 1
    start = (page - 1) * capped
    page_rows = filtered[start : start + capped]
    data = [
        {
            "id": tool.get("id"),
            "label": tool.get("label"),
            "kind": tool.get("kind"),
            "status": tool.get("status"),
            "availability_tag": tool.get("availability_tag"),
            "coverage": tool.get("coverage"),
            "primary": tool.get("primary"),
            "fallback": tool.get("fallback"),
            "keywords": tool.get("keywords") or [],
            "examples": tool.get("examples") or [],
            "skill_refs": tool.get("skill_refs") or [],
            "origin": tool.get("origin"),
            "providers": tool.get("providers") or [],
            "has_fallback": bool(tool.get("has_fallback")),
            "has_skill_refs": bool(tool.get("skill_refs")),
            "status_reason": tool.get("status_reason"),
            "last_checked_at_utc": tool.get("last_checked_at_utc"),
        }
        for tool in page_rows
    ]
    return {
        "contract": TOOLS_CATALOG_CONTRACT,
        "contract_version": TOOLS_CATALOG_CONTRACT_VERSION,
        "generated_at_utc": catalog.get("generated_at_utc"),
        "annotations_path": catalog.get("annotations_path"),
        "filters": {
            "q": q,
            "kind": kind,
            "status": status,
            "provider": provider,
            "has_skill_refs": has_skill_refs,
            "has_fallback": has_fallback,
        },
        "pagination": {
            "page": page,
            "limit": capped,
            "total": total,
            "total_pages": total_pages,
        },
        "summary": catalog.get("summary") or {},
        "data": data,
    }


def search_tools(
    query: str,
    *,
    limit: int = 20,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = build_tools_catalog(state=state)
    q = query.strip().lower()
    terms = [term for term in q.split() if term]
    rows = list(catalog.get("tools") or [])
    scored: list[dict[str, Any]] = []
    for tool in rows:
        hay = _tool_search_haystack(tool)
        if terms and not any(term in hay for term in terms):
            continue
        score = 0
        reasons: list[str] = []
        if q and q in hay:
            score += 20
            reasons.append("phrase")
        for field in ("id", "label"):
            val = str(tool.get(field) or "").lower()
            if q and q in val:
                score += 10
                reasons.append(field)
        for token in terms:
            if token in hay:
                score += 3
        if any(token in _tool_search_haystack({"keywords": tool.get("keywords")}) for token in terms):
            reasons.append("keywords")
        if any(token in _tool_search_haystack({"examples": tool.get("examples")}) for token in terms):
            reasons.append("examples")
        if any(token in _tool_search_haystack({"commands": tool.get("commands")}) for token in terms):
            reasons.append("commands")
        if any(token in _tool_search_haystack({"skill_refs": tool.get("skill_refs")}) for token in terms):
            reasons.append("skills")
        scored.append({**tool, "score": score, "match_reasons": _dedupe(reasons) or ["content"]})
    scored.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("label") or x.get("id") or "").casefold()))
    capped = max(1, min(100, int(limit or 20)))
    return {
        "contract": f"{TOOLS_CATALOG_CONTRACT}-search",
        "contract_version": TOOLS_CATALOG_CONTRACT_VERSION,
        "generated_at_utc": catalog.get("generated_at_utc"),
        "query": query,
        "total": len(scored),
        "data": scored[:capped],
    }


def get_tool(tool_id: str, *, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    catalog = build_tools_catalog(state=state)
    key = tool_id.strip().lower()
    tool = next((row for row in catalog.get("tools") or [] if str(row.get("id") or "").lower() == key), None)
    if not tool:
        return None
    return {
        "contract": f"{TOOLS_CATALOG_CONTRACT}-item",
        "contract_version": TOOLS_CATALOG_CONTRACT_VERSION,
        "generated_at_utc": catalog.get("generated_at_utc"),
        "tool": tool,
        "linked_skills": tool.get("linked_skills") or [],
        "usage": {
            "list_command": "zab tools list --json",
            "search_command": "zab tools search <query> --json",
            "check_command": f"zab tools check {tool['id']} --json",
        },
    }


def validate_tools(*, strict: bool = False, state: dict[str, Any] | None = None) -> dict[str, Any]:
    catalog = build_tools_catalog(state=state)
    tools = list(catalog.get("tools") or [])
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_ids = set(catalog.get("duplicate_ids") or [])
    for tool in tools:
        tid = str(tool.get("id") or "").strip()
        if not tid:
            issues.append({"tool_id": "", "severity": "error", "code": "missing_id", "message": "tool sans id"})
            continue
        if not _TOOL_ID_RE.match(tid):
            issues.append({"tool_id": tid, "severity": "error", "code": "invalid_id", "message": f"id invalide: {tid}"})
        if tid in seen or tid in duplicate_ids:
            issues.append({"tool_id": tid, "severity": "error", "code": "duplicate_id", "message": f"duplicate id: {tid}"})
        seen.add(tid)
        if not tool.get("keywords"):
            issues.append({"tool_id": tid, "severity": "error", "code": "missing_keywords", "message": "aucun mot-clé"})
        for ref in _string_list(tool.get("skill_refs")):
            resolved = any(
                ref.casefold() == str(item.get("id") or "").casefold() or ref.casefold() == str(item.get("key") or "").casefold()
                for item in (_resolve_skill_lookup(state).values())
            )
            if not resolved:
                issues.append(
                    {
                        "tool_id": tid,
                        "severity": "warn",
                        "code": "broken_skill_ref",
                        "message": f"skill_ref introuvable: {ref}",
                    }
                )
        issues.extend(_validate_commands(tool))
    severity_counts = Counter(item["severity"] for item in issues)
    summary = {
        "total_tools": len(tools),
        "errors": severity_counts.get("error", 0),
        "warnings": severity_counts.get("warn", 0),
        "broken_skill_refs": sum(1 for item in issues if item.get("code") == "broken_skill_ref"),
        "invalid_ids": sum(1 for item in issues if item.get("code") == "invalid_id"),
        "unsafe_commands": sum(1 for item in issues if item.get("code") == "unsafe_command"),
    }
    if strict:
        summary["strict"] = True
        summary["exit_status"] = 1 if summary["errors"] or summary["invalid_ids"] or summary["broken_skill_refs"] else 0
    return {
        "contract": f"{TOOLS_CATALOG_CONTRACT}-validation",
        "contract_version": TOOLS_CATALOG_CONTRACT_VERSION,
        "generated_at_utc": catalog.get("generated_at_utc"),
        "strict": strict,
        "summary": summary,
        "issues": issues,
    }
