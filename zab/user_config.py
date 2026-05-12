"""Configuration utilisateur ~/.config/zab/config.yaml (skills_root, liste CLI manuelle)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.paths import config_dir

CONFIG_FILENAME = "config.yaml"

# Modèle écrit par ensure_user_config_exists() si ~/.config/zab/config.yaml est absent.
DEFAULT_USER_CONFIG_YAML = """# Configuration zab — fichier créé au premier lancement ou par install-zab-shell.sh
#
# Inventaire explicite (recommandé) — rempli par : zab scan --propose-config puis zab scan --apply-config
# Liste chaque SKILL.md et chaque dossier plugin Claude détectés au scan (pas seulement une racine).
#
skill_md_paths: []

claude_plugin_paths: []

# Racines dépôt (orgs/, configs/, …) — optionnel si skill_md_paths couvre déjà vos dépôts (MCP déduit des chemins SKILL.md).
skills_roots: []

# Ancienne clé (optionnelle) : première entrée équivalente à skills_roots[0] si la liste est vide
# skills_root: ~/projects/skills
#
# Fichier local-tools (proxies LLM, cli_watchlist) — optionnel ; défaut : ~/.config/zab/local-tools.yaml
# local_tools_path: ~/.config/zab/local-tools.yaml

cli_watchlist: []

# Chemins optionnels — sinon défaut ~/.agentpipe.yaml et ~/.codexbar/config.json
# agentpipe_config_path: ~/.agentpipe.yaml
# codexbar_config_path: ~/.codexbar/config.json

# Rempli automatiquement si vous cochez « Enregistrer après scan » sur Modèles / Cursor :
# models_discovery:
#   updated_at_utc: ...
#   agentpipe: { config_path, coding_models_flat, agents: [...] }
#   codexbar: { config_path, cli_probe: {...} }

# Dépôts « projets » (découverte skills .cursor / .claude). Si la clé est absente : ~/projects lorsqu’il existe.
# Liste vide [] = désactiver la découverte par projets.
# projects_roots:
#   - ~/projects

# Variables supplémentaires suivies (dashboard Sécurité), en plus du catalogue zab
tracked_env_extra: []

# Tâches agrégées : jetons GitLab / Linear / Notion — préférez ~/.config/zab/.env
# (fusion : zab pm-env sync ou bouton dans l’onglet Tâches). Ne mettez pas de secrets dans ce YAML.
# Liste task_sources pour GET /api/tasks/inbox — chaque entrée : id, label, backend (gitlab|linear|notion),
# routing_doc (chemin ou URL), mcp_hint (optionnel), local_project_path (optionnel),
# env_token (défaut GITLAB_TOKEN / LINEAR_API_KEY / NOTION_TOKEN).
# GitLab : host (défaut gitlab.com), path_with_namespace OU project_id ; optionnel assignee_username.
# Linear : optionnel team_keys (clés d’équipe).
# Notion : database_id ; notion_title_prop (défaut Name).
# task_sources: []
"""


def user_config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def ensure_user_config_exists() -> Path | None:
    """
    Crée ~/.config/zab/config.yaml avec le modèle par défaut si le fichier n'existe pas.
    Retourne le chemin si création, None si le fichier était déjà présent.
    """
    p = user_config_path()
    if p.is_file():
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_USER_CONFIG_YAML.strip() + "\n", encoding="utf-8")
    return p


def load_user_config() -> dict[str, Any]:
    p = user_config_path()
    if not p.is_file():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (yaml.YAMLError, OSError):
        return {"_error": "yaml_invalid", "path": str(p)}


def save_user_config(data: dict[str, Any]) -> Path:
    p = user_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def projects_roots_strings_ordered() -> list[str]:
    """
    Racines contenant des dossiers projet (un niveau).
    Clé absente : défaut ``~/projects`` (chaîne seule ; filtré par ``projects_roots_resolved`` si inexistant).
    ``projects_roots: []`` explicite : aucune racine (découverte désactivée).
    """
    cfg = load_user_config()
    if "projects_roots" not in cfg:
        return [str(Path.home() / "projects")]
    raw = cfg.get("projects_roots")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            v = x.strip()
            if v not in out:
                out.append(v)
    return out


def projects_roots_resolved() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for s in projects_roots_strings_ordered():
        try:
            p = Path(s).expanduser().resolve()
        except OSError:
            continue
        if not p.is_dir():
            continue
        k = str(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def skills_roots_strings_ordered() -> list[str]:
    """Ordre : skills_roots[] puis skills_root legacy si absent de la liste."""
    cfg = load_user_config()
    out: list[str] = []
    raw_list = cfg.get("skills_roots")
    if isinstance(raw_list, list):
        for x in raw_list:
            if isinstance(x, str) and x.strip():
                v = x.strip()
                if v not in out:
                    out.append(v)
    leg = cfg.get("skills_root")
    if isinstance(leg, str) and leg.strip():
        v = leg.strip()
        if v not in out:
            out.insert(0, v)
    return out


def skill_md_paths_strings_ordered() -> list[str]:
    cfg = load_user_config()
    raw = cfg.get("skill_md_paths")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            v = x.strip()
            if v not in out:
                out.append(v)
    return out


def claude_plugin_paths_strings_ordered() -> list[str]:
    cfg = load_user_config()
    raw = cfg.get("claude_plugin_paths")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            v = x.strip()
            if v not in out:
                out.append(v)
    return out


def skill_md_paths_resolved() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for s in skill_md_paths_strings_ordered():
        try:
            p = Path(s).expanduser().resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        k = str(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def claude_plugin_paths_resolved() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for s in claude_plugin_paths_strings_ordered():
        try:
            p = Path(s).expanduser().resolve()
        except OSError:
            continue
        if not p.is_dir():
            continue
        k = str(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def merge_scan_inventory_into_config(
    skill_md_abs_paths: list[str],
    *,
    claude_plugin_abs_paths: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Remplace skill_md_paths / claude_plugin_paths et vide skills_roots (inventaire explicite).
    Si claude_plugin_abs_paths est None, déduit les bundles depuis les chemins SKILL.md.
    """
    from zab.services.inventory_config import collect_plugin_roots_from_skill_paths

    cfg = load_user_config()
    cfg.pop("_error", None)
    skills_set = sorted(
        {str(Path(x).expanduser().resolve()) for x in skill_md_abs_paths if x and str(x).strip()}
    )
    if claude_plugin_abs_paths is None:
        roots_pl = collect_plugin_roots_from_skill_paths([Path(s) for s in skills_set])
        plugins_set = [str(p) for p in roots_pl]
    else:
        plugins_set = sorted(
            {str(Path(x).expanduser().resolve()) for x in claude_plugin_abs_paths if x and str(x).strip()}
        )
    cfg["skill_md_paths"] = skills_set
    cfg["claude_plugin_paths"] = plugins_set
    cfg["skills_roots"] = []
    cfg.pop("skills_root", None)
    save_user_config(cfg)
    summary = {"skill_md_paths": skills_set, "claude_plugin_paths": plugins_set}
    return user_config_path(), summary


