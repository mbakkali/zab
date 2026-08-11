"""Tests pour le module communication_channels, couvrant le repli local et les chemins PostgreSQL."""

import json
from datetime import datetime, timezone
from pathlib import Path


from zab.services import communication_channels as cc


# ==========================================
# CLASSES DE MOCK POUR PSYCOPG / POSTGRESQL
# ==========================================


def test_hermes_channels_snapshot_reads_config_and_directory(tmp_path: Path) -> None:
    hermes = tmp_path / ".hermes"
    hermes.mkdir()
    (hermes / "config.yaml").write_text(
        """
communication_channels:
  enabled: true
  default_org: personal
  channels:
    - id: telegram-personal
      label: Telegram
      type: telegram
      connector: telegram
      enabled: false
platform_toolsets:
  telegram:
    - hermes-telegram
""",
        encoding="utf-8",
    )
    (hermes / "channel_directory.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-06-09T10:00:00",
                "platforms": {
                    "telegram": [{"id": "123", "name": "Alex", "type": "dm"}],
                },
            }
        ),
        encoding="utf-8",
    )

    snap = cc.hermes_channels_snapshot(hermes)

    assert snap["enabled"] is True
    assert snap["channels"][0]["id"] == "telegram-personal"
    assert snap["platform_toolsets"]["telegram"] == ["hermes-telegram"]
    assert snap["directory_counts"] == {"telegram": 1}

class MockCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed_queries = []

    def execute(self, query, params=None):
        self.executed_queries.append((query, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class MockConnection:
    def __init__(self, rows=None):
        self.cursor_obj = MockCursor(rows)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


# ==========================================
# TESTS CLASSIQUES (FALLBACKS LOCAUX)
# ==========================================

def test_load_channels_config_defaults(monkeypatch) -> None:
    """Returns an empty channel list when none are configured."""
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (None, None))
    monkeypatch.setattr("zab.services.communication_channels.load_user_config", lambda: {})

    channels = cc.load_channels_config()
    assert channels == []


def test_save_channels_config_local(monkeypatch) -> None:
    """Vérifie l'enregistrement local de la configuration (fallback)."""
    # Désactiver PostgreSQL
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (None, None))
    
    saved_data = {}
    
    def mock_load():
        return {}
        
    def mock_save(data):
        nonlocal saved_data
        saved_data = data
        return Path("/mock/config.yaml")
        
    monkeypatch.setattr("zab.services.communication_channels.load_user_config", mock_load)
    monkeypatch.setattr("zab.services.communication_channels.save_user_config", mock_save)
    
    test_channels = [{"id": "test-chan", "label": "Test Channel"}]
    cc.save_channels_config(test_channels)
    
    assert saved_data.get("communication_channels") == test_channels


def test_add_channel_config(monkeypatch) -> None:
    """Vérifie l'ajout d'un canal."""
    # Désactiver PostgreSQL
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (None, None))
    
    current_config = {"communication_channels": []}
    
    def mock_load():
        return current_config
        
    def mock_save(data):
        nonlocal current_config
        current_config = data
        return Path("/mock/config.yaml")
        
    monkeypatch.setattr("zab.services.communication_channels.load_user_config", mock_load)
    monkeypatch.setattr("zab.services.communication_channels.save_user_config", mock_save)
    
    new_chan = cc.add_channel_config(
        label="Nouveau Slack Client",
        channel_type="slack",
        connector="slack",
        org="client-abc"
    )
    
    assert new_chan["id"] == "nouveau-slack-client"
    assert new_chan["label"] == "Nouveau Slack Client"
    assert new_chan["type"] == "slack"
    assert new_chan["connector"] == "slack"
    assert new_chan["org"] == "client-abc"
    
    # Vérifier l'unicité de l'ID en cas de doublon de label
    second_chan = cc.add_channel_config(
        label="Nouveau Slack Client",
        channel_type="slack",
        connector="slack"
    )
    assert second_chan["id"] == "nouveau-slack-client-1"


