"""Factory FastAPI : API /api + statique zab-ui/dist si présent."""

from __future__ import annotations

import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from zab.api import routes
from zab.paths import config_dir, skills_root_from_config_file_only, zab_ui_dist_dir
from zab.services.pm_env_sync import apply_pm_tokens_from_user_dotenv
from zab.services import request_logs


def create_app() -> FastAPI:
    from zab.user_config import ensure_user_config_exists

    ensure_user_config_exists()

    sr = skills_root_from_config_file_only()
    if sr is not None:
        env_file = sr / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
    zab_env = config_dir() / ".env"
    if zab_env.is_file():
        load_dotenv(zab_env, override=False)
    apply_pm_tokens_from_user_dotenv()
    app = FastAPI(title="zab", version="0.2.0")

    @app.middleware("http")
    async def request_log_middleware(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path.startswith("/api/logs/"):
            return await call_next(request)
        request_id = request.headers.get("x-zab-request-id") or uuid.uuid4().hex
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = round((time.monotonic() - started) * 1000)
            request_logs.record_event(
                surface="api",
                component=_api_log_component(path),
                level="ERROR",
                request_id=request_id,
                actor=request_logs.actor_context(surface="api", source="http", request=request),
                scope=request_logs.resolve_scope(args=dict(request.query_params)),
                request={
                    "name": f"{request.method} {path}",
                    "method": request.method,
                    "path": path,
                    "args_redacted": {"query": dict(request.query_params)},
                    "input_hash": request_logs.input_hash(dict(request.query_params)),
                },
                result={
                    "status": "error",
                    "duration_ms": duration,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                },
            )
            raise
        duration = round((time.monotonic() - started) * 1000)
        response.headers["X-Zab-Request-Id"] = request_id
        status = getattr(response, "status_code", 0)
        request_logs.record_event(
            surface="api",
            component=_api_log_component(path),
            level="ERROR" if status >= 500 else ("WARNING" if status >= 400 else "INFO"),
            request_id=request_id,
            actor=request_logs.actor_context(surface="api", source="http", request=request),
            scope=request_logs.resolve_scope(args=dict(request.query_params)),
            request={
                "name": f"{request.method} {path}",
                "method": request.method,
                "path": path,
                "args_redacted": {"query": dict(request.query_params)},
                "input_hash": request_logs.input_hash(dict(request.query_params)),
            },
            result={
                "status": "ok" if status < 400 else "error",
                "duration_ms": duration,
                "http_status": status,
            },
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
            "http://127.0.0.1:5280",
            "http://localhost:5280",
            "http://127.0.0.1:5281",
            "http://localhost:5281",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes.router, prefix="/api")

    dist_dir = zab_ui_dist_dir()
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="spa")
    else:

        @app.get("/")
        async def root() -> JSONResponse:
            return JSONResponse(
                {
                    "service": "zab",
                    "api": "/api/health",
                    "hint": "Build front : depuis la racine du dépôt zab : cd zab-ui && npm run build — ou dev : npm run dev (proxy /api)",
                }
            )

    return app


def _api_log_component(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    return f"api.{parts[1]}" if len(parts) > 1 else "api"