def merge_skills_roots_into_config(paths_str: list[str]) -> tuple[Path, list[str]]:
    """Ajoute des chemins à ``skills_roots``, supprime la clé legacy ``skills_root``."""
    cfg = load_user_config()
    cfg.pop("_error", None)
    merged = skills_roots_strings_ordered()
    for raw in paths_str:
        if not raw or not str(raw).strip():
            continue
        p = str(Path(raw.strip()).expanduser().resolve())
        if p not in merged:
            merged.append(p)
    cfg["skills_roots"] = merged
    cfg.pop("skills_root", None)
    save_user_config(cfg)
    return user_config_path(), merged


def merge_projects_roots_into_config(paths_str: list[str]) -> tuple[Path, list[str]]:
    """
    Écrit ``projects_roots`` dans ~/.config/zab/config.yaml (chemins uniques, résolus).
    Les entrées sous le répertoire personnel sont stockées en forme ``~/…``.
    Une liste vide enregistre ``projects_roots: []`` (découverte par projets désactivée).
    """
    cfg = load_user_config()
    cfg.pop("_error", None)
    merged_abs: list[str] = []
    for raw in paths_str:
        if not raw or not str(raw).strip():
            continue
        abs_p = str(Path(raw.strip()).expanduser().resolve())
        if abs_p not in merged_abs:
            merged_abs.append(abs_p)
    home = Path.home().resolve()
    yaml_list: list[str] = []
    for abs_p in merged_abs:
        p = Path(abs_p)
        try:
            rel = p.resolve().relative_to(home)
            yaml_list.append("~/" + str(rel).replace("\\", "/"))
        except ValueError:
            yaml_list.append(str(p.resolve()))
    cfg["projects_roots"] = yaml_list
    save_user_config(cfg)
    return user_config_path(), yaml_list


def skills_root_from_user_config() -> str | None:
    lst = skills_roots_strings_ordered()
    if lst:
        return lst[0]
    for md in skill_md_paths_resolved():
        from zab.services.inventory_config import infer_mcp_repo_base_from_skill_md

        base = infer_mcp_repo_base_from_skill_md(md)
        if base is not None:
            return str(base.resolve())
        return str(md.parent.resolve())
    return None


