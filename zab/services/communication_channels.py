"""Service de gestion et de synchronisation des canaux de communication (emails, WhatsApp, Slack, Telegram) avec support PostgreSQL."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from zab.paths import data_dir
from zab.user_config import load_user_config, save_user_config
from zab.services import obsidian_vault
from zab.services.memory_db import _url_or_none, _pg_connect_timeout, memory_psycopg_available
from zab.services.channel_fetchers import fetch_for_channel

CACHE_FILENAME = "channels_cache.json"

# Identifiants des anciens items mockés (avant le passage aux fetchers réels). On les purge
# à chaque sync s'ils traînent encore dans le cache local ou en base.
_LEGACY_MOCK_ACTION_IDS = {"act_mail_001", "act_mail_002", "act_whatsapp_001", "act_slack_001"}

DEFAULT_CHANNELS: list[dict[str, Any]] = []


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


def load_channels_config() -> list[dict[str, Any]]:
    """Charge les canaux configurés depuis PostgreSQL si disponible, sinon depuis ~/.config/zab/config.yaml."""
    conn, _ = get_pg_connection()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, label, type, connector, org, email_address, enabled, status, reason, last_synced_at, sync_summary
                        FROM zab_communication_channels
                        ORDER BY org, label ASC
                    """)
                    rows = cur.fetchall()
                    if rows:
                        channels = []
                        for r in rows:
                            channels.append({
                                "id": r[0],
                                "label": r[1],
                                "type": r[2],
                                "connector": r[3],
                                "org": r[4],
                                "email_address": r[5],
                                "enabled": r[6],
                                "status": r[7] or "ok",
                                "reason": r[8],
                                "last_synced_at": r[9],
                                "sync_summary": r[10] if isinstance(r[10], dict) else None,
                            })
                        return channels
                    else:
                        # La table existe mais est vide. On migre la config du fichier local.
                        local_channels = _load_local_channels_config()
                        for c in local_channels:
                            cur.execute("""
                                INSERT INTO zab_communication_channels (id, label, type, connector, org, email_address, enabled, status)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO NOTHING
                            """, (
                                c.get("id"),
                                c.get("label"),
                                c.get("type"),
                                c.get("connector"),
                                c.get("org", "personal"),
                                c.get("email_address"),
                                c.get("enabled", True),
                                "ok"
                            ))
                        conn.commit()
                        return local_channels
        except Exception as e:
            print(f"[Channels PG] Erreur lors de la lecture des canaux Postgres : {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Repli local
    return _load_local_channels_config()


def _load_local_channels_config() -> list[dict[str, Any]]:
    """Charge les canaux configurés localement dans ~/.config/zab/config.yaml."""
    cfg = load_user_config()
    channels = cfg.get("communication_channels")
    if channels is None or not isinstance(channels, list) or len(channels) == 0:
        return DEFAULT_CHANNELS
    return channels


def save_channels_config(channels: list[dict[str, Any]]) -> None:
    """Enregistre les canaux dans ~/.config/zab/config.yaml ET dans PostgreSQL si disponible."""
    # 1. Sauvegarde locale (fallback obligatoire)
    cfg = load_user_config()
    cfg["communication_channels"] = channels
    save_user_config(cfg)

    # 2. Sauvegarde PostgreSQL si disponible
    conn, _ = get_pg_connection()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    for c in channels:
                        cur.execute("""
                            INSERT INTO zab_communication_channels (id, label, type, connector, org, email_address, enabled)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                label = EXCLUDED.label,
                                type = EXCLUDED.type,
                                connector = EXCLUDED.connector,
                                org = EXCLUDED.org,
                                email_address = EXCLUDED.email_address,
                                enabled = EXCLUDED.enabled
                        """, (
                            c.get("id"),
                            c.get("label"),
                            c.get("type"),
                            c.get("connector"),
                            c.get("org", "personal"),
                            c.get("email_address"),
                            c.get("enabled", True)
                        ))
                    
                    # Supprimer de Postgres les canaux supprimés de la config
                    active_ids = [c.get("id") for c in channels if c.get("id")]
                    if active_ids:
                        cur.execute(
                            "DELETE FROM zab_communication_channels WHERE id NOT IN %s",
                            (tuple(active_ids),)
                        )
                    conn.commit()
        except Exception as e:
            print(f"[Channels PG] Erreur lors de l'écriture des canaux Postgres : {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass


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
    p = get_channels_cache_path()
    if p.is_file():
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
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
    old_actions = []
    conn, _ = get_pg_connection()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, channel_id, channel_label, type, sender, subject, content, date, url, org, status, processed_at, obsidian_noted
                        FROM zab_dashboard_actions
                    """)
                    rows = cur.fetchall()
                    for r in rows:
                        dt_val = r[7]
                        dt_str = dt_val.isoformat() if isinstance(dt_val, datetime) else str(dt_val)
                        proc_val = r[11]
                        proc_str = proc_val.isoformat() if isinstance(proc_val, datetime) else (str(proc_val) if proc_val else None)
                        
                        old_actions.append({
                            "id": r[0],
                            "channel_id": r[1],
                            "channel_label": r[2],
                            "type": r[3],
                            "sender": r[4],
                            "subject": r[5],
                            "content": r[6],
                            "date": dt_str,
                            "url": r[8],
                            "org": r[9],
                            "status": r[10],
                            "processed_at": proc_str,
                            "obsidian_noted": r[12] or False,
                        })
        except Exception as e:
            print(f"[Channels PG] Erreur lecture des actions Postgres durant sync : {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
    else:
        # Fallback local
        p = get_channels_cache_path()
        if p.is_file():
            try:
                with p.open("r", encoding="utf-8") as f:
                    old_cache = json.load(f)
                    old_actions = old_cache.get("action_items", [])
            except Exception:
                pass

    # Purger les items mockés hérités d'avant le passage aux fetchers réels.
    if old_actions and not demo_mode:
        old_actions = [a for a in old_actions if a.get("id") not in _LEGACY_MOCK_ACTION_IDS]
        conn_purge, _ = get_pg_connection()
        if conn_purge:
            try:
                with conn_purge:
                    with conn_purge.cursor() as cur:
                        cur.execute(
                            "DELETE FROM zab_dashboard_actions WHERE id = ANY(%s)",
                            (list(_LEGACY_MOCK_ACTION_IDS),),
                        )
                        conn_purge.commit()
            except Exception as e:
                print(f"[Channels PG] Erreur purge legacy mock actions : {e}")
            finally:
                try:
                    conn_purge.close()
                except Exception:
                    pass

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

    # Si connecté à Postgres, on enregistre les modifications
    conn, _ = get_pg_connection()
    if conn:
        try:
            from psycopg.types.json import Jsonb
            with conn:
                with conn.cursor() as cur:
                    # 1. Enregistrer l'état des canaux synchronisés
                    for s in synced_channels:
                        cur.execute("""
                            UPDATE zab_communication_channels SET
                                status = %s,
                                reason = %s,
                                last_synced_at = %s,
                                sync_summary = %s
                            WHERE id = %s
                        """, (
                            s.get("status"),
                            s.get("reason"),
                            s.get("last_synced_at"),
                            Jsonb(s.get("sync_summary") or {}),
                            s.get("id")
                        ))

                    # 2. Insérer les messages d'actions dans zab_dashboard_actions (sans écraser le statut utilisateur)
                    for a in final_actions:
                        # S'assurer que le canal existe en DB pour respecter la contrainte de clé étrangère
                        cur.execute("SELECT 1 FROM zab_communication_channels WHERE id = %s", (a["channel_id"],))
                        if not cur.fetchone():
                            cur.execute("""
                                INSERT INTO zab_communication_channels (id, label, type, connector, org, enabled)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT NOTHING
                            """, (
                                a["channel_id"],
                                a["channel_label"],
                                a["type"],
                                "gmail" if a["type"] == "email" else a["type"],
                                a["org"],
                                True
                            ))

                        try:
                            dt_obj = datetime.fromisoformat(a["date"])
                        except Exception:
                            dt_obj = now_dt

                        cur.execute("""
                            INSERT INTO zab_dashboard_actions (id, channel_id, channel_label, type, sender, subject, content, date, url, org, status, processed_at, obsidian_noted)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO NOTHING
                        """, (
                            a["id"],
                            a["channel_id"],
                            a["channel_label"],
                            a["type"],
                            a["sender"],
                            a.get("subject"),
                            a["content"],
                            dt_obj,
                            a.get("url"),
                            a["org"],
                            a.get("status", "pending"),
                            datetime.fromisoformat(a["processed_at"]) if a.get("processed_at") else None,
                            a.get("obsidian_noted", False)
                        ))

                    conn.commit()

                    # Recharger depuis la DB pour assurer une cohérence absolue
                    cur.execute("""
                        SELECT id, channel_id, channel_label, type, sender, subject, content, date, url, org, status, processed_at, obsidian_noted
                        FROM zab_dashboard_actions
                    """)
                    rows = cur.fetchall()
                    final_actions = []
                    for r in rows:
                        dt_val = r[7]
                        dt_str = dt_val.isoformat() if isinstance(dt_val, datetime) else str(dt_val)
                        proc_val = r[11]
                        proc_str = proc_val.isoformat() if isinstance(proc_val, datetime) else (str(proc_val) if proc_val else None)

                        final_actions.append({
                            "id": r[0],
                            "channel_id": r[1],
                            "channel_label": r[2],
                            "type": r[3],
                            "sender": r[4],
                            "subject": r[5],
                            "content": r[6],
                            "date": dt_str,
                            "url": r[8],
                            "org": r[9],
                            "status": r[10],
                            "processed_at": proc_str,
                            "obsidian_noted": r[12] or False,
                        })
        except Exception as e:
            print(f"[Channels PG] Erreur d'écriture/lecture durant sync : {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    result = {
        "generated_at_utc": _iso_now(),
        "channels": synced_channels,
        "action_items": final_actions,
        "total_actions_count": len([a for a in final_actions if a.get("status") == "pending"]),
    }

    # Toujours écrire dans le cache local (cohérence + repli instantané)
    p = get_channels_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def dismiss_action_item(action_id: str) -> dict[str, Any]:
    """Marque une action à mener comme traitée (dismissed)."""
    # 1. Mise à jour dans PostgreSQL si disponible
    conn, _ = get_pg_connection()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE zab_dashboard_actions SET
                            status = 'dismissed',
                            processed_at = %s
                        WHERE id = %s
                    """, (datetime.now(timezone.utc), action_id))
                    conn.commit()
        except Exception as e:
            print(f"[Channels PG] Erreur de dismiss Postgres : {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # 2. Mise à jour dans le cache local
    cache = fetch_channels_cache()
    actions = cache.get("action_items", [])
    
    found = False
    for a in actions:
        if a.get("id") == action_id:
            a["status"] = "dismissed"
            a["processed_at"] = _iso_now()
            found = True
            break
            
    if not found and not conn:
        raise KeyError(f"Action {action_id} inconnue")
        
    cache["total_actions_count"] = len([a for a in actions if a.get("status") == "pending"])
    
    # Sauvegarder
    p = get_channels_cache_path()
    with p.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        
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
        # Tenter de charger depuis la DB si présent
        conn, _ = get_pg_connection()
        if conn:
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, channel_id, channel_label, type, sender, subject, content, date, url, org, status
                            FROM zab_dashboard_actions WHERE id = %s
                        """, (action_id,))
                        row = cur.fetchone()
                        if row:
                            target_action = {
                                "id": row[0],
                                "channel_id": row[1],
                                "channel_label": row[2],
                                "type": row[3],
                                "sender": row[4],
                                "subject": row[5],
                                "content": row[6],
                                "date": row[7].isoformat() if isinstance(row[7], datetime) else str(row[7]),
                                "url": row[8],
                                "org": row[9],
                                "status": row[10]
                            }
            except Exception as e:
                print(f"[Channels PG] Erreur chargement action convert : {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

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

    # 1. Mettre à jour PostgreSQL si disponible
    conn, _ = get_pg_connection()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE zab_dashboard_actions SET
                            status = 'converted',
                            processed_at = %s,
                            obsidian_noted = TRUE
                        WHERE id = %s
                    """, (datetime.now(timezone.utc), action_id))
                    conn.commit()
        except Exception as e:
            print(f"[Channels PG] Erreur de convert Postgres : {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # 2. Mettre à jour le cache local
    for a in actions:
        if a.get("id") == action_id:
            a["status"] = "converted"
            a["processed_at"] = _iso_now()
            a["obsidian_noted"] = True
            break
            
    cache["total_actions_count"] = len([a for a in actions if a.get("status") == "pending"])
    
    # Sauvegarder le cache local
    p = get_channels_cache_path()
    with p.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        
    return {
        "cache": cache,
        "obsidian_task_added": markdown_task,
    }
