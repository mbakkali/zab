from pathlib import Path

from fastapi.testclient import TestClient

from zab.api.app import create_app


def test_health():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


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


def test_config_files_api():
    client = TestClient(create_app())
    r = client.get("/api/config/files")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 2
    keys = {row["key"] for row in rows}
    assert keys == {"local_tools_actual", "user_zab_config"}


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
    r = client.get("/api/memory/documents")
    assert r.status_code == 503


def test_build_argv_mempalace_install():
    from zab.services.jobs import build_argv_for_preset

    argv, cwd = build_argv_for_preset("mempalace_install")
    assert argv[:4] == ["uv", "tool", "install", "mempalace"]
    assert Path(cwd) == Path.home()

