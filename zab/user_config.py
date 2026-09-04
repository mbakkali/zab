"""Configuration utilisateur ~/.config/zab/config.yaml (skills_root, liste CLI manuelle)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.paths import config_dir

CONFIG_FILENAME = "config.yaml"
_USER_CONFIG_CACHE: tuple[str, int, int, dict[str, Any]] | None = None
DEFAULT_ORGANIZATION_SLUGS: tuple[str, ...] = ()

# Modèle écrit par ensure_user_config_exists() si ~/.config/zab/config.yaml est absent.
DEFAULT_USER_CONFIG_YAML = """# Configuration zab — fichier créé au premier lancement ou par install-zab-shell.sh
#
# Registre des skills (auto-créé) : ~/.config/zab/skills-registry.json
# (remplace l’ancienne liste skill_md_paths — voir docs/skills-registry-migration.md)
# skills_registry_path: ~/.config/zab/skills-registry.json

skills_roots: []

claude_plugin_paths: []

# Ancienne clé (optionnelle) : première entrée équivalente à skills_roots[0] si la liste est vide
# skills_root: ~/projects/skills
#
# Fichier local-tools (proxies LLM, cli_watchlist) — optionnel ; défaut : ~/.config/zab/local-tools.yaml
# local_tools_path: ~/.config/zab/local-tools.yaml

cli_watchlist: []

# Chemins optionnels — sinon défaut ~/.agentpipe.yaml et ~/.codexbar/config.json
# agentpipe_config_path: ~/.agentpipe.yaml
# codexbar_config_path: ~/.codexbar/config.json

# Rempli automatiquement lors d'un scan workspace persisté (``/api/scan?persist=1``) :
# models_discovery:
#   updated_at_utc: ...
#   agentpipe: { config_path, coding_models_flat, agents: [...] }
#   codexbar: { config_path, cli_probe: {...} }

# Dépôts « projets » (découverte skills .cursor / .claude). Si la clé est absente : ~/projects lorsqu’il existe.
# Liste vide [] = désactiver la découverte par projets.
# projects_roots:
#   - ~/projects

# Organisations métier fixes affichées dans le dashboard. Le scan rattache les projets à ces slugs,
# mais ne crée pas de nouvelles organisations depuis les catégories de skills.
# organizations:
#   - work
#   - personal
#   - clients

# Observabilité locale. Les logs restent redacted et écrits sous ~/.local/share/zab/logs par défaut.
# logging:
#   default_actor: mehdi

# Création/synchronisation optionnelle d'un dépôt personnel de skills.
# Par défaut, les opérations réseau restent explicites (`zab skill sync --push`).
# skills_sync:
#   repo_root: ~/projects/skills
#   git_remote: git@github.com:YOUR_USER/your-skills.git
#   hermes_config_path: ~/.hermes/config.yaml
#   auto_sync: false
#   auto_hermes_update: false
#   notify: false
#   notify_channel: evolution

# Vault Obsidian — exposé via le MCP zab (vault_list, vault_read, vault_search, daily_append, inbox_create).
# allow_full_write reste à false par défaut : seuls daily_append et inbox_create écrivent dans le vault.
# obsidian:
#   vault_path: ~/ObsidianVault
#   allow_full_write: false
#   daily_dir: 10_daily
#   inbox_dir: 00_inbox
#   daily_template: 90_meta/templates/daily.md

# Variables supplémentaires suivies (dashboard Sécurité), en plus du catalogue zab
tracked_env_extra: []

# Fichiers .env éditables et scannés par l’onglet Sécurité (chemins absolus ou ~).
# Si la clé est absente : première racine skills + ~/.hermes/.env + ~/.config/zab/.env
# security_env_paths:
#   - ~/projects/skills/.env
#   - ~/.hermes/.env