def _stub_fetcher(action_id: str = "act_stub_001", subject: str = "Stub subject"):
    """Fabrique un fetcher déterministe pour les tests."""
    def _fn(channel, now_dt):
        action = {
            "id": action_id,
            "channel_id": channel.get("id"),
            "channel_label": channel.get("label"),
            "type": channel.get("type", "email"),
            "sender": "Stub Sender",
            "subject": subject,
            "content": "Contenu stub",
            "date": now_dt.isoformat(),
            "url": "mailto:stub@example.com",
            "org": channel.get("org", "test"),
            "is_actionable": True,
        }
        summary = {"unread_count": 1, "received_today": 1, "received_this_week": 1}
        return [action], summary, "ok", None
    return _fn


def test_sync_communication_channels_local(monkeypatch, tmp_path) -> None:
    """Vérifie la synchronisation et la persistance locale du cache (fallback)."""
    # Désactiver PostgreSQL
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (None, None))

    # Configurer un répertoire de données de test temporaire pour le cache
    test_cache_path = tmp_path / "channels_cache.json"
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)

    # Mocker load_user_config pour avoir un canal connu
    monkeypatch.setattr("zab.services.communication_channels.load_user_config", lambda: {
        "communication_channels": [
            {"id": "work-email", "label": "Flowmetrik Email", "type": "email", "connector": "outlook", "org": "flowmetrik"}
        ]
    })

    # Stub du fetcher réel pour ne pas dépendre de gog/composio/Evolution en test.
    monkeypatch.setattr("zab.services.communication_channels.fetch_for_channel", _stub_fetcher())

    result = cc.sync_communication_channels()

    assert "generated_at_utc" in result
    assert len(result["channels"]) == 1
    assert result["channels"][0]["id"] == "work-email"
    assert "sync_summary" in result["channels"][0]
    assert result["channels"][0]["status"] == "ok"
    assert len(result["action_items"]) > 0
    assert result["total_actions_count"] > 0

    assert test_cache_path.is_file()
    with test_cache_path.open("r", encoding="utf-8") as f:
        cached_data = json.load(f)
    assert cached_data["generated_at_utc"] == result["generated_at_utc"]


def test_sync_communication_channels_degraded(monkeypatch, tmp_path) -> None:
    """Sans fetcher configuré, le canal doit passer en 'degraded' sans inventer d'actions."""
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (None, None))
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    monkeypatch.setattr("zab.services.communication_channels.load_user_config", lambda: {
        "communication_channels": [
            {"id": "work-email", "label": "Flowmetrik Email", "type": "email", "connector": "gmail", "email_address": "x@y.z", "org": "flowmetrik"}
        ]
    })

    def _degraded(channel, now_dt):
        return [], None, "degraded", "no_creds"

    monkeypatch.setattr("zab.services.communication_channels.fetch_for_channel", _degraded)
    monkeypatch.delenv("ZAB_DEMO_CHANNELS", raising=False)

    result = cc.sync_communication_channels()
    assert result["channels"][0]["status"] == "degraded"
    assert result["channels"][0]["reason"] == "no_creds"
    assert result["action_items"] == []
    assert result["total_actions_count"] == 0


def test_dismiss_action_item_local(monkeypatch, tmp_path) -> None:
    """Vérifie le marquage d'un message comme traité (dismiss) localement."""
    # Désactiver PostgreSQL
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (None, None))
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    monkeypatch.setattr("zab.services.communication_channels.fetch_for_channel", _stub_fetcher())

    # Lancer une sync pour initialiser le cache
    cc.sync_communication_channels()
    
    cache = cc.fetch_channels_cache()
    action_id = cache["action_items"][0]["id"]
    assert cache["action_items"][0]["status"] == "pending"
    
    updated_cache = cc.dismiss_action_item(action_id)
    
    action_updated = next(a for a in updated_cache["action_items"] if a["id"] == action_id)
    assert action_updated["status"] == "dismissed"
    assert "processed_at" in action_updated
    assert updated_cache["total_actions_count"] == cache["total_actions_count"] - 1


