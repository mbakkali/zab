"""Surface de contrôle distante minimale pour la VM de dev, servie en PWA.

Cette application est volontairement séparée du dashboard zab. Exposer l'API zab
complète sur Internet donnerait à quiconque franchit l'authentification un accès
à toute la machine : scan du workspace, lecture des configurations, jobs, secrets.
Ici la surface se limite à quatre actions sur une seule ressource, derrière un
jeton porteur.

Deux propriétés comptent pour un usage depuis un téléphone :

- les actions sont **asynchrones**. Démarrer la VM et reprendre la synchronisation
  prend plusieurs minutes, bien au-delà du délai d'un proxy HTTP : la requête
  enregistre un job et rend la main tout de suite, l'état est ensuite lu par
  interrogation régulière.
- une seule action peut être en cours à la fois, pour qu'un double appui sur un
  bouton ne lance pas deux `start` concurrents.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from zab.paths import config_dir, zab_package_dir
from zab.services import remote_vm

TOKEN_ENV = "ZAB_REMOTE_TOKEN"
TOKEN_FILENAME = "remote-token"
PUBLIC_PATHS = {"/healthz"}


def pwa_dir() -> Path:
    return zab_package_dir() / "pwa"


def token_path() -> Path:
    return config_dir() / TOKEN_FILENAME


def read_token() -> str | None:
    """Jeton courant : variable d'environnement, sinon fichier de configuration."""
    env = os.environ.get(TOKEN_ENV, "").strip()
    if env:
        return env
    path = token_path()
    if path.is_file():
        value = path.read_text().strip()
        return value or None
    return None


def ensure_token(*, rotate: bool = False) -> str:
    """Crée le jeton s'il manque, en 0600, et le renvoie."""
    if not rotate:
        existing = read_token()
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n")
    path.chmod(0o600)
    return token


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobRunner:
    """Exécute une action longue à la fois et conserve le résultat de la dernière."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: dict[str, Any] | None = None
        self._last: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._current or self._last or {}) or None

    def busy(self) -> bool:
        with self._lock:
            return self._current is not None

    def submit(self, action: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            if self._current is not None:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "action déjà en cours", "job": dict(self._current)},
                )
            job = {"action": action, "state": "running", "started_at": _now()}
            self._current = job

        def run() -> None:
            try:
                result = fn()
                outcome = {
                    "state": "done" if result.get("ok") else "failed",
                    "ok": bool(result.get("ok")),
                    "error": result.get("error"),
                }
            except Exception as exc:  # noqa: BLE001 - remonté tel quel au client
                outcome = {"state": "failed", "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            with self._lock:
                finished = dict(self._current or {})
                finished.update(outcome)
                finished["finished_at"] = _now()
                self._last = finished
                self._current = None

        threading.Thread(target=run, name=f"remote-vm-{action}", daemon=True).start()
        return dict(job)


def create_remote_app(*, jobs: JobRunner | None = None) -> FastAPI:
    app = FastAPI(title="zab remote", version="0.1.0", docs_url=None, redoc_url=None)
    runner = jobs or JobRunner()
    app.state.jobs = runner

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in PUBLIC_PATHS or not path.startswith("/api/"):
            return await call_next(request)
        expected = read_token()
        if not expected:
            return JSONResponse(
                {"error": "aucun jeton configuré côté serveur ; lance `zab vm token`"},
                status_code=503,
            )
        header = request.headers.get("authorization", "")
        presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not presented or not hmac.compare_digest(presented, expected):
            return JSONResponse({"error": "jeton invalide"}, status_code=401)
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        # Sonde du tunnel : ne révèle ni l'état de la VM ni la configuration.
        return {"status": "ok", "service": "zab-remote"}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        payload = remote_vm.overview()
        payload["job"] = runner.snapshot()
        payload["busy"] = runner.busy()
        payload["server_time"] = _now()
        return payload

    @app.get("/api/cost")
    def cost(days: int = Query(30, ge=1, le=180)) -> dict[str, Any]:
        report = remote_vm.cost_report(days=days)
        # La PWA n'a besoin que des agrégats : le détail quotidien est inutile ici.
        return {
            "currency": report.get("currency"),
            "totals": report.get("totals"),
            "freshness": report.get("freshness"),
            "error": report.get("error"),
        }

    @app.post("/api/start")
    def start() -> dict[str, Any]:
        return {"job": runner.submit("start", remote_vm.start_vm)}

    @app.post("/api/stop")
    def stop() -> dict[str, Any]:
        return {"job": runner.submit("stop", remote_vm.stop_vm)}

    @app.post("/api/sync-action")
    def sync_action(action: str = Query(..., description="sync-flush | sync-resume | sync-pause")) -> dict[str, Any]:
        if action not in {"sync-flush", "sync-resume", "sync-pause"}:
            raise HTTPException(status_code=400, detail={"error": f"action non autorisée: {action}"})
        return {"job": runner.submit(action, lambda: remote_vm.sync_action(action))}

    root = pwa_dir()
    if root.is_dir():
        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(root / "index.html")

        @app.get("/sw.js")
        def service_worker() -> FileResponse:
            # Le service worker doit être servi depuis la racine pour contrôler
            # toute l'origine, il ne peut donc pas vivre sous /static.
            return FileResponse(root / "sw.js", media_type="text/javascript")

        @app.get("/manifest.webmanifest")
        def manifest() -> FileResponse:
            return FileResponse(root / "manifest.webmanifest", media_type="application/manifest+json")

        app.mount("/", StaticFiles(directory=str(root), html=True), name="pwa")

    return app