# Tâches agrégées : jetons GitLab / Linear / Notion — préférez ~/.config/zab/.env
# (fusion : zab pm-env sync ou bouton dans l’onglet Tâches). Ne mettez pas de secrets dans ce YAML.
# Liste task_sources pour GET /api/tasks/inbox — chaque entrée : id, label, backend (gitlab|linear|notion),
# routing_doc (chemin ou URL), mcp_hint (optionnel), local_project_path (optionnel),
# env_token (défaut GITLAB_TOKEN / LINEAR_API_KEY / NOTION_TOKEN).
# GitLab : host (défaut gitlab.com), path_with_namespace OU project_id ; optionnel assignee_username.
# Linear : optionnel team_keys (clés d’équipe).
# Notion : database_id ; notion_title_prop (défaut Name).
# task_sources: []

# Canaux de communication (dashboard Canaux). Vous pouvez inclure la config
# directement dans ce YAML, y compris les credentials par canal.
# Exemple WhatsApp Evolution API :
# communication_channels:
#   - id: whatsapp-evo
#     label: WhatsApp (Evolution API)
#     type: whatsapp
#     connector: evolution-api
#     org: work
#     enabled: true
#     documentation: https://doc.evolution-api.com/
#     credentials:
#       evolution_api_url: https://wa.example.com
#       evolution_api_key: VOTRE_CLE
#       evolution_instance: mon-instance
#   - id: slack-clients
#     label: Slack Clients
#     type: slack
#     connector: slack
#     org: clients
#     enabled: true
#     documentation: https://api.slack.com/authentication/token-types#bot
#     credentials:
#       slack_bot_token: xoxb-...
#       slack_channel_id: C01234567
#   - id: work-email
#     label: Work Email
#     type: email
#     connector: outlook
#     org: work
#     enabled: true
#     email_address: you@example.com
#     documentation: https://docs.composio.dev
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
    clear_user_config_cache()
    return p


def clear_user_config_cache() -> None:
    global _USER_CONFIG_CACHE
    _USER_CONFIG_CACHE = None


def load_user_config() -> dict[str, Any]:
    global _USER_CONFIG_CACHE
    p = user_config_path()
    if not p.is_file():
        _USER_CONFIG_CACHE = None
        return {}
    try:
        st = p.stat()
        cache_key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
    except OSError:
        _USER_CONFIG_CACHE = None
        return {"_error": "yaml_invalid", "path": str(p)}
    if _USER_CONFIG_CACHE is not None and _USER_CONFIG_CACHE[:3] == cache_key:
        return dict(_USER_CONFIG_CACHE[3])
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        data = raw if isinstance(raw, dict) else {}
        _USER_CONFIG_CACHE = (*cache_key, data)
        return dict(data)
    except (yaml.YAMLError, OSError):
        _USER_CONFIG_CACHE = None
        return {"_error": "yaml_invalid", "path": str(p)}


def save_user_config(data: dict[str, Any]) -> Path:
    p = user_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    clear_user_config_cache()
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


def organization_slugs_from_user_config() -> list[str]:
    """
    Organisations métier canoniques.

    La clé ``organizations`` accepte soit une liste de slugs, soit une liste
    d'objets ``{"slug": "..."}``. Si elle est absente, aucune organisation
    canonique n'est imposée. Les catégories du dépôt de skills ne sont pas
    des organisations.
    """
    cfg = load_user_config()
    raw = cfg.get("organizations")
    if raw is None:
        raw = cfg.get("workspace_orgs")
    if raw is None:
        return list(DEFAULT_ORGANIZATION_SLUGS)
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        slug = ""
        if isinstance(item, str):
            slug = item
        elif isinstance(item, dict):
            raw_slug = item.get("slug") or item.get("id") or item.get("name")
            if isinstance(raw_slug, str):
                slug = raw_slug
        slug = slug.strip().lower().replace(" ", "-")
        if slug and slug not in out:
            out.append(slug)
    return out


def organization_slug_set_from_user_config() -> set[str]:
    return set(organization_slugs_from_user_config())


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
    """Déprécié : chemins adoptés du registre skills (compat tests / ancien code)."""
    from zab.services import skills_registry

    return [str(p) for p in skills_registry.adopted_skill_md_paths_resolved()]