def test_convert_action_to_obsidian_task_local(monkeypatch, tmp_path) -> None:
    """Vérifie la conversion en tâche Obsidian localement."""
    # Désactiver PostgreSQL
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (None, None))
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    monkeypatch.setattr("zab.services.communication_channels.fetch_for_channel", _stub_fetcher())

    cc.sync_communication_channels()
    cache = cc.fetch_channels_cache()
    action_id = cache["action_items"][0]["id"]
    
    daily_append_called = False
    appended_text = ""
    
    def mock_daily_append(text, *args, **kwargs):
        nonlocal daily_append_called, appended_text
        daily_append_called = True
        appended_text = text
        return Path("/mock/daily.md")
        
    monkeypatch.setattr("zab.services.obsidian_vault.daily_append", mock_daily_append)
    
    res = cc.convert_action_to_obsidian_task(action_id)
    
    assert daily_append_called is True
    assert "- [ ]" in appended_text
    
    updated_cache = res["cache"]
    action_updated = next(a for a in updated_cache["action_items"] if a["id"] == action_id)
    assert action_updated["status"] == "converted"
    assert action_updated.get("obsidian_noted") is True


# ==========================================
# TESTS AVEC MOCK POSTGRESQL (MODE CONNECTÉ)
# ==========================================

def test_load_channels_config_postgres(monkeypatch) -> None:
    """Vérifie que la configuration charge bien les canaux depuis PostgreSQL."""
    mock_db_rows = [
        ("work-email", "Work Email", "email", "outlook", "demo", "you@example.com", True, "ok", None, "2026-05-22", {"unread_count": 5})
    ]
    mock_conn = MockConnection(mock_db_rows)
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (mock_conn, "postgresql://mock"))

    channels = cc.load_channels_config()
    assert len(channels) == 1
    assert channels[0]["id"] == "work-email"
    assert channels[0]["label"] == "Work Email"
    assert channels[0]["sync_summary"] == {"unread_count": 5}
    assert mock_conn.cursor_obj.executed_queries[0][0].strip().startswith("SELECT id, label, type, connector")


def test_save_channels_config_postgres(monkeypatch) -> None:
    """Vérifie que la configuration s'écrit dans PostgreSQL."""
    mock_conn = MockConnection()
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (mock_conn, "postgresql://mock"))
    
    # Mocker load_user_config / save_user_config pour le fallback local
    monkeypatch.setattr("zab.services.communication_channels.load_user_config", lambda: {})
    monkeypatch.setattr("zab.services.communication_channels.save_user_config", lambda x: None)

    test_channels = [
        {"id": "work-email", "label": "Work Email", "type": "email", "connector": "outlook", "org": "demo", "email_address": "you@example.com", "enabled": True}
    ]
    cc.save_channels_config(test_channels)

    assert mock_conn.committed is True
    # Vérifier qu'on a exécuté l'INSERT et le DELETE
    queries = [q[0].strip() for q in mock_conn.cursor_obj.executed_queries]
    assert any(q.startswith("INSERT INTO zab_communication_channels") for q in queries)
    assert any(q.startswith("DELETE FROM zab_communication_channels") for q in queries)


def test_sync_communication_channels_postgres(monkeypatch, tmp_path) -> None:
    """Vérifie que la synchronisation enregistre bien l'état et les actions dans PostgreSQL."""
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)

    # Simuler des anciennes actions vides, puis simuler la lecture après insertion
    mock_db_rows = []  # Pour la première lecture
    mock_conn = MockConnection(mock_db_rows)
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (mock_conn, "postgresql://mock"))

    # Mocker load_user_config
    monkeypatch.setattr("zab.services.communication_channels.load_user_config", lambda: {
        "communication_channels": [
            {"id": "work-email", "label": "Flowmetrik Email", "type": "email", "connector": "outlook", "org": "flowmetrik"}
        ]
    })

    # Stub du fetcher pour ne pas appeler de vraie CLI / API en test.
    monkeypatch.setattr("zab.services.communication_channels.fetch_for_channel", _stub_fetcher(action_id="act_mail_001", subject="Validation"))

    # Simuler qu'au rechargement final (après l'écriture des messages dans sync), le fetchall renvoie nos messages
    def mock_fetchall():
        return [
            ("act_mail_001", "work-email", "Flowmetrik Email", "email", "Yassine", "Validation", "Content", datetime.now(timezone.utc), "mailto:", "flowmetrik", "pending", None, False)
        ]
    mock_conn.cursor_obj.fetchall = mock_fetchall

    result = cc.sync_communication_channels()
    
    assert mock_conn.committed is True
    assert len(result["action_items"]) == 1
    assert result["action_items"][0]["id"] == "act_mail_001"

    # Vérifier l'insertion
    queries = [q[0].strip() for q in mock_conn.cursor_obj.executed_queries]
    assert any(q.startswith("UPDATE zab_communication_channels SET") for q in queries)
    assert any(q.startswith("INSERT INTO zab_dashboard_actions") for q in queries)


