"""Factory FastAPI : API /api + statique zab-ui/dist si présent."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from zab.api import routes
from zab.paths import skills_root_from_config_file_only, zab_ui_dist_dir
from zab.services.pm_env_sync import apply_pm_tokens_from_user_dotenv


def create_app() -> FastAPI:
    from zab.user_config import ensure_user_config_exists

    ensure_user_config_exists()

    sr = skills_root_from_config_file_only()
    if sr is not None:
        env_file = sr / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
    apply_pm_tokens_from_user_dotenv()
    app = FastAPI(title="zab", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
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
