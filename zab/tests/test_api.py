from pathlib import Path
import json

from fastapi.testclient import TestClient

from zab.api.app import create_app


def test_health():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_system_check_api():
    client = TestClient(create_app())
    r = client.get("/api/system/check")
    assert r.status_code == 200
    data = r.json()
    assert 0 <= data["percentage"] <= 100
    assert data["total"] >= 1
    assert isinstance(data["checks"], list)
    ids = {row["id"] for row in data["checks"]}
    assert {"config_yaml", "skills_root", "state_index", "cli_tools"} <= ids
    assert all(row["status"] in {"ok", "warn", "fail"} for row in data["checks"])


def test_system_check_stream():
    client = TestClient(create_app())
    r = client.get("/api/system/check/stream")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    text = r.text

    # Parse SSE events
    events: dict[str, list[dict]] = {}
    current_event = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            current_event = line[7:].strip()
            events.setdefault(current_event, [])
        elif line.startswith("data: ") and current_event:
            import json
            events[current_event].append(json.loads(line[6:]))

    # Must have registry, at least one check, and done
    assert "registry" in events
    assert "check" in events
    assert "done" in events
    assert len(events["registry"]) == 1
    registry = events["registry"][0]
    assert isinstance(registry, list)
    assert len(registry) >= 1
    assert all("id" in d and "label" in d and "category" in d for d in registry)

    assert len(events["check"]) >= 1
    for chk in events["check"]:
        assert chk["status"] in {"ok", "warn", "fail"}
        assert "id" in chk

    done = events["done"][0]
    assert 0 <= done["percentage"] <= 100
    assert done["total"] >= 1


def test_system_check_last_api(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app())
    r0 = client.get("/api/system/check/last")
    assert r0.status_code == 200
    assert r0.json()["present"] is False

    report = {
        "generated_at_utc": "2026-05-28T19:00:00+00:00",
        "percentage": 100,
        "score": 12.0,
        "total": 12,
        "ok": 12,
        "warn": 0,
        "fail": 0,
        "checks": [],
    }
    r1 = client.post("/api/system/check/last", json={"report": report})
    assert r1.status_code == 200
    assert r1.json()["saved"] is True

    r2 = client.get("/api/system/check/last")
    assert r2.status_code == 200
    data = r2.json()
    assert data["present"] is True
    assert data["report"]["percentage"] == 100
    assert data["saved_at_utc"]


def test_overview():
    client = TestClient(create_app())
    r = client.get("/api/overview")
    assert r.status_code == 200
    data = r.json()
    assert "orgs" in data
    assert "projects" in data
    assert "projects_roots" in data
    assert isinstance(data["projects"], list)
    assert "mcp_configs" in data
    assert data.get("skills_root_configured") is True
    assert isinstance(data.get("skills_root"), str)
    assert len(data["skills_root"]) > 0
    assert "user_config_path" in data
    assert data.get("skills_root_yaml_raw")


def test_tasks_inbox():
    client = TestClient(create_app())
    r = client.get("/api/tasks/inbox")
    assert r.status_code == 200
    data = r.json()
    assert "sources" in data and isinstance(data["sources"], list)
    assert "parse_errors" in data and isinstance(data["parse_errors"], list)
    assert "env_hints" in data and isinstance(data["env_hints"], dict)
    assert "generated_at_utc" in data


def test_connectors_api():
    client = TestClient(create_app())
    r = client.get("/api/connectors?limit=10")
    assert r.status_code == 200
    data = r.json()
    assert "data" in data and "pagination" in data
    assert isinstance(data["data"], list)
    if not data["data"]:
        return
    slug = str(data["data"][0]["id"])
    r2 = client.get(f"/api/connectors/{slug}")
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["id"] == slug


def test_connectors_api_404():
    client = TestClient(create_app())
    r = client.get("/api/connectors/nonexistent-slug-xyz123")
    assert r.status_code == 404


def test_state_api_and_sync():
    client = TestClient(create_app())
    r = client.post("/api/sync")
    assert r.status_code == 200
    data = r.json()
    assert data["version"]
    assert "counts" in data
    r2 = client.get("/api/state")
    assert r2.status_code == 200
    assert r2.json()["counts"]["connectors"] >= 0


