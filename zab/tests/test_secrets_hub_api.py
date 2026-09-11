"""Test de la route API : vue par projet/org du hub de secrets (lecture seule)."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from zab.api.app import create_app


def _setup(monkeypatch, tmp_path, *, tracked=()):
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"projects_roots": [str(root)], "tracked_env_extra": list(tracked)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("ZAB_SECRET_MANAGER_PROJECT", "demo-projet")
    for name in tracked:
        monkeypatch.delenv(name, raising=False)
    return root, cfg_dir


def test_secrets_hub_overview_agrege_par_projet_sans_ecrire(monkeypatch, tmp_path):
    root, _cfg = _setup(monkeypatch, tmp_path)

    # Projet non versionné : un secret probable, un nom écarté.
    libre = root / "acme-cowork" / "api"
    libre.mkdir(parents=True)
    (libre / ".env").write_text(
        "STRIPE_API_KEY=k\nDB_HOST=localhost\n", encoding="utf-8"
    )

    # Projet versionné (CI seule, sans .git) : agrégé, jamais miroité.
    versionne = root / "acme-cowork" / "appli"
    (versionne / ".github" / "workflows").mkdir(parents=True)
    (versionne / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    (versionne / ".env").write_text("DB_PASSWORD=du-depot\n", encoding="utf-8")

    client = TestClient(create_app())
    r = client.get("/api/security/secrets-hub/overview")
    assert r.status_code == 200
    payload = r.json()

    # Aucune valeur ne doit transiter par cette route — seulement des noms et des compteurs.
    body_text = r.text
    assert "du-depot" not in body_text
    assert "localhost" not in body_text

    assert set(payload.keys()) >= {"counts", "scanned_files", "projects", "totals"}
    assert isinstance(payload["counts"], dict)
    assert set(payload["counts"].keys()) == {"referenced", "plain", "process", "missing"}

    projets = {(p["org"], p["project"]): p for p in payload["projects"]}
    api = projets[("acme", "api")]
    assert api["detected_count"] == 1
    assert api["skipped_count"] == 1
    assert api["versioned"] is False
    assert api["env_file_count"] == 1

    appli = projets[("acme", "appli")]
    assert appli["detected_count"] == 1
    assert appli["skipped_count"] == 0
    assert appli["versioned"] is True

    assert payload["totals"]["projects"] == len(payload["projects"])
    assert payload["totals"]["detected"] == sum(p["detected_count"] for p in payload["projects"])
    assert payload["totals"]["skipped"] == sum(p["skipped_count"] for p in payload["projects"])
    assert payload["totals"]["versioned"] == 1
