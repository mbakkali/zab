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
import re
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

# Applications embarquées, joignables derrière la même origine que la mini-app.
# Aucune configurée, la fonctionnalité disparaît : ni route, ni onglet côté PWA.
#
# `ZAB_APPS` porte la liste, un enregistrement par application :
#     slug|Libellé|https://amont ; slug2|Libellé 2|https://amont2
#
# `ZAB_AGENT_UPSTREAM` reste compris et vaut une application de slug `agent`.
# C'est ce qui permet de passer d'un amont unique à plusieurs sans redéployer
# dans le désordre : l'ancienne variable continue de marcher seule.
APPS_ENV = "ZAB_APPS"
AGENT_UPSTREAM_ENV = "ZAB_AGENT_UPSTREAM"

# Mis à 1 quand le service tourne derrière IAP : l'identité vient alors du SSO
# Google et la PWA cesse de réclamer un jeton collé à la main.
IAP_ENV = "ZAB_IAP"

APP_PREFIX = "/app"
AGENT_PREFIX = "/agent"
AGENT_SLUG = "agent"
SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
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


def iap_identity(request: Request) -> str | None:
    """Adresse de l'utilisateur authentifié par IAP, ou None.

    IAP pose `X-Goog-Authenticated-User-Email` **après** avoir vérifié le compte
    Google, et Cloud Run avec IAP n'accepte que le proxy comme appelant : un
    client direct ne peut pas fabriquer cet en-tête, il n'a pas d'entrée.

    Ce raccourci n'est donc valable que si le déploiement est réellement
    derrière IAP. On l'exige explicitement via `ZAB_IAP=1` plutôt que de le
    déduire de la présence d'un en-tête : un en-tête ne prouve rien tout seul,
    et un déploiement public qui l'accepterait serait grand ouvert.
    """
    if os.environ.get(IAP_ENV, "").strip() not in {"1", "true", "yes"}:
        return None
    raw = request.headers.get("x-goog-authenticated-user-email", "").strip()
    if not raw:
        return None
    # Format : `accounts.google.com:user@example.com`
    return raw.split(":", 1)[-1] or None