def test_features_and_agent_guide_api():
    client = TestClient(create_app())
    r = client.get("/api/features")
    assert r.status_code == 200
    assert isinstance(r.json().get("features"), list)
    g = client.get("/api/agent-guide")
    assert g.status_code == 200
    assert "bootstrap_commands" in g.json()


def test_index_sections_and_context_pack():
    client = TestClient(create_app())
    assert client.post("/api/sync").status_code == 200
    for path in ("/api/skills?limit=5", "/api/code-tools?limit=5", "/api/tools?limit=5", "/api/models?limit=5"):
        r = client.get(path)
        assert r.status_code == 200
        payload = r.json()
        assert "data" in payload and "pagination" in payload
    cp = client.post("/api/context-pack", json={"limit": 5})
    assert cp.status_code == 200
    data = cp.json()
    assert data["bytes"] > 0
    assert "zab Context Pack" in data["preview"]
    assert "## Tools Catalog" in data["preview"]


def test_tools_catalog_api():
    client = TestClient(create_app())
    catalog = client.get("/api/tools/catalog")
    assert catalog.status_code == 200
    catalog_payload = catalog.json()
    assert catalog_payload["contract"] == "tools-catalog"
    assert isinstance(catalog_payload["tools"], list)
    assert catalog_payload["summary"]["total"] == len(catalog_payload["tools"])
    assert any(tool["id"] == "gmail-search" for tool in catalog_payload["tools"])

    detail = client.get("/api/tools/gmail-search")
    assert detail.status_code == 200
    assert detail.json()["tool"]["id"] == "gmail-search"

    search = client.get("/api/tools/search?q=gmail&limit=5")
    assert search.status_code == 200
    assert search.json()["contract"] == "tools-catalog-search"

    validate = client.get("/api/tools/validate")
    assert validate.status_code == 200
    validate_payload = validate.json()
    assert validate_payload["contract"] == "tools-catalog-validation"
    assert validate_payload["summary"]["total_tools"] >= 1

    check = client.get("/api/tools/check?tool_id=gmail-search")
    assert check.status_code == 200
    check_payload = check.json()
    assert check_payload["contract"] == "tools-check"
    assert check_payload["tool_id"] == "gmail-search"


def test_agent_search_and_security_api():
    client = TestClient(create_app())
    boot = client.get("/api/agent/bootstrap")
    assert boot.status_code == 200
    assert boot.json()["contract"] == "agent-bootstrap"

    search = client.get("/api/search?q=skills&limit=5")
    assert search.status_code == 200
    assert search.json()["query"] == "skills"
    assert "data" in search.json()

    skills_manifest = client.get("/api/agent/skills?limit=5")
    assert skills_manifest.status_code == 200
    assert skills_manifest.json()["contract"] == "skills-manifest"

    sec = client.get("/api/security/status")
    assert sec.status_code == 200
    assert sec.json()["policy"]["secrets"] == "never_print_raw_values"


