from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from zab.api import remote_app


def _client(monkeypatch, tmp_path: Path, token: str = "jeton-de-test") -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(remote_app.TOKEN_ENV, token)
    monkeypatch.setattr(remote_app.remote_vm, "overview", lambda: {"configured": True, "vm": {"status": "RUNNING"}})
    monkeypatch.setattr(
        remote_app.remote_vm,
        "cost_report",
        lambda days=30, refresh=False: {"currency": "EUR", "totals": {"mtd_cost": 1.0}, "freshness": {}},
    )
    return TestClient(remote_app.create_remote_app())


def _auth(token: str = "jeton-de-test") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_ping_is_public_and_reveals_nothing(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/ping")

    assert response.status_code == 200
    body = response.json()
    # `sso` dit *comment* on s'authentifie, jamais qui est connecté ni dans quel
    # état est la VM : c'est ce dont la PWA a besoin pour ne pas afficher un
    # écran de jeton là où Google a déjà fait le travail.
    assert body == {"status": "ok", "service": "zab-remote", "sso": False}


def test_iap_replaces_the_bearer_token_when_the_deployment_says_so(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(remote_app.IAP_ENV, "1")
    client = _client(monkeypatch, tmp_path)

    assert client.get("/ping").json()["sso"] is True
    # Aucun en-tête Authorization : c'est IAP qui porte l'identité.
    response = client.get(
        "/api/me", headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:user@example.com"}
    )
    assert response.status_code == 200
    assert response.json() == {"email": "user@example.com"}


def test_the_iap_header_alone_opens_nothing(monkeypatch, tmp_path: Path) -> None:
    # Un en-tête ne prouve rien tout seul : sans ZAB_IAP, un déploiement public
    # qui l'accepterait serait grand ouvert. Le raccourci doit rester inerte.
    monkeypatch.delenv(remote_app.IAP_ENV, raising=False)
    client = _client(monkeypatch, tmp_path)

    response = client.get(
        "/api/me", headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:intrus@ailleurs.com"}
    )
    assert response.status_code == 401


def test_api_requires_a_valid_token(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer faux"}).status_code == 401
    assert client.get("/api/status", headers={"Authorization": "jeton-de-test"}).status_code == 401
    assert client.get("/api/status", headers=_auth()).status_code == 200


def test_api_refuses_everything_when_no_token_is_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(remote_app.TOKEN_ENV, raising=False)
    client = TestClient(remote_app.create_remote_app())

    response = client.get("/api/status", headers=_auth())

    assert response.status_code == 503
    assert "jeton" in response.json()["error"]


def test_pwa_shell_is_served(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    index = client.get("/")
    manifest = client.get("/manifest.webmanifest")
    worker = client.get("/sw.js")

    assert index.status_code == 200
    assert "VM cowork" in index.text
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"
    # Un service worker servi ailleurs qu'à la racine ne contrôlerait pas toute l'origine.
    assert worker.status_code == 200
    assert "text/javascript" in worker.headers["content-type"]


def test_status_exposes_job_and_busy_flags(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    body = client.get("/api/status", headers=_auth()).json()

    assert body["busy"] is False
    assert body["job"] is None
    assert body["vm"]["status"] == "RUNNING"


def test_long_action_returns_immediately_and_rejects_a_second_one(monkeypatch, tmp_path: Path) -> None:
    release = threading.Event()
    started = threading.Event()

    def slow_start() -> dict[str, Any]:
        started.set()
        release.wait(timeout=5)
        return {"ok": True}

    client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(remote_app.remote_vm, "start_vm", slow_start)

    first = client.post("/api/start", headers=_auth())
    assert first.status_code == 200
    assert first.json()["job"]["state"] == "running"
    assert started.wait(timeout=5)

    # Un double appui sur le bouton ne doit pas lancer deux démarrages.
    second = client.post("/api/start", headers=_auth())
    assert second.status_code == 409

    during = client.get("/api/status", headers=_auth()).json()
    assert during["busy"] is True

    release.set()
    for _ in range(50):
        after = client.get("/api/status", headers=_auth()).json()
        if not after["busy"]:
            break
    assert after["busy"] is False
    assert after["job"]["state"] == "done"
    assert after["job"]["ok"] is True


def test_start_failure_is_reported_not_raised(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(remote_app.remote_vm, "start_vm", lambda: {"ok": False, "error": "zone inconnue"})

    assert client.post("/api/start", headers=_auth()).status_code == 200
    for _ in range(50):
        job = client.get("/api/status", headers=_auth()).json()["job"]
        if job and job.get("state") != "running":
            break
    assert job["state"] == "failed"
    assert job["error"] == "zone inconnue"


def test_stop_endpoint_is_not_exposed(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    assert client.post("/api/stop", headers=_auth()).status_code in {404, 405}


def test_sync_action_allowlist(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(remote_app.remote_vm, "sync_action", lambda action: {"ok": True})

    assert client.post("/api/sync-action?action=rm-rf", headers=_auth()).status_code == 400
    assert client.post("/api/sync-action?action=sync-flush", headers=_auth()).status_code == 200


def test_token_file_is_created_private_and_rotatable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(remote_app.TOKEN_ENV, raising=False)

    first = remote_app.ensure_token()
    path = remote_app.token_path()

    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert remote_app.read_token() == first
    assert remote_app.ensure_token() == first

    rotated = remote_app.ensure_token(rotate=True)
    assert rotated != first
    assert remote_app.read_token() == rotated


def test_environment_token_wins_over_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(remote_app.TOKEN_ENV, raising=False)
    remote_app.ensure_token()

    monkeypatch.setenv(remote_app.TOKEN_ENV, "depuis-environnement")

    assert remote_app.read_token() == "depuis-environnement"


def test_agent_tab_is_absent_until_an_upstream_is_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(remote_app.AGENT_UPSTREAM_ENV, raising=False)
    client = _client(monkeypatch, tmp_path)

    body = client.get("/api/agent", headers=_auth()).json()

    assert body["enabled"] is False
    assert body["label"] == "Agent"


def test_agent_tab_reports_its_label_once_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(remote_app.AGENT_UPSTREAM_ENV, "http://agent.invalid:9119/")
    monkeypatch.setenv("ZAB_AGENT_LABEL", "Hermès")
    client = _client(monkeypatch, tmp_path)

    body = client.get("/api/agent", headers=_auth()).json()

    assert body == {"enabled": True, "path": "/agent/", "label": "Hermès"}


def test_agent_upstream_drops_its_trailing_slash(monkeypatch) -> None:
    monkeypatch.setenv(remote_app.AGENT_UPSTREAM_ENV, "http://agent.invalid:9119/")

    assert remote_app.agent_upstream() == "http://agent.invalid:9119"


def test_agent_proxy_says_so_when_no_upstream_is_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(remote_app.AGENT_UPSTREAM_ENV, raising=False)
    monkeypatch.delenv(remote_app.APPS_ENV, raising=False)
    client = _client(monkeypatch, tmp_path)

    response = client.get("/agent/")

    # 503 et non 404 : la route existe, c'est le déploiement qui est incomplet.
    assert response.status_code == 503
    # Le message doit nommer la variable à renseigner ; depuis le passage à
    # plusieurs applications, c'est ZAB_APPS et non plus l'ancienne variable.
    assert remote_app.APPS_ENV in response.json()["error"]


def test_apps_are_listed_in_order_with_the_legacy_variable_first(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(remote_app.AGENT_UPSTREAM_ENV, "https://hermes.invalid/")
    monkeypatch.setenv("ZAB_AGENT_LABEL", "Hermès")
    monkeypatch.setenv(remote_app.APPS_ENV, "flowgo|Flowgo|https://flowgo.invalid/")
    client = _client(monkeypatch, tmp_path)

    body = client.get("/api/apps", headers=_auth()).json()

    assert [a["slug"] for a in body["apps"]] == ["agent", "flowgo"]
    assert [a["label"] for a in body["apps"]] == ["Hermès", "Flowgo"]
    assert body["apps"][1]["path"] == "/app/flowgo/"
    # L'amont ne sort pas : le téléphone n'en a pas besoin, et publier les noms
    # d'hôtes internes n'ajouterait qu'une surface.
    assert all("upstream" not in a for a in body["apps"])


def test_malformed_app_records_are_ignored_rather_than_fatal(monkeypatch, tmp_path: Path) -> None:
    # Une coquille dans une variable d'environnement ne doit pas priver la
    # mini-app de son onglet VM, seul moyen de rallumer la machine.
    monkeypatch.delenv(remote_app.AGENT_UPSTREAM_ENV, raising=False)
    monkeypatch.setenv(
        remote_app.APPS_ENV,
        "sans-url|Cassé ; ok|OK|https://ok.invalid ; MAJUSCULE X|X|https://x.invalid ; ok|Doublon|https://z.invalid",
    )
    client = _client(monkeypatch, tmp_path)

    body = client.get("/api/apps", headers=_auth()).json()

    assert [a["slug"] for a in body["apps"]] == ["ok"]


def test_unknown_app_slug_is_a_404(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(remote_app.AGENT_UPSTREAM_ENV, raising=False)
    monkeypatch.setenv(remote_app.APPS_ENV, "flowgo|Flowgo|https://flowgo.invalid")
    client = _client(monkeypatch, tmp_path)

    assert client.get("/app/inconnu/").status_code == 404


def test_agent_proxy_surfaces_an_unreachable_agent(monkeypatch, tmp_path: Path) -> None:
    # L'agent vit sur une machine qui peut être éteinte ; le proxy doit rendre
    # un 502 lisible plutôt que de laisser filer l'exception.
    monkeypatch.setenv(remote_app.AGENT_UPSTREAM_ENV, "http://127.0.0.1:1/")
    client = _client(monkeypatch, tmp_path)

    response = client.get("/agent/")

    assert response.status_code == 502
    assert "injoignable" in response.json()["error"]


def test_hop_by_hop_headers_are_not_forwarded() -> None:
    headers = {"Host": "vm.example.com", "Connection": "keep-alive", "Accept": "text/html"}

    forwarded = remote_app._forwardable(headers)

    assert forwarded == {"Accept": "text/html"}