def configured_apps() -> list[dict[str, str]]:
    """Applications à relayer, dans l'ordre d'affichage des onglets.

    Un enregistrement mal formé est ignoré plutôt que fatal : une coquille dans
    une variable d'environnement ne doit pas priver la mini-app de son onglet
    VM, qui est le seul moyen de rallumer la machine.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    legacy = os.environ.get(AGENT_UPSTREAM_ENV, "").strip().rstrip("/")
    if legacy:
        label = os.environ.get("ZAB_AGENT_LABEL", "Agent").strip() or "Agent"
        out.append({"slug": AGENT_SLUG, "label": label, "upstream": legacy})
        seen.add(AGENT_SLUG)

    for record in os.environ.get(APPS_ENV, "").split(";"):
        parts = [p.strip() for p in record.split("|")]
        if len(parts) != 3:
            continue
        slug, label, upstream = parts[0].lower(), parts[1], parts[2].rstrip("/")
        if not SLUG_OK.match(slug) or not label or not upstream or slug in seen:
            continue
        out.append({"slug": slug, "label": label, "upstream": upstream})
        seen.add(slug)
    return out


def app_by_slug(slug: str) -> dict[str, str] | None:
    return next((a for a in configured_apps() if a["slug"] == slug), None)


def agent_upstream() -> str | None:
    """Base HTTP de la première application relayée, sans barre oblique finale.

    Conservée pour l'ancien chemin `/agent/` et pour les tests qui l'utilisent.
    """
    apps = configured_apps()
    return apps[0]["upstream"] if apps else None


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
        # Derrière IAP, l'identité est déjà établie par Google avant que la
        # requête n'atteigne le conteneur, et le service n'est joignable que par
        # le proxy : redemander un jeton collé à la main n'ajoute rien et
        # supprime tout l'intérêt du SSO.
        if (identity := iap_identity(request)) is not None:
            request.state.iap_user = identity
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
        # `sso` dit seulement *comment* on s'authentifie, pas *qui* est connecté :
        # c'est ce dont la PWA a besoin pour ne pas afficher un écran de jeton
        # là où Google a déjà fait le travail.
        return {
            "status": "ok",
            "service": "zab-remote",
            "sso": os.environ.get(IAP_ENV, "").strip() in {"1", "true", "yes"},
        }

    @app.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        """Qui est connecté, quand l'identité vient d'IAP."""
        return {"email": getattr(request.state, "iap_user", None)}

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

    @app.get("/api/apps")
    def apps_info() -> dict[str, Any]:
        """Dit à la PWA quels onglets exister, dans quel ordre et sous quel nom.

        L'amont n'est pas exposé : le téléphone n'a besoin que du chemin local,
        et publier les noms d'hôtes internes n'apporterait qu'une surface.
        """
        return {
            "apps": [
                {"slug": a["slug"], "label": a["label"], "path": f"{APP_PREFIX}/{a['slug']}/"}
                for a in configured_apps()
            ]
        }

    @app.get("/api/agent")
    def agent_info() -> dict[str, Any]:
        """Ancien contrat, gardé pour les PWA déjà installées sur un téléphone.

        Un service worker déjà en cache continue d'appeler cette route après le
        déploiement : la retirer afficherait une app sans onglet le temps que le
        cache tourne.
        """
        first = next(iter(configured_apps()), None)
        return {
            "enabled": first is not None,
            "path": AGENT_PREFIX + "/",
            "label": first["label"] if first else "Agent",
        }

    async def _relay_ws(client: WebSocket, base: str | None, path: str) -> None:
        """Relaie le WebSocket d'une application — sans lui, sa SPA reste muette."""
        import websockets

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

    @app.websocket(APP_PREFIX + "/{slug}/{path:path}")
    async def app_ws(client: WebSocket, slug: str, path: str) -> None:
        entry = app_by_slug(slug)
        await _relay_ws(client, entry["upstream"] if entry else None, path)

    @app.websocket(AGENT_PREFIX + "/{path:path}")
    async def agent_ws(client: WebSocket, path: str) -> None:
        await _relay_ws(client, agent_upstream(), path)

    async def _relay_http(request: Request, base: str | None, prefix: str, path: str) -> Response:
        """Relaie une application sous un sous-chemin de cette origine.

        `X-Forwarded-Prefix` est la convention que suivent les SPA servies
        derrière un préfixe : elle leur permet de réécrire leurs URLs d'assets
        absolues sans rebuild. Sans cet en-tête, la page se charge mais
        réclame ses bundles à la racine, où vit la PWA — et reste blanche.
        """
        if not base:
            return JSONResponse(
                {"error": f"aucune application configurée ; renseigne {APPS_ENV}"},
                status_code=503,
            )
        # Convention du préfixe : on le retire de l'URL amont et on l'annonce
        # dans l'en-tête. L'agent sert ses assets à la racine ; les lui
        # réclamer sous /agent renverrait sa page d'index à la place du bundle.
        url = f"{base}/{path}"
        headers = _forwardable(request.headers)
        headers["X-Forwarded-Prefix"] = prefix
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
            # L'application vit sur une machine qui peut être éteinte : le dire
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

    @app.api_route(APP_PREFIX + "/{slug}", methods=PROXY_METHODS)
    @app.api_route(APP_PREFIX + "/{slug}/{path:path}", methods=PROXY_METHODS)
    async def app_proxy(request: Request, slug: str, path: str = "") -> Response:
        entry = app_by_slug(slug)
        if not entry:
            return JSONResponse({"error": f"application inconnue: {slug}"}, status_code=404)
        return await _relay_http(request, entry["upstream"], f"{APP_PREFIX}/{slug}", path)

    @app.api_route(AGENT_PREFIX, methods=PROXY_METHODS)
    @app.api_route(AGENT_PREFIX + "/{path:path}", methods=PROXY_METHODS)
    async def agent_proxy(request: Request, path: str = "") -> Response:
        """Ancien chemin, conservé le temps que les PWA installées se mettent à jour."""
        return await _relay_http(request, agent_upstream(), AGENT_PREFIX, path)

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
