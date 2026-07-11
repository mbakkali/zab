"""Service de gestion et de synchronisation des canaux de communication (emails, WhatsApp, Slack, Telegram) avec support PostgreSQL."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml

from zab.paths import data_dir
from zab.user_config import load_user_config, save_user_config
from zab.services import obsidian_vault
from zab.services import postgres_store as local_db
from zab.services.memory_db import _url_or_none, _pg_connect_timeout, memory_psycopg_available
from zab.services.channel_fetchers import fetch_for_channel

CACHE_FILENAME = "channels_cache.json"

# Identifiants des anciens items mockés (avant le passage aux fetchers réels). On les purge
# à chaque sync s'ils traînent encore dans le cache local ou en base.
_LEGACY_MOCK_ACTION_IDS = {"act_mail_001", "act_mail_002", "act_whatsapp_001", "act_slack_001"}

DEFAULT_CHANNELS: list[dict[str, Any]] = []


def hermes_channels_snapshot(hermes_home: Path | None = None) -> dict[str, Any]:
    """Read Hermes channel configuration and discovered directory without mutating it."""
    root = (hermes_home or Path.home() / ".hermes").expanduser()
    config_path = root / "config.yaml"
    directory_path = root / "channel_directory.json"

    config: dict[str, Any] = {}
    config_error: str | None = None
    if config_path.is_file():
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            config = raw if isinstance(raw, dict) else {}
        except (OSError, yaml.YAMLError) as exc:
            config_error = str(exc)

    comm = config.get("communication_channels") if isinstance(config.get("communication_channels"), dict) else {}
    channels = comm.get("channels") if isinstance(comm, dict) and isinstance(comm.get("channels"), list) else []
    platform_toolsets = config.get("platform_toolsets") if isinstance(config.get("platform_toolsets"), dict) else {}
    platforms_cfg = config.get("platforms") if isinstance(config.get("platforms"), dict) else {}

    directory: dict[str, Any] = {}
    directory_error: str | None = None
    if directory_path.is_file():
        try:
            raw_dir = json.loads(directory_path.read_text(encoding="utf-8"))
            directory = raw_dir if isinstance(raw_dir, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            directory_error = str(exc)

    directory_platforms = directory.get("platforms") if isinstance(directory.get("platforms"), dict) else {}
    counts = {
        str(platform): len(entries) if isinstance(entries, list) else 0
        for platform, entries in directory_platforms.items()
    }

    return {
        "home": str(root),
        "config_path": str(config_path),
        "config_present": config_path.is_file(),
        "config_error": config_error,
        "enabled": bool(comm.get("enabled")) if isinstance(comm, dict) else False,
        "default_org": comm.get("default_org") if isinstance(comm, dict) else None,
        "channels": channels,
        "platform_toolsets": platform_toolsets,
        "platforms": platforms_cfg,
        "directory_path": str(directory_path),
        "directory_present": directory_path.is_file(),
        "directory_error": directory_error,
        "directory_updated_at": directory.get("updated_at"),
        "directory_counts": counts,
        "directory_platforms": directory_platforms,
    }


def ensure_postgres_channels_schema(conn) -> None:
    """S'assure de l'existence des tables zab_communication_channels et zab_dashboard_actions dans Postgres."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zab_communication_channels (
                id VARCHAR(128) PRIMARY KEY,
                label VARCHAR(255) NOT NULL,
                type VARCHAR(64) NOT NULL,
                connector VARCHAR(64) NOT NULL,
                org VARCHAR(64) NOT NULL,
                email_address VARCHAR(255),
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                status VARCHAR(64) DEFAULT 'ok',
                reason TEXT,
                last_synced_at VARCHAR(128),
                sync_summary JSONB,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zab_dashboard_actions (
                id VARCHAR(128) PRIMARY KEY,
                channel_id VARCHAR(128) NOT NULL REFERENCES zab_communication_channels(id) ON DELETE CASCADE,
                channel_label VARCHAR(255) NOT NULL,
                type VARCHAR(64) NOT NULL,
                sender VARCHAR(255) NOT NULL,
                subject VARCHAR(255),
                content TEXT NOT NULL,
                date TIMESTAMP WITH TIME ZONE NOT NULL,
                url TEXT,
                org VARCHAR(64) NOT NULL,
                status VARCHAR(64) NOT NULL DEFAULT 'pending',
                processed_at TIMESTAMP WITH TIME ZONE,
                obsidian_noted BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


def get_pg_connection() -> tuple[Any, str | None]:
    """Tente d'établir une connexion PostgreSQL et d'assurer le schéma. Retourne (conn, url) ou (None, None)."""
    if not memory_psycopg_available():
        return None, None
    url = _url_or_none()
    if not url:
        return None, None
    try:
        import psycopg
        conn = psycopg.connect(url, connect_timeout=_pg_connect_timeout())
        ensure_postgres_channels_schema(conn)
        return conn, url
    except Exception as e:
        print(f"[Channels PG] Impossible de se connecter à PostgreSQL : {e}")
        return None, None


def _legacy_pg_connection() -> tuple[Any | None, str | None]:
    """Compatibility hook for the pre-canonical-store channel tests/integrations."""

    hook_is_overridden = getattr(get_pg_connection, "__module__", __name__) != __name__
    if _url_or_none() and not hook_is_overridden:
        return None, None
    try:
        conn, url = get_pg_connection()
    except Exception:
        return None, None
    if conn is None or not url:
        return None, None
    return conn, url


def _row_get(row: Any, index: int, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[index]
    except (IndexError, TypeError):
        return default


def _legacy_channel_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": _row_get(row, 0, "id"),
        "label": _row_get(row, 1, "label"),
        "type": _row_get(row, 2, "type"),
        "connector": _row_get(row, 3, "connector"),
        "org": _row_get(row, 4, "org"),
        "email_address": _row_get(row, 5, "email_address"),
        "enabled": bool(_row_get(row, 6, "enabled", True)),
        "status": _row_get(row, 7, "status"),
        "reason": _row_get(row, 8, "reason"),
        "last_synced_at": _row_get(row, 9, "last_synced_at"),
        "sync_summary": _row_get(row, 10, "sync_summary"),
    }


def _legacy_action_from_row(row: Any) -> dict[str, Any]:
    date_value = _row_get(row, 7, "date")
    processed_at = _row_get(row, 11, "processed_at")
    return {
        "id": _row_get(row, 0, "id"),
        "channel_id": _row_get(row, 1, "channel_id"),
        "channel_label": _row_get(row, 2, "channel_label"),
        "type": _row_get(row, 3, "type"),
        "sender": _row_get(row, 4, "sender"),
        "subject": _row_get(row, 5, "subject"),
        "content": _row_get(row, 6, "content"),
        "date": date_value.isoformat() if hasattr(date_value, "isoformat") else date_value,
        "url": _row_get(row, 8, "url"),
        "org": _row_get(row, 9, "org"),
        "status": _row_get(row, 10, "status", "pending"),
        "processed_at": processed_at.isoformat() if hasattr(processed_at, "isoformat") else processed_at,
        "obsidian_noted": bool(_row_get(row, 12, "obsidian_noted", False)),
    }


def _legacy_load_channels(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, label, type, connector, org, email_address, enabled, status, reason, last_synced_at, sync_summary "
            "FROM zab_communication_channels ORDER BY org, label"
        )
        rows = cur.fetchall()
    return [_legacy_channel_from_row(row) for row in rows]


def _legacy_replace_channels(conn: Any, channels: list[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM zab_communication_channels")
        for channel in channels:
            cur.execute(
                "INSERT INTO zab_communication_channels "
                "(id, label, type, connector, org, email_address, enabled, status, reason, last_synced_at, sync_summary) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    channel.get("id"),
                    channel.get("label"),
                    channel.get("type"),
                    channel.get("connector"),
                    channel.get("org"),
                    channel.get("email_address"),
                    bool(channel.get("enabled", True)),
                    channel.get("status"),
                    channel.get("reason"),
                    channel.get("last_synced_at"),
                    channel.get("sync_summary"),
                ),
            )
    conn.commit()


def _legacy_update_channels(conn: Any, channels: list[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        for channel in channels:
            cur.execute(
                "UPDATE zab_communication_channels SET status = %s, reason = %s, last_synced_at = %s, sync_summary = %s WHERE id = %s",
                (
                    channel.get("status"),
                    channel.get("reason"),
                    channel.get("last_synced_at"),
                    channel.get("sync_summary"),
                    channel.get("id"),
                ),
            )
    conn.commit()


def _legacy_load_dashboard_actions(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, channel_id, channel_label, type, sender, subject, content, date, url, org, status, processed_at, obsidian_noted "
            "FROM zab_dashboard_actions ORDER BY updated_at DESC, id"
        )
        rows = cur.fetchall()
    return [_legacy_action_from_row(row) for row in rows]


def _legacy_replace_dashboard_actions(conn: Any, actions: list[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM zab_dashboard_actions")
        for action in actions:
            cur.execute(
                "INSERT INTO zab_dashboard_actions "
                "(id, channel_id, channel_label, type, sender, subject, content, date, url, org, status, processed_at, obsidian_noted) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    action.get("id"),
                    action.get("channel_id"),
                    action.get("channel_label"),
                    action.get("type"),
                    action.get("sender"),
                    action.get("subject"),
                    action.get("content"),
                    action.get("date"),
                    action.get("url"),
                    action.get("org"),
                    action.get("status"),
                    action.get("processed_at"),
                    bool(action.get("obsidian_noted", False)),
                ),
            )
    conn.commit()


def _legacy_update_dashboard_action(conn: Any, action_id: str, patch: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE zab_dashboard_actions SET status = %s, processed_at = %s, obsidian_noted = %s WHERE id = %s",
            (
                patch.get("status"),
                patch.get("processed_at"),
                bool(patch.get("obsidian_noted", False)),
                action_id,
            ),
        )
    conn.commit()


def _store_load_channels() -> list[dict[str, Any]]:
    conn, _ = _legacy_pg_connection()
    if conn is not None:
        return _legacy_load_channels(conn)
    return local_db.load_channels()


def _store_replace_channels(channels: list[dict[str, Any]]) -> None:
    conn, _ = _legacy_pg_connection()
    if conn is not None:
        _legacy_replace_channels(conn, channels)
        return
    local_db.replace_channels(channels)


def _store_update_channels(channels: list[dict[str, Any]]) -> None:
    conn, _ = _legacy_pg_connection()
    if conn is not None:
        _legacy_update_channels(conn, channels)
        return
    local_db.replace_channels(channels)


def _store_load_dashboard_actions() -> list[dict[str, Any]]:
    conn, _ = _legacy_pg_connection()
    if conn is not None:
        return _legacy_load_dashboard_actions(conn)
    return local_db.load_dashboard_actions()


def _store_replace_dashboard_actions(actions: list[dict[str, Any]]) -> None:
    conn, _ = _legacy_pg_connection()
    if conn is not None:
        _legacy_replace_dashboard_actions(conn, actions)
        return
    local_db.replace_dashboard_actions(actions)


def _store_get_dashboard_action(action_id: str) -> dict[str, Any] | None:
    actions = _store_load_dashboard_actions()
    return next((action for action in actions if action.get("id") == action_id), None)


def _store_update_dashboard_action(action_id: str, patch: dict[str, Any]) -> None:
    conn, _ = _legacy_pg_connection()
    if conn is not None:
        _legacy_update_dashboard_action(conn, action_id, patch)
        return
    local_db.update_dashboard_action(action_id, patch)


def load_channels_config() -> list[dict[str, Any]]:
    """Charge les canaux depuis Postgres canonique, puis importe config.yaml si vide."""
    local_channels = _store_load_channels()
    if local_channels:
        return local_channels

    local_channels = _load_local_channels_config()
    if local_channels:
        _store_replace_channels(local_channels)
    return local_channels


def _load_local_channels_config() -> list[dict[str, Any]]:
    """Charge les canaux configurés localement dans ~/.config/zab/config.yaml."""
    cfg = load_user_config()
    channels = cfg.get("communication_channels")
    if channels is None or not isinstance(channels, list) or len(channels) == 0:
        return DEFAULT_CHANNELS
    return channels


def save_channels_config(channels: list[dict[str, Any]]) -> None:
    """Enregistre les canaux dans Postgres canonique et config.yaml."""
    _store_replace_channels(channels)

    cfg = load_user_config()
    cfg["communication_channels"] = channels
    save_user_config(cfg)


def add_channel_config(
    label: str,
    channel_type: str,
    connector: str,
    email_address: str | None = None,
    org: str | None = None,
    *,
    documentation: str | None = None,
    credentials: dict[str, Any] | None = None,
    enabled: bool = True,
    channel_id: str | None = None,
) -> dict[str, Any]:
    """Ajoute un canal de communication à la configuration."""
    channels = load_channels_config()
    slug = channel_id or label.lower().replace(" ", "-").replace("(", "").replace(")", "")

    # Éviter les collisions d'IDs
    count = 1
    orig_id = slug
    while any(c.get("id") == slug for c in channels):
        slug = f"{orig_id}-{count}"
        count += 1

    new_chan: dict[str, Any] = {
        "id": slug,
        "label": label,
        "type": channel_type,
        "connector": connector,
        "org": org or "personal",
        "enabled": enabled,
    }
    if email_address:
        new_chan["email_address"] = email_address
    if documentation:
        new_chan["documentation"] = documentation
    if credentials:
        new_chan["credentials"] = credentials

    channels.append(new_chan)
    save_channels_config(channels)
    return new_chan


def check_channel_config(channel_id: str) -> dict[str, Any]:
    """Vérifie la connectivité d'un canal et persiste le résultat dans config.yaml."""
    from zab.services.channel_fetchers import check_channel_connection

    channels = load_channels_config()
    idx = next((i for i, c in enumerate(channels) if c.get("id") == channel_id), None)
    if idx is None:
        raise KeyError(channel_id)

    channel = channels[idx]
    now_dt = datetime.now(timezone.utc)
    result = check_channel_connection(channel, now_dt)

    updated: dict[str, Any] = {
        **channel,
        "status": result["status"],
        "reason": result.get("reason"),
        "last_synced_at": now_dt.isoformat(),
        "last_check_status": result["status"],
        "last_check_reason": result.get("reason"),
        "last_checked_at_utc": now_dt.isoformat(),
    }
    if result.get("sync_summary") is not None:
        updated["sync_summary"] = result["sync_summary"]

    channels[idx] = updated
    save_channels_config(channels)
    return updated


def get_channels_cache_path() -> Path:
    return data_dir() / CACHE_FILENAME


def fetch_channels_cache() -> dict[str, Any]:
    """Charge le cache de synchronisation ou déclenche une synchro si absent."""
    db_actions = _store_load_dashboard_actions()
    if db_actions:
        db_channels = _store_load_channels()
        return {
            "generated_at_utc": _iso_now(),
            "channels": db_channels,
            "action_items": db_actions,
            "total_actions_count": len([a for a in db_actions if a.get("status") == "pending"]),
        }
    p = get_channels_cache_path()
    if p.is_file():
        try:
            with p.open("r", encoding="utf-8") as f:
                cache = json.load(f)
            if isinstance(cache, dict):
                _store_replace_channels([x for x in cache.get("channels", []) if isinstance(x, dict)])
                _store_replace_dashboard_actions([x for x in cache.get("action_items", []) if isinstance(x, dict)])
                return cache
        except Exception:
            pass
    return sync_communication_channels()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_communication_channels() -> dict[str, Any]:
    """Déclenche la synchronisation de tous les canaux et consolide l'état (Postgres + local)."""
    channels = load_channels_config()
    now_dt = datetime.now(timezone.utc)
    
    # 1. Pour chaque canal, déclencher le fetcher réel correspondant (gog/composio/evolution).
    #    Le fetcher renvoie (actions, sync_summary, status, reason). En cas d'absence de
    #    credentials/CLI, on passe le canal en "degraded" sans inventer de données.
    synced_channels: list[dict[str, Any]] = []
    fetched_actions: list[dict[str, Any]] = []
    for c in channels:
        if not c.get("enabled", True):
            sync_info = {**c, "status": "disabled", "reason": "channel_disabled", "last_synced_at": now_dt.isoformat(), "sync_summary": {"unread_count": 0}}
            synced_channels.append(sync_info)
            continue

        try:
            actions, summary, status, reason = fetch_for_channel(c, now_dt)
        except Exception as exc:  # noqa: BLE001 — un canal cassé ne doit pas planter la sync globale
            actions, summary, status, reason = [], None, "error", f"fetcher_exception: {exc}"[:200]

        if summary is None:
            summary = {"unread_count": 0}

        sync_info = {
            **c,
            "status": status,
            "reason": reason,
            "last_synced_at": now_dt.isoformat(),
            "sync_summary": summary,
        }
        synced_channels.append(sync_info)
        fetched_actions.extend(actions)

    # Repli "démo" pour les environnements sans connecteurs (CI, démos, tests historiques).
    # Activé via ZAB_DEMO_CHANNELS=1 — par défaut désactivé pour ne pas masquer la réalité.
    demo_mode = os.environ.get("ZAB_DEMO_CHANNELS", "").strip() == "1"

    # 2. Charger les anciennes actions pour fusionner proprement
    old_actions = _store_load_dashboard_actions()

    # Purger les items mockés hérités d'avant le passage aux fetchers réels.
    if old_actions and not demo_mode:
        old_actions = [a for a in old_actions if a.get("id") not in _LEGACY_MOCK_ACTION_IDS]

    pending_actions = {a["id"]: a for a in old_actions if a.get("status") == "pending"}

    new_generated_actions: list[dict[str, Any]] = list(fetched_actions)

    if demo_mode and not new_generated_actions:
        # Données de démonstration (activées uniquement via ZAB_DEMO_CHANNELS=1).
        new_generated_actions = [
            {
                "id": "act_mail_001",
                "channel_id": "work-email",
                "channel_label": "Work Email",
                "type": "email",
                "sender": "Alex (Demo)",
                "subject": "[DEMO] Budget approval needed",
                "content": "Hi, please review the cloud budget request when you have a moment.",
                "date": (now_dt - timedelta(hours=2)).isoformat(),
                "url": "mailto:alex@example.com",
                "org": "demo",
                "is_actionable": True,
            },
            {
                "id": "act_mail_002",
                "channel_id": "work-email",
                "channel_label": "Work Email",
                "type": "email",
                "sender": "Sam (Demo)",
                "subject": "[DEMO] Onboarding forms incomplete",
                "content": "Hello, several onboarding forms are still blocked at step 3.",
                "date": (now_dt - timedelta(hours=5)).isoformat(),
                "url": "mailto:sam@example.com",
                "org": "demo",
                "is_actionable": True,
            },
            {
                "id": "act_whatsapp_001",
                "channel_id": "whatsapp-evo",
                "channel_label": "WhatsApp (Evolution API)",
                "type": "whatsapp",
                "sender": "[DEMO] Sarah",
                "subject": "Service alert",
                "content": "We are seeing HTTP 500 errors on the staging API since this morning.",
                "date": (now_dt - timedelta(minutes=45)).isoformat(),
                "url": "https://web.whatsapp.com/",
                "org": "demo",
                "is_actionable": True,
            },
            {
                "id": "act_slack_001",
                "channel_id": "slack-team",
                "channel_label": "Slack (Demo)",
                "type": "slack",
                "sender": "[DEMO] Jordan",
                "subject": "Cursor rules review",
                "content": "Can we merge the PR for the updated project rules?",
                "date": (now_dt - timedelta(hours=1, minutes=15)).isoformat(),
                "url": "https://slack.com",
                "org": "demo",
                "is_actionable": True,
            },
        ]

    # Fusionner en gardant l'état mis à jour par l'utilisateur si existant
    final_actions = []
    for action in new_generated_actions:
        aid = action["id"]
        if aid in pending_actions:
            final_actions.append(pending_actions[aid])
        else:
            was_processed = any(a["id"] == aid and a.get("status") != "pending" for a in old_actions)
            if not was_processed:
                action["status"] = "pending"
                final_actions.append(action)

    for aid, act in pending_actions.items():
        if not any(x["id"] == aid for x in final_actions):
            final_actions.append(act)

    result = {
        "generated_at_utc": _iso_now(),
        "channels": synced_channels,
        "action_items": final_actions,
        "total_actions_count": len([a for a in final_actions if a.get("status") == "pending"]),
    }

    # Export de compatibilité pour debug; Postgres reste canonique.
    p = get_channels_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    _store_update_channels(synced_channels)
    _store_replace_dashboard_actions(final_actions)

    return result


def dismiss_action_item(action_id: str) -> dict[str, Any]:
    """Marque une action à mener comme traitée (dismissed)."""
    cache = fetch_channels_cache()
    actions = cache.get("action_items", [])
    
    found = False
    for a in actions:
        if a.get("id") == action_id:
            a["status"] = "dismissed"
            a["processed_at"] = _iso_now()
            found = True
            break
    if found:
        _store_update_dashboard_action(
            action_id,
            {"status": "dismissed", "processed_at": _iso_now()},
        )
            
    if not found:
        raise KeyError(f"Action {action_id} inconnue")
        
    cache["total_actions_count"] = len([a for a in actions if a.get("status") == "pending"])
    
    # Sauvegarder
    p = get_channels_cache_path()
    with p.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, default=str)
    _store_replace_dashboard_actions([x for x in actions if isinstance(x, dict)])
        
    return cache


def convert_action_to_obsidian_task(action_id: str) -> dict[str, Any]:
    """Convertit une action à mener en tâche dans la Daily Note d'Obsidian et l'archive."""
    cache = fetch_channels_cache()
    actions = cache.get("action_items", [])
    
    target_action = None
    for a in actions:
        if a.get("id") == action_id:
            target_action = a
            break
            
    if target_action is None:
        target_action = _store_get_dashboard_action(action_id)

    if target_action is None:
        target_action = _store_get_dashboard_action(action_id)

    if target_action is None:
        raise KeyError(f"Action {action_id} inconnue")
        
    sender = target_action.get("sender", "Inconnu")
    subject = target_action.get("subject", "Action sans titre")
    channel_lbl = target_action.get("channel_label", "Canal inconnu")
    url = target_action.get("url", "")
    content_preview = target_action.get("content", "")[:120].strip().replace("\n", " ")
    if len(content_preview) > 120:
        content_preview += "..."

    markdown_task = f"- [ ] **Action ({channel_lbl})** de *{sender}* : {subject}  \n"
    if content_preview:
        markdown_task += f"  > {content_preview}  \n"
    if url:
        markdown_task += f"  > Source : [{url}]({url})  \n"

    # Appeler le service obsidian_vault pour ajouter la tâche
    daily_note_written = False
    error_msg = None
    try:
        obsidian_vault.daily_append(markdown_task)
        daily_note_written = True
    except Exception as e:
        error_msg = str(e)

    if not daily_note_written:
        raise RuntimeError(f"Erreur d'écriture dans le coffre Obsidian : {error_msg or 'vault_not_configured'}")

    for a in actions:
        if a.get("id") == action_id:
            a["status"] = "converted"
            a["processed_at"] = _iso_now()
            a["obsidian_noted"] = True
            break
    _store_update_dashboard_action(
        action_id,
        {"status": "converted", "processed_at": _iso_now(), "obsidian_noted": True},
    )
            
    cache["total_actions_count"] = len([a for a in actions if a.get("status") == "pending"])
    
    # Sauvegarder le cache local
    p = get_channels_cache_path()
    with p.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, default=str)
    _store_replace_dashboard_actions([x for x in actions if isinstance(x, dict)])
        
    return {
        "cache": cache,
        "obsidian_task_added": markdown_task,
    }