def test_dismiss_action_item_postgres(monkeypatch, tmp_path) -> None:
    """Vérifie que le dismiss met à jour le statut dans PostgreSQL."""
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    
    mock_conn = MockConnection()
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (mock_conn, "postgresql://mock"))
    monkeypatch.setattr("zab.services.communication_channels.fetch_for_channel", _stub_fetcher(action_id="act_mail_001", subject="Validation"))

    # Simuler des retours de base de données pour avoir l'item d'action
    def mock_fetchall():
        return [
            ("act_mail_001", "work-email", "Flowmetrik Email", "email", "Yassine", "Validation", "Content", datetime.now(timezone.utc), "mailto:", "flowmetrik", "pending", None, False)
        ]
    mock_conn.cursor_obj.fetchall = mock_fetchall
    mock_conn.cursor_obj.rows = [
        ("act_mail_001", "work-email", "Flowmetrik Email", "email", "Yassine", "Validation", "Content", datetime.now(timezone.utc), "mailto:", "flowmetrik", "pending", None, False)
    ]

    # Initialiser le cache local également pour que fetch_channels_cache ne lève pas d'erreur
    cc.sync_communication_channels()

    cc.dismiss_action_item("act_mail_001")
    
    assert mock_conn.committed is True
    queries = [q[0].strip() for q in mock_conn.cursor_obj.executed_queries]
    assert any(q.startswith("UPDATE zab_dashboard_actions SET") for q in queries)


def test_convert_action_to_obsidian_task_postgres(monkeypatch, tmp_path) -> None:
    """Vérifie que la conversion met à jour le statut dans PostgreSQL et écrit dans Obsidian."""
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    
    mock_conn = MockConnection()
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (mock_conn, "postgresql://mock"))
    monkeypatch.setattr("zab.services.communication_channels.fetch_for_channel", _stub_fetcher(action_id="act_mail_001", subject="Validation"))

    # Simuler des retours de base de données pour avoir l'item d'action
    def mock_fetchall():
        return [
            ("act_mail_001", "work-email", "Flowmetrik Email", "email", "Yassine", "Validation", "Content", datetime.now(timezone.utc), "mailto:", "flowmetrik", "pending", None, False)
        ]
    mock_conn.cursor_obj.fetchall = mock_fetchall
    mock_conn.cursor_obj.rows = [
        ("act_mail_001", "work-email", "Flowmetrik Email", "email", "Yassine", "Validation", "Content", datetime.now(timezone.utc), "mailto:", "flowmetrik", "pending", None, False)
    ]

    # Initialiser le cache local pour qu'on trouve l'action
    cc.sync_communication_channels()

    daily_append_called = False
    def mock_daily_append(text):
        nonlocal daily_append_called
        daily_append_called = True
        return Path("/mock/daily.md")

    monkeypatch.setattr("zab.services.obsidian_vault.daily_append", mock_daily_append)

    cc.convert_action_to_obsidian_task("act_mail_001")

    assert mock_conn.committed is True
    assert daily_append_called is True
    queries = [q[0].strip() for q in mock_conn.cursor_obj.executed_queries]
    assert any("UPDATE zab_dashboard_actions SET" in q for q in queries)