def skill_md_paths_resolved() -> list[Path]:
    from zab.services import skills_registry

    return skills_registry.adopted_skill_md_paths_resolved()


def register_skill_md_path(path: str | Path) -> Path:
    """Déprécié : utiliser skills_registry.register_mirror_skill_path."""
    from zab.services import skills_registry

    return skills_registry.register_mirror_skill_path(path)


def merge_scan_inventory_into_config(
    skill_md_abs_paths: list[str],
    *,
    claude_plugin_abs_paths: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Compat : alimente skills-registry.json (adopted) + claude_plugin_paths dans config.
    Ne réécrit plus skill_md_paths.
    """
    from zab.services import skills_registry
    from zab.services.inventory_config import collect_plugin_roots_from_skill_paths

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
    cfg = load_user_config()
    cfg.pop("_error", None)
    cfg["claude_plugin_paths"] = plugins_set
    cfg["skills_roots"] = []
    cfg.pop("skills_root", None)
    save_user_config(cfg)

    skills_registry.ensure_registry_and_migrate()
    doc = skills_registry.load_registry_document()
    by_key = {}
    for s in doc.get("skills") or []:
        if isinstance(s, dict) and s.get("key"):
            by_key[str(s["key"])] = s
    for abs_p in skills_set:
        md = Path(abs_p)
        if not md.is_file():
            continue
        slug = md.parent.name
        org = "hors-org"
        try:
            settings = skills_sync_settings()
            rr = Path(str(settings["repo_root"])).expanduser().resolve()
            hint = skills_registry.infer_org_slug_for_skill_file(md, rr)
            if hint:
                org = hint
        except OSError:
            pass
        key = f"{org.strip().lower()}:{slug.strip().lower()}"
        by_key[key] = {
            "key": key,
            "org": org,
            "slug": slug,
            "status": "adopted",
            "canonical_path": abs_p,
            "sources": [
                {
                    "kind": "config_legacy",
                    "path": abs_p,
                    "project": None,
                    "last_seen_at": skills_registry.utc_now_iso(),
                }
            ],
            "sync": {},
            "tags": [],
            "description": None,
            "frontmatter_name": None,
        }
    skills_registry.replace_skills_entries(by_key)
    summary = {"skill_md_paths": skills_set, "claude_plugin_paths": plugins_set}
    return user_config_path(), summary


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


def skills_sync_settings() -> dict[str, Any]:
    """Paramètres du dépôt de skills édité par `zab skill`.

    Les valeurs réseau/écriture automatique sont désactivées par défaut pour
    garder une étape de revue explicite avant publication ou modification Hermes.
    """

    cfg = load_user_config()
    raw = cfg.get("skills_sync")
    block = raw if isinstance(raw, dict) else {}
    roots = skills_roots_strings_ordered()
    default_root = roots[0] if roots else str(Path.home() / "projects" / "skills")
    repo_root = block.get("repo_root") if isinstance(block.get("repo_root"), str) and block.get("repo_root").strip() else default_root
    git_remote = (
        block.get("git_remote")
        if isinstance(block.get("git_remote"), str) and block.get("git_remote").strip()
        else ""
    )
    hermes_config_path = (
        block.get("hermes_config_path")
        if isinstance(block.get("hermes_config_path"), str) and block.get("hermes_config_path").strip()
        else str(Path.home() / ".hermes" / "config.yaml")
    )
    notify_raw = block.get("notify", False)
    notify = bool(notify_raw) if not isinstance(notify_raw, str) else notify_raw.strip().lower() in ("1", "true", "yes")
    notify_channel = block.get("notify_channel")
    ch = str(notify_channel).strip().lower() if isinstance(notify_channel, str) and notify_channel.strip() else "evolution"

    return {
        "repo_root": str(Path(str(repo_root)).expanduser()),
        "git_remote": str(git_remote),
        "hermes_config_path": str(Path(str(hermes_config_path)).expanduser()),
        "auto_sync": bool(block.get("auto_sync", False)),
        "auto_hermes_update": bool(block.get("auto_hermes_update", False)),
        "notify": notify,
        "notify_channel": ch if ch in ("evolution", "telegram") else "evolution",
    }


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


def primary_skills_dotenv_from_inventory() -> Path | None:
    """
    Déduit ``…/skills/.env`` à partir de ``skill_md_paths`` (ancêtre commun avec ``orgs/`` ou ``common/``).
    """
    mds = skill_md_paths_resolved()
    if not mds:
        return None
    try:
        common = Path(os.path.commonpath([str(m.resolve()) for m in mds]))
    except (ValueError, OSError):
        common = mds[0].resolve().parent
    cur = common
    for _ in range(16):
        if (cur / "orgs").is_dir() or (cur / "common").is_dir():
            return (cur / ".env").resolve()
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def security_env_paths_strings_ordered() -> list[str]:
    """
    Chemins .env pour l’onglet Sécurité (lecture / édition / scan de présence).

    Clé absente : défaut = dépôt skills déduit, ``~/.hermes/.env``, ``~/.config/zab/.env``.
    ``security_env_paths: []`` explicite : aucun fichier configuré.
    """
    cfg = load_user_config()
    if "security_env_paths" in cfg:
        return _as_str_list(cfg.get("security_env_paths"))
    out: list[str] = []
    inv = primary_skills_dotenv_from_inventory()
    if inv is not None:
        out.append(str(inv))
    for s in skills_roots_strings_ordered():
        candidate = f"{s.rstrip('/')}/.env"
        if candidate not in out:
            out.append(candidate)
    leg = cfg.get("skills_root")
    if isinstance(leg, str) and leg.strip():
        candidate = f"{leg.strip().rstrip('/')}/.env"
        if candidate not in out:
            out.append(candidate)
    out.append(str(Path.home() / ".hermes" / ".env"))
    out.append(str(config_dir() / ".env"))
    deduped: list[str] = []
    for item in out:
        if item not in deduped:
            deduped.append(item)
    return deduped


def security_env_paths_resolved() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for s in security_env_paths_strings_ordered():
        try:
            p = Path(s).expanduser().resolve()
        except OSError:
            continue
        if p.name != ".env":
            continue
        k = str(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


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
        if backend not in ("gitlab", "linear", "notion", "github"):
            errors.append(f"{prefix} id={sid!r}: backend invalide (gitlab|linear|notion|github)")
            continue

        entry: dict[str, Any] = {
            "id": sid,
            "label": label,
            "backend": backend,
            "routing_doc": _as_str(item.get("routing_doc")),
            "mcp_hint": _as_str(item.get("mcp_hint")),
            "local_project_path": _as_str(item.get("local_project_path")),
            "url": _as_str(item.get("url")),
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
        elif backend == "github":
            entry["env_token"] = env_token or "GITHUB_TOKEN"
            entry["repos"] = _as_str_list(item.get("repos"))
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
    """Les variables que le statut sécurité doit regarder.

    Trois sources, dans cet ordre : le catalogue interne, le registre de
    connecteurs déclaré en configuration, puis les ajouts de l'utilisateur.
    Le registre est ce qui manquait : `ATTIO_API_KEY` et `FIREFLIES_API_KEY`
    n'étaient dans aucun catalogue, alors que deux canaux du ledger en
    dépendent — le statut ne les regardait donc jamais.
    """
    from zab.secrets_catalog import ALL_TRACKED

    merged: list[str] = list(ALL_TRACKED)
    try:
        from zab.services.secrets_registry import tracked_names

        depuis_registre = tracked_names()
    except Exception:
        depuis_registre = []
    for x in list(depuis_registre) + list(tracked_env_extra_from_user_config()):
        if x not in merged:
            merged.append(x)
    return tuple(merged)
