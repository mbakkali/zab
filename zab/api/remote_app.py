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

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from zab.paths import config_dir, zab_package_dir
from zab.services import remote_vm

TOKEN_ENV = "ZAB_REMOTE_TOKEN"
TOKEN_FILENAME = "remote-token"
# `/healthz` ne peut pas servir de sonde : le frontend Google le réserve et
# répond 404 avant même que la requête n'atteigne le conteneur.
PUBLIC_PATHS = {"/ping"}

# Agent embarqué joignable derrière la même origine que la mini-app. Vide, la
# fonctionnalité disparaît : ni route, ni onglet côté PWA.
AGENT_UPSTREAM_ENV = "ZAB_AGENT_UPSTREAM"
AGENT_PREFIX = "/agent"
# En-têtes propres à un saut de connexion : les recopier casserait le tunnel.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
        "content-length",
        "host",
    }
)
PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def agent_upstream() -> str | None:
    """Base HTTP de l'agent à relayer, sans barre oblique finale."""
    return os.environ.get(AGENT_UPSTREAM_ENV, "").strip().rstrip("/") or None


def _forwardable(headers: Any, *, drop_host: bool = True) -> dict[str, str]:
    out = {}
    for key, value in headers.items():
        low = key.lower()
        if low in HOP_BY_HOP and (low != "host" or drop_host):
            continue
        out[key] = value
    return out


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

    @app.get("/ping")
    def ping() -> dict[str, Any]:
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

    @app.post("/api/sync-action")
    def sync_action(action: str = Query(..., description="sync-flush | sync-resume | sync-pause")) -> dict[str, Any]:
        if action not in {"sync-flush", "sync-resume", "sync-pause"}:
            raise HTTPException(status_code=400, detail={"error": f"action non autorisée: {action}"})
        return {"job": runner.submit(action, lambda: remote_vm.sync_action(action))}

    @app.get("/api/agent")
    def agent_info() -> dict[str, Any]:
        """Dit à la PWA si l'onglet doit exister, et sous quel libellé."""
        return {
            "enabled": agent_upstream() is not None,
            "path": AGENT_PREFIX + "/",
            "label": os.environ.get("ZAB_AGENT_LABEL", "Agent").strip() or "Agent",
        }

    @app.websocket(AGENT_PREFIX + "/{path:path}")
    async def agent_ws(client: WebSocket, path: str) -> None:
        """Relaie le WebSocket de l'agent — sans lui, sa SPA reste muette."""
        import websockets

        base = agent_upstream()
        if not base:
            await client.close(code=1011)
            return
        target = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        url = f"{target}/{path}"
        if client.url.query:
            url += f"?{client.url.query}"
        await client.accept()
        try:
            async with websockets.connect(url, open_timeout=20, max_size=None) as upstream:
                async def pump_up() -> None:
                    while True:
                        message = await client.receive()
                        if message["type"] == "websocket.disconnect":
                            await upstream.close()
                            return
                        if (text := message.get("text")) is not None:
                            await upstream.send(text)
                        elif (data := message.get("bytes")) is not None:
                            await upstream.send(data)

                async def pump_down() -> None:
                    async for frame in upstream:
                        if isinstance(frame, str):
                            await client.send_text(frame)
                        else:
                            await client.send_bytes(frame)

                import asyncio

                done, pending = await asyncio.wait(
                    {asyncio.create_task(pump_up()), asyncio.create_task(pump_down())},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
        except Exception:  # noqa: BLE001 - une coupure réseau ne doit pas tuer le worker
            pass
        finally:
            try:
                await client.close()
            except RuntimeError:
                pass

    @app.api_route(AGENT_PREFIX, methods=PROXY_METHODS)
    @app.api_route(AGENT_PREFIX + "/{path:path}", methods=PROXY_METHODS)
    async def agent_proxy(request: Request, path: str = "") -> Response:
        """Relaie l'agent sous un sous-chemin de cette origine.

        `X-Forwarded-Prefix` est la convention que suivent les SPA servies
        derrière un préfixe : elle leur permet de réécrire leurs URLs d'assets
        absolues sans rebuild. Sans cet en-tête, la page se charge mais
        réclame ses bundles à la racine, où vit la PWA — et reste blanche.
        """
        base = agent_upstream()
        if not base:
            return JSONResponse(
                {"error": f"aucun agent configuré ; renseigne {AGENT_UPSTREAM_ENV}"},
                status_code=503,
            )
        # Convention du préfixe : on le retire de l'URL amont et on l'annonce
        # dans l'en-tête. L'agent sert ses assets à la racine ; les lui
        # réclamer sous /agent renverrait sa page d'index à la place du bundle.
        url = f"{base}/{path}"
        headers = _forwardable(request.headers)
        headers["X-Forwarded-Prefix"] = AGENT_PREFIX
        headers["X-Forwarded-Proto"] = request.url.scheme
        client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=False)
        try:
            upstream = await client.send(
                client.build_request(
                    request.method,
                    url,
                    headers=headers,
                    params=dict(request.query_params),
                    content=await request.body(),
                ),
                stream=True,
            )
        except httpx.RequestError as exc:
            await client.aclose()
            # L'agent vit sur une machine qui peut être éteinte : le dire
            # franchement vaut mieux qu'une page blanche.
            return JSONResponse(
                {"error": f"agent injoignable: {type(exc).__name__}"}, status_code=502
            )

        async def drain():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            drain(),
            status_code=upstream.status_code,
            headers=_forwardable(upstream.headers, drop_host=False),
            media_type=upstream.headers.get("content-type"),
        )

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