def local_tools_path_from_user_config() -> str | None:
    cfg = load_user_config()
    v = cfg.get("local_tools_path")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def cli_watchlist_from_user_config() -> list[str]:
    cfg = load_user_config()
    raw = cfg.get("cli_watchlist")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def merge_models_discovery_from_workspace_scan(scan: dict[str, Any]) -> Path:
    """
    Écrit ``models_discovery`` dans ~/.config/zab/config.yaml à partir du payload ``workspace_scan``.
    Ne supprime pas les autres clés (skills_roots, etc.).
    """
    cfg = load_user_config()
    cfg.pop("_error", None)
    ap = scan.get("agentpipe") if isinstance(scan.get("agentpipe"), dict) else {}
    cb = scan.get("codexbar") if isinstance(scan.get("codexbar"), dict) else {}

    agents_summ: list[dict[str, Any]] = []
    for a in ap.get("agents") or []:
        if not isinstance(a, dict):
            continue
        agents_summ.append(
            {
                "id": a.get("id"),
                "type": a.get("type"),
                "coding_models": a.get("coding_models") if isinstance(a.get("coding_models"), list) else [],
                "on_path": a.get("on_path"),
                "probe_binary": a.get("probe_binary"),
            }
        )

    cfg["models_discovery"] = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "agentpipe": {
            "config_path": ap.get("path"),
            "present": ap.get("present"),
            "coding_models_flat": ap.get("coding_models_flat") if isinstance(ap.get("coding_models_flat"), list) else [],
            "agents": agents_summ,
            "yaml_version": ap.get("yaml_version"),
            "cli_agentpipe_binary": ap.get("cli_agentpipe_binary"),
            "error": ap.get("error"),
        },
        "codexbar": {
            "config_path": cb.get("path"),
            "present": cb.get("present"),
            "top_level_keys": cb.get("top_level_keys") if isinstance(cb.get("top_level_keys"), list) else [],
            "cli_codexbar_binary": cb.get("cli_codexbar_binary"),
            "cli_probe": cb.get("cli_probe") if isinstance(cb.get("cli_probe"), dict) else {},
            "_error": cb.get("_error"),
        },
    }
    return save_user_config(cfg)


def tracked_env_extra_from_user_config() -> list[str]:
    cfg = load_user_config()
    raw = cfg.get("tracked_env_extra")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            v = item.strip()
            if v not in out:
                out.append(v)
    return out


def _as_str(v: Any) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _as_str_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for x in v:
        s = _as_str(x)
        if s and s not in out:
            out.append(s)
    return out


def task_sources_from_user_config() -> tuple[list[dict[str, Any]], list[str]]:
    """
    Lit ``task_sources`` depuis ~/.config/zab/config.yaml.

    Retourne (sources_validées, erreurs_de_validation) — une entrée invalide est ignorée avec message dans erreurs.
    """
    cfg = load_user_config()
    raw = cfg.get("task_sources")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["task_sources doit être une liste"]

    errors: list[str] = []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        prefix = f"task_sources[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: entrée ignorée (objet attendu)")
            continue
        sid = _as_str(item.get("id"))
        label = _as_str(item.get("label"))
        backend = (_as_str(item.get("backend")) or "").lower()
        if not sid:
            errors.append(f"{prefix}: id manquant")
            continue
        if not label:
            errors.append(f"{prefix} id={sid!r}: label manquant")
            continue
        if backend not in ("gitlab", "linear", "notion"):
            errors.append(f"{prefix} id={sid!r}: backend invalide (gitlab|linear|notion)")
            continue

        entry: dict[str, Any] = {
            "id": sid,
            "label": label,
            "backend": backend,
            "routing_doc": _as_str(item.get("routing_doc")),
            "mcp_hint": _as_str(item.get("mcp_hint")),
            "local_project_path": _as_str(item.get("local_project_path")),
        }

        env_token = _as_str(item.get("env_token"))
        if backend == "gitlab":
            default_t = "GITLAB_TOKEN"
            entry["env_token"] = env_token or default_t
            host = _as_str(item.get("host")) or "gitlab.com"
            entry["host"] = host
            pwn = _as_str(item.get("path_with_namespace"))
            pid = item.get("project_id")
            project_id: str | int | None
            if pid is not None and (isinstance(pid, (int, str)) and str(pid).strip()):
                project_id = int(pid) if isinstance(pid, str) and pid.isdigit() else pid
            else:
                project_id = None
            entry["path_with_namespace"] = pwn
            entry["project_id"] = project_id
            if not pwn and project_id is None:
                errors.append(f"{prefix} id={sid!r}: GitLab requiert path_with_namespace ou project_id")
                continue
            entry["assignee_username"] = _as_str(item.get("assignee_username"))
        elif backend == "linear":
            entry["env_token"] = env_token or "LINEAR_API_KEY"
            entry["team_keys"] = [k.upper() for k in _as_str_list(item.get("team_keys"))]
        else:
            entry["env_token"] = env_token or "NOTION_TOKEN"
            db = _as_str(item.get("database_id"))
            if not db:
                errors.append(f"{prefix} id={sid!r}: notion database_id manquant")
                continue
            entry["database_id"] = db
            entry["notion_title_prop"] = _as_str(item.get("notion_title_prop")) or "Name"

        out.append(entry)
    return out, errors


def tracked_env_names_for_security() -> tuple[str, ...]:
    from zab.secrets_catalog import ALL_TRACKED

    extra = tracked_env_extra_from_user_config()
    merged: list[str] = list(ALL_TRACKED)
    for x in extra:
        if x not in merged:
            merged.append(x)
    return tuple(merged)