def test_agent_handoff_api(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "projects"
    project = root / "demo"
    project.mkdir(parents=True)
    (project / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"projects_roots": [str(root)], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    assert client.post("/api/sync").status_code == 200
    r = client.post("/api/agent/handoff", json={"project": "demo", "limit": 5})
    assert r.status_code == 200
    assert r.json()["project"]["name"] == "demo"


def test_config_files_api():
    client = TestClient(create_app())
    r = client.get("/api/config/files")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    keys = {row["key"] for row in rows}
    assert keys == {"user_zab_config"}
    assert rows[0]["path_display"].startswith("~/.config/zab/config.yaml")


def test_config_file_one_key():
    client = TestClient(create_app())
    r = client.get("/api/config/file?key=cursor_mcp_json")
    assert r.status_code == 200
    payload = r.json()
    assert "path_display" in payload
    assert "content" in payload


def test_config_file_bad_key():
    client = TestClient(create_app())
    r = client.get("/api/config/file?key=../../../etc/passwd")
    assert r.status_code == 400


def test_config_history_api():
    client = TestClient(create_app())
    r = client.get("/api/config/history")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert {row["key"] for row in rows} >= {"user_zab_config", "local_tools_actual", "scan_last"}
    assert all("path_display" in row and "exists" in row for row in rows)


def test_config_sync_status_api():
    from zab.paths import config_dir, data_dir

    cfg = config_dir()
    data = data_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    (data / "state.yaml").write_text(
        "version: '2.1'\nlast_sync_at: '2026-07-13T10:00:00+00:00'\n",
        encoding="utf-8",
    )
    (data / "scan-last.yaml").write_text(
        "saved_at_utc: '2026-07-13T09:00:00+00:00'\nscan: {}\n",
        encoding="utf-8",
    )
    (cfg / "skills-registry.json").write_text(
        json.dumps({"version": 1, "updated_at": "2026-07-13T11:00:00+00:00", "skills": []}),
        encoding="utf-8",
    )
    (cfg / "mcp-registry.json").write_text(
        json.dumps({"version": 1, "updated_at": "2026-07-13T08:30:00+00:00", "servers": {}}),
        encoding="utf-8",
    )
    (data / "tasks_cache.json").write_text(
        json.dumps(
            {
                "generated_at_utc": "2026-07-13T12:00:00+00:00",
                "sources": [{"id": "linear-main", "status": "ok"}],
                "all_tasks": [],
            }
        ),
        encoding="utf-8",
    )
    (data / "channels_cache.json").write_text(
        json.dumps(
            {
                "generated_at_utc": "2026-07-13T12:15:00+00:00",
                "channels": [
                    {
                        "id": "work-email",
                        "status": "ok",
                        "last_synced_at": "2026-07-13T12:10:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with (cfg / "config.yaml").open("a", encoding="utf-8") as f:
        f.write("\ncustom_block:\n  enabled: true\n")

    client = TestClient(create_app())
    r = client.get("/api/config/sync-status")
    assert r.status_code == 200
    payload = r.json()
    assert payload["sections"]["skills_roots"]["last_synced_at"] == "2026-07-13T11:00:00+00:00"
    assert payload["sections"]["task_sources"]["last_synced_at"] == "2026-07-13T12:00:00+00:00"
    assert payload["sections"]["communication_channels"]["last_synced_at"] == "2026-07-13T12:15:00+00:00"
    assert payload["sections"]["custom_block"]["last_synced_at"] == "2026-07-13T10:00:00+00:00"
    assert payload["items"]["task_sources"]["linear-main"]["last_synced_at"] == "2026-07-13T12:00:00+00:00"
    assert payload["items"]["communication_channels"]["work-email"]["last_synced_at"] == "2026-07-13T12:10:00+00:00"


def test_security_env_file_roundtrip(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "sr"
    repo.mkdir()
    (repo / "configs").mkdir(parents=True)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"skills_roots": [str(repo.resolve())], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.get("/api/security/env-file")
    assert r.status_code == 200
    data = r.json()
    assert data["exists"] is False
    assert data["content"] == ""

    r_put = client.put("/api/security/env-file", json={"content": "X=1\nY=secret\n"})
    assert r_put.status_code == 200
    assert r_put.json()["written"] is True
    assert r_put.json()["backup"] is None

    r2 = client.get("/api/security/env-file")
    assert r2.json()["content"] == "X=1\nY=secret\n"

    r_put2 = client.put("/api/security/env-file", json={"content": "X=2\n"})
    assert r_put2.status_code == 200
    assert r_put2.json()["backup"] is not None


def test_security_env_merges_dotenv_file(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "sr"
    repo.mkdir()
    (repo / "configs").mkdir(parents=True)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"skills_roots": [str(repo.resolve())], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    monkeypatch.delenv("QONTO_API_KEY", raising=False)
    # Créer le client avant le fichier .env pour que load_dotenv au démarrage ne charge rien.
    client = TestClient(create_app())
    (repo / ".env").write_text("QONTO_API_KEY=abc123secret\n", encoding="utf-8")
    r = client.get("/api/security/env")
    assert r.status_code == 200
    rows = {row["name"]: row for row in r.json()["variables"]}
    q = rows["QONTO_API_KEY"]
    assert q["present"] is True
    assert q["in_file"] is True
    assert q["in_process"] is False
    assert q["masked"].endswith("cret")
    client = TestClient(create_app())
    r = client.get("/api/cli/help")
    assert r.status_code == 200
    payload = r.json()
    assert "text" in payload
    assert len(payload["text"]) > 20
    assert "COMMAND" in payload["text"].upper() or "doctor" in payload["text"].lower()


def test_security_env_overview_includes_secret_sync_without_raw_values(monkeypatch, tmp_path):
    import yaml
    from zab.services import security_secret_sync

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(
        security_secret_sync,
        "dashlane_secret_inventory",
        lambda: {
            "available": True,
            "status": "ok",
            "count": 1,
            "items": [
                {
                    "id": "{TEST-PLAIN-LOCAL-KEY}",
                    "title": "Z_PLAIN_LOCAL_KEY",
                    "reference": "dl://{TEST-PLAIN-LOCAL-KEY}",
                }
            ],
        },
    )
    repo = tmp_path / "sr"
    repo.mkdir()
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = repo / ".env"
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [str(env_path.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": ["PLAIN_LOCAL_KEY", "DASHLANE_REF_KEY"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PLAIN_LOCAL_KEY", raising=False)
    monkeypatch.delenv("DASHLANE_REF_KEY", raising=False)
    client = TestClient(create_app())
    env_path.write_text(
        "PLAIN_LOCAL_KEY=super-secret-local-value\nDASHLANE_REF_KEY=dl://dashlane-secret-id\n",
        encoding="utf-8",
    )

    r = client.get("/api/security/env-overview")
    assert r.status_code == 200
    assert "super-secret-local-value" not in r.text
    payload = r.json()
    rows = {row["name"]: row for row in payload["variables"]}
    assert rows["PLAIN_LOCAL_KEY"]["sync"]["status"] == "pending"
    assert rows["PLAIN_LOCAL_KEY"]["sync"]["recommended_provider"] == "dashlane"
    assert rows["PLAIN_LOCAL_KEY"]["sync"]["dashlane_match_status"] == "matched"
    assert rows["PLAIN_LOCAL_KEY"]["sync"]["dashlane_reference_value"] == "dl://{TEST-PLAIN-LOCAL-KEY}"
    assert rows["PLAIN_LOCAL_KEY"]["sync"]["dashlane_web_url"].endswith("/#/credentials/TEST-PLAIN-LOCAL-KEY")
    assert rows["PLAIN_LOCAL_KEY"]["sync"]["dashlane_matches"][0]["web_url"].endswith(
        "/#/credentials/TEST-PLAIN-LOCAL-KEY"
    )
    assert payload["secret_sync"]["dashlane_inventory"]["count"] == 1
    assert payload["secret_sync"]["dashlane_inventory"]["items"][0]["title"] == "Z_PLAIN_LOCAL_KEY"
    assert payload["secret_sync"]["dashlane_inventory"]["items"][0]["web_url"].endswith(
        "/#/credentials/TEST-PLAIN-LOCAL-KEY"
    )
    note = rows["PLAIN_LOCAL_KEY"]["sync"]["note_template"]
    assert "PLAIN_LOCAL_KEY" in note
    assert "dl://{TEST-PLAIN-LOCAL-KEY}" in note
    assert "~/" in note or str(env_path) in note
    assert "super-secret-local-value" not in note
    assert rows["DASHLANE_REF_KEY"]["sync"]["status"] == "synced"
    assert rows["DASHLANE_REF_KEY"]["sync"]["provider"] == "dashlane"
    assert rows["DASHLANE_REF_KEY"]["sync"]["dashlane_web_url"] == "https://app.dashlane.com/#/credentials"
    assert payload["secret_sync"]["counts"]["pending"] >= 1

    r_check = client.post("/api/security/secret-sync/check", json={"provider": "dashlane", "apply": True})
    assert r_check.status_code == 200
    check = r_check.json()
    assert check["write_supported"] is False
    assert check["status"] == "action_required"
    assert "super-secret-local-value" not in r_check.text


def test_security_env_overview_uses_alias_value_for_secret_sync(monkeypatch, tmp_path):
    import yaml
    from zab.services import security_secret_sync

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(
        security_secret_sync,
        "dashlane_secret_inventory",
        lambda: {"available": True, "status": "ok", "count": 0, "items": []},
    )
    repo = tmp_path / "sr"
    repo.mkdir()
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = repo / ".env"
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [str(env_path.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    monkeypatch.delenv("COMPOSIO_X_CONSUMER_API_KEY", raising=False)
    env_path.write_text("COMPOSIO_X_CONSUMER_API_KEY=dl://Z_COMPOSIO_API_KEY\n", encoding="utf-8")
    client = TestClient(create_app())

    r = client.get("/api/security/env-overview")

    assert r.status_code == 200
    payload = r.json()
    rows = {row["name"]: row for row in payload["variables"]}
    assert rows["COMPOSIO_API_KEY"]["sync"]["status"] == "synced"
    assert rows["COMPOSIO_API_KEY"]["sync"]["provider"] == "dashlane"
    assert rows["COMPOSIO_API_KEY"]["masked"].endswith("_KEY")


def test_security_dashlane_apply_writes_reference_without_raw_values(monkeypatch, tmp_path):
    import yaml
    from zab.services import security_secret_sync

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(
        security_secret_sync,
        "dashlane_secret_inventory",
        lambda: {
            "available": True,
            "status": "ok",
            "count": 1,
            "items": [
                {
                    "id": "{TEST-PLAIN-LOCAL-KEY}",
                    "title": "Z_PLAIN_LOCAL_KEY",
                    "reference": "dl://{TEST-PLAIN-LOCAL-KEY}",
                }
            ],
        },
    )
    repo = tmp_path / "sr"
    repo.mkdir()
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = repo / ".env"
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [str(env_path.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": ["PLAIN_LOCAL_KEY"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PLAIN_LOCAL_KEY", raising=False)
    env_path.write_text("PLAIN_LOCAL_KEY=super-secret-local-value\n", encoding="utf-8")
    client = TestClient(create_app())

    r = client.post(
        "/api/security/secret-sync/dashlane/apply",
        json={
            "provider": "dashlane",
            "name": "PLAIN_LOCAL_KEY",
            "selected_count": 1,
            "confirm_all": True,
        },
    )

    assert r.status_code == 200
    assert "super-secret-local-value" not in r.text
    payload = r.json()
    assert payload["result"]["status"] == "synced"
    assert "PLAIN_LOCAL_KEY=dl://{TEST-PLAIN-LOCAL-KEY}" in env_path.read_text(encoding="utf-8")
    assert "super-secret-local-value" not in env_path.read_text(encoding="utf-8")
    assert not list(repo.glob(".env.zab-dashlane-backup-*"))
    assert not list(repo.glob(".env.zab-dashlane-tmp-*"))
    assert payload["secret_sync"]["counts"]["synced"] == 1


def test_security_dashlane_apply_missing_secret_requires_creation(monkeypatch, tmp_path):
    import yaml
    from zab.services import security_secret_sync

    created: dict[str, str] = {}
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(
        security_secret_sync,
        "dashlane_secret_inventory",
        lambda: {"available": True, "status": "ok", "count": 0, "items": []},
    )
    monkeypatch.setattr(
        security_secret_sync,
        "create_dashlane_secret",
        lambda variable, *, value: (
            created.setdefault("name", variable["name"]),
            created.setdefault("value", value),
            {
                "ok": True,
                "status": "created",
                "provider": "dashlane",
                "dashlane_title": "Z_QONTO_SECRET_KEY",
                "dashlane_reference_value": "dl://{CREATED-QONTO-SECRET}",
                "dashlane_web_url": "https://app.dashlane.com/#/credentials/CREATED-QONTO-SECRET",
            },
        )[2],
    )
    repo = tmp_path / "sr"
    repo.mkdir()
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = repo / ".env"
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [str(env_path.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": ["QONTO_SECRET_KEY"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("QONTO_SECRET_KEY", raising=False)
    env_path.write_text("QONTO_SECRET_KEY=qonto-secret-value\n", encoding="utf-8")
    client = TestClient(create_app())

    r = client.post(
        "/api/security/secret-sync/dashlane/apply",
        json={
            "provider": "dashlane",
            "name": "QONTO_SECRET_KEY",
            "selected_count": 1,
            "confirm_all": True,
        },
    )

    assert r.status_code == 200
    assert "qonto-secret-value" not in r.text
    payload = r.json()
    assert payload["result"]["status"] == "synced"
    assert payload["result"]["dashlane_secret_status"] == "created"
    assert payload["result"]["dashlane_title"] == "Z_QONTO_SECRET_KEY"
    assert created == {"name": "QONTO_SECRET_KEY", "value": "qonto-secret-value"}
    assert env_path.read_text(encoding="utf-8") == "QONTO_SECRET_KEY=dl://{CREATED-QONTO-SECRET}\n"


def test_security_dashlane_apply_missing_secret_errors_without_writer(monkeypatch, tmp_path):
    import yaml
    from zab.services import security_secret_sync

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.delenv("ZAB_DASHLANE_SECRET_CREATE_COMMAND", raising=False)
    monkeypatch.setattr(
        security_secret_sync,
        "dashlane_secret_inventory",
        lambda: {"available": True, "status": "ok", "count": 0, "items": []},
    )
    repo = tmp_path / "sr"
    repo.mkdir()
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = repo / ".env"
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [str(env_path.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": ["QONTO_SECRET_KEY"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("QONTO_SECRET_KEY", raising=False)
    env_path.write_text("QONTO_SECRET_KEY=qonto-secret-value\n", encoding="utf-8")
    client = TestClient(create_app())

    r = client.post(
        "/api/security/secret-sync/dashlane/apply",
        json={
            "provider": "dashlane",
            "name": "QONTO_SECRET_KEY",
            "selected_count": 1,
            "confirm_all": True,
        },
    )

    assert r.status_code == 200
    assert "qonto-secret-value" not in r.text
    payload = r.json()
    assert payload["result"]["status"] == "error"
    assert payload["result"]["reason"] == "dashlane_secret_write_unavailable"
    assert payload["result"]["dashlane_title"] == "Z_QONTO_SECRET_KEY"
    assert env_path.read_text(encoding="utf-8") == "QONTO_SECRET_KEY=qonto-secret-value\n"


def test_security_dashlane_copy_value_does_not_return_secret(monkeypatch, tmp_path):
    import yaml
    from zab.services import security_secret_sync

    copied: dict[str, str] = {}
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(
        security_secret_sync,
        "dashlane_secret_inventory",
        lambda: {"available": True, "status": "ok", "count": 0, "items": []},
    )
    monkeypatch.setattr(
        security_secret_sync,
        "copy_to_clipboard",
        lambda value: (copied.setdefault("value", value) is not None, None),
    )
    repo = tmp_path / "sr"
    repo.mkdir()
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = repo / ".env"
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [str(env_path.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": ["QONTO_SECRET_KEY"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("QONTO_SECRET_KEY", raising=False)
    env_path.write_text("QONTO_SECRET_KEY=qonto-secret-value\n", encoding="utf-8")
    client = TestClient(create_app())

    r = client.post(
        "/api/security/secret-sync/dashlane/copy-value",
        json={"name": "QONTO_SECRET_KEY", "confirm_clipboard": True},
    )

    assert r.status_code == 200
    assert copied["value"] == "qonto-secret-value"
    assert "qonto-secret-value" not in r.text
    assert r.json()["dashlane_title"] == "Z_QONTO_SECRET_KEY"


def test_security_dashlane_apply_requires_all_selection_confirmation(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    repo = tmp_path / "sr"
    repo.mkdir()
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = repo / ".env"
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [str(env_path.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": ["FIRST_SECRET", "SECOND_SECRET"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FIRST_SECRET", raising=False)
    monkeypatch.delenv("SECOND_SECRET", raising=False)
    env_path.write_text("FIRST_SECRET=one-secret\nSECOND_SECRET=two-secret\n", encoding="utf-8")
    client = TestClient(create_app())

    r = client.post(
        "/api/security/secret-sync/dashlane/apply",
        json={
            "provider": "dashlane",
            "name": "FIRST_SECRET",
            "reference": "dl://zab-env-FIRST_SECRET",
            "selected_count": 2,
            "total_selectable": 2,
            "confirm_all": False,
        },
    )

    assert r.status_code == 409
    assert "one-secret" not in r.text
    assert "FIRST_SECRET=one-secret" in env_path.read_text(encoding="utf-8")


def test_security_reports_api(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    report_dir = tmp_path / ".local" / "share" / "zab" / "security-last"
    report_dir.mkdir(parents=True)
    (report_dir / "security_osv_zab-zab.json").write_text(
        json.dumps(
            {
                "generated_at_utc": "2026-05-14T00:00:00+00:00",
                "summary": {"preset": "security_osv_zab", "status": "done", "exit_code": 0},
                "lines": ["ok"],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.get("/api/security/reports")
    assert r.status_code == 200
    assert r.json()["reports"][0]["key"] == "security_osv_zab-zab"
    r2 = client.get("/api/security/last?key=security_osv_zab-zab")
    assert r2.status_code == 200
    assert r2.json()["present"] is True
    assert r2.json()["summary"]["preset"] == "security_osv_zab"


def test_config_projects_roots_put(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "my-code"
    root.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "skills_anchor_config_test"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "configs").mkdir(parents=True)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"skills_roots": [str(repo.resolve())], "projects_roots": [], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.put("/api/config/projects-roots", json={"roots": [str(root.resolve())]})
    assert r.status_code == 200
    data = r.json()
    assert data["written"] is True
    assert "projects_roots" in data
    paths = data["projects_roots"]
    assert len(paths) == 1
    assert paths[0].startswith("~/") or str(root.resolve()) in paths[0]
    raw = yaml.safe_load((cfg_dir / "config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw.get("projects_roots"), list)


def test_models_discovery_route(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "sr"
    repo.mkdir()
    (repo / "configs").mkdir(parents=True)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [str(repo.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": [],
                "models_discovery": {"updated_at_utc": "x", "agentpipe": {}, "codexbar": {}},
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.get("/api/config/models-discovery")
    assert r.status_code == 200
    assert r.json().get("models_discovery") is not None


def test_scan_route(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ZAB_SKILLS_ROOT", str(tmp_path / "skills-repo"))
    (tmp_path / "skills-repo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "snap").mkdir(parents=True)
    (tmp_path / "snap" / "SKILL.md").write_text("# t\n", encoding="utf-8")
    client = TestClient(create_app())
    r = client.get("/api/scan")
    assert r.status_code == 200
    data = r.json()
    assert data["skill_md_count"] >= 1
    assert "snap/SKILL.md" in [row["path"] for row in data["skill_md_files"]]
    assert data.get("workspace_projects") is not None
    ms = data.get("memory_stack")
    assert isinstance(ms, dict)
    assert "mempalace" in ms and "postgres_probe" in ms
    assert "MEHDI_MEMORY_DATABASE_URL_configured" in ms


def test_memory_status_ok_shape():
    client = TestClient(create_app())
    r = client.get("/api/memory/status")
    assert r.status_code == 200
    j = r.json()
    assert j.get("configured") in (True, False)
    assert "psycopg_available" in j
    assert "document_count" in j or "error" in j


def test_memory_documents_503_without_dsn(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MEHDI_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("ZAB_SKILLS_ROOT", raising=False)
    monkeypatch.delenv("ZAB_INVOCATION_CWD", raising=False)
    repo = tmp_path / "sr"
    repo.mkdir()
    (repo / "configs").mkdir(parents=True)
    monkeypatch.setattr("zab.services.memory_db.skills_root", lambda: repo)
    monkeypatch.setattr("zab.services.memory_db.skills_root_from_config_file_only", lambda: repo)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"skills_roots": [str(repo.resolve())], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.get("/api/memory/documents")
    assert r.status_code == 503


def test_conversations_providers_ok():
    client = TestClient(create_app())
    r = client.get("/api/conversations/providers")
    assert r.status_code == 200
    j = r.json()
    assert "providers" in j
    assert len(j["providers"]) >= 1


def test_conversations_health_ok():
    client = TestClient(create_app())
    r = client.get("/api/conversations/health")
    assert r.status_code == 200
    h = r.json()
    assert h.get("severity") in ("ok", "warn", "fail")
    assert "recommendations" in h


def test_conversations_search_503_without_dsn(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MEHDI_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("ZAB_SKILLS_ROOT", raising=False)
    monkeypatch.delenv("ZAB_INVOCATION_CWD", raising=False)
    repo = tmp_path / "sr"
    repo.mkdir()
    (repo / "configs").mkdir(parents=True)
    monkeypatch.setattr("zab.services.memory_db.skills_root", lambda: repo)
    monkeypatch.setattr("zab.services.memory_db.skills_root_from_config_file_only", lambda: repo)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"skills_roots": [str(repo.resolve())], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.get("/api/conversations/search?q=test")
    assert r.status_code == 503


def test_conversations_documents_lists_history_without_query(monkeypatch):
    monkeypatch.setattr(
        "zab.api.routes.memory_db.fetch_status",
        lambda: {"configured": True, "psycopg_available": True, "connected": True},
    )
    monkeypatch.setattr(
        "zab.api.routes.memory_db.fetch_conversation_documents",
        lambda limit=25, offset=0, provider=None, wing=None, source=None: {
            "total": 1,
            "conversation_storage": "archive",
            "items": [
                {
                    "document_id": "00000000-0000-0000-0000-000000000001",
                    "source": "cursor_agent_transcript",
                    "wing": "cursor__zab",
                    "room": "conversation",
                    "synced_at": "2026-05-21T10:00:00+00:00",
                    "path": "/tmp/demo.jsonl",
                    "chunk_count": 3,
                    "message_count": 2,
                    "content_excerpt": "Bonjour",
                }
            ],
        },
    )

    client = TestClient(create_app())
    r = client.get("/api/conversations/documents?limit=25&offset=0&provider=cursor")
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 1
    assert j["items"][0]["message_count"] == 2
    assert j["items"][0]["document_id"].endswith("0001")


def test_conversations_document_detail_exposes_structured_messages(monkeypatch):
    monkeypatch.setattr(
        "zab.api.routes.memory_db.fetch_status",
        lambda: {"configured": True, "psycopg_available": True, "connected": True},
    )
    monkeypatch.setattr(
        "zab.api.routes.memory_db.fetch_conversation_document_detail",
        lambda document_id, chunk_limit=100: {
            "id": document_id,
            "source": "cursor_agent_transcript",
            "metadata": {
                "messages": [
                    {"role": "user", "label": "You", "content": "bonjour"},
                    {"role": "assistant", "label": "Agent", "content": "salut"},
                ]
            },
            "chunks": [{"content": "### user\nbonjour"}],
        },
    )

    client = TestClient(create_app())
    r = client.get("/api/conversations/document/00000000-0000-0000-0000-000000000001")
    assert r.status_code == 200
    j = r.json()["document"]
    assert j["messages"][0]["label"] == "You"
    assert j["messages"][1]["label"] == "Agent"


def test_conversations_sync_starts_job():
    client = TestClient(create_app())
    r = client.post("/api/conversations/sync", json={"dry_run": True, "append": True})
    assert r.status_code == 200
    j = r.json()
    assert "id" in j
    assert j.get("preset") == "conversation_sync"


def test_build_argv_mempalace_install():
    from zab.services.jobs import build_argv_for_preset

    argv, cwd = build_argv_for_preset("mempalace_install")
    assert argv[:4] == ["uv", "tool", "install", "mempalace"]
    assert Path(cwd) == Path.home()


def test_mcps_sync_status_and_list():
    client = TestClient(create_app())
    r = client.get("/api/mcps/sync-status")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    j = r.json()
    assert "counts" in j
    assert "sources" in j

    r2 = client.get("/api/mcps")
    assert r2.status_code == 200
    body = r2.json()
    assert "data" in body
    assert "total" in body


def test_mcps_scan_persists_registry(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills-repo"
    (repo / "configs").mkdir(parents=True, exist_ok=True)
    (repo / "configs" / "cursor-mcp.json").write_text(
        json.dumps({"mcpServers": {"scanme": {"command": "true", "args": []}}}),
        encoding="utf-8",
    )
    (repo / "configs" / "claude-desktop-mcp.json").write_text("{}", encoding="utf-8")
    cfg = tmp_path / ".config" / "zab"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text(
        f"skills_roots: [{json.dumps(str(repo))}]\nprojects_roots: []\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())
    r = client.post("/api/mcps/scan")
    assert r.status_code == 200
    out = r.json()
    assert out.get("ok") is True
    assert "state_summary" in out
    assert (tmp_path / ".config" / "zab" / "mcp-registry.json").is_file()


def test_channels_check_api():
    client = TestClient(create_app())
    r = client.get("/api/channels/check")
    assert r.status_code == 200
    payload = r.json()
    assert payload["contract"] == "conversation-ledger-channels"
    assert isinstance(payload.get("channels"), list)


def test_workpackets_list_api():
    client = TestClient(create_app())
    r = client.get("/api/workpackets")
    assert r.status_code == 200
    payload = r.json()
    assert payload["contract"] == "workpacket-list"
    assert isinstance(payload.get("items"), list)


def test_ledger_eval_api():
    client = TestClient(create_app())
    r = client.get("/api/ledger/eval?suite=hard")
    assert r.status_code == 200
    payload = r.json()
    assert payload["contract"] == "ledger-eval-report"
    assert payload["hard"]["failed"] == 0
