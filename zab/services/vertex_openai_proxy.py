"""Proxy OpenAI-compatible vers l'endpoint Vertex (jeton SA rafraîchi côté zab, pas dans le process Hermes)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_VERTEX_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


def _project_id() -> str:
    v = (os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or "").strip()
    if not v:
        raise ValueError("GOOGLE_CLOUD_PROJECT (ou GCP_PROJECT) requis pour le proxy Vertex")
    return v


def _location() -> str:
    return (os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get("VERTEX_LOCATION") or "global").strip() or "global"


def _credentials_path() -> Path | None:
    raw = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_file() else None


def upstream_openapi_base() -> str:
    """URL de base OpenAPI Vertex (sans /v1/chat/completions)."""
    project = _project_id()
    loc = _location()
    return (
        f"https://aiplatform.googleapis.com/v1beta1/projects/{project}"
        f"/locations/{loc}/endpoints/openapi"
    )


def upstream_chat_completions_url() -> str:
    return f"{upstream_openapi_base()}/chat/completions"


def default_model_id() -> str:
    for key in ("VERTEX_DEFAULT_MODEL", "GEMINI_MODEL", "GOOGLE_CLOUD_MODEL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return "gemini-2.0-flash"


def refresh_access_token() -> str:
    """Jeton OAuth2 SA (cloud-platform), rafraîchi à chaque appel."""
    path = _credentials_path()
    if path is None:
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS doit pointer vers un fichier JSON de service account valide."
        )
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import service_account
    except ImportError as e:  # pragma: no cover - dépendance optionnelle
        raise RuntimeError(
            "Installez google-auth (ex. pip install 'google-auth[requests]') pour le proxy Vertex."
        ) from e

    creds = service_account.Credentials.from_service_account_file(
        str(path),
        scopes=_VERTEX_SCOPES,
    )
    creds.refresh(GoogleAuthRequest())
    if not creds.token:
        raise ValueError("Échec refresh du jeton SA (token vide)")
    return creds.token


def public_status() -> dict[str, Any]:
    """État sans secret : chemins, projet, test refresh optionnel."""
    cred_path = _credentials_path()
    project_ok = bool((os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or "").strip())
    out: dict[str, Any] = {
        "credentials_configured": cred_path is not None,
        "credentials_path": str(cred_path) if cred_path else None,
        "project_configured": project_ok,
        "location": _location() if project_ok else None,
        "upstream_chat_url_template": f"{upstream_openapi_base()}/chat/completions" if project_ok else None,
        "default_model": default_model_id(),
        "token_refresh_ok": None,
        "token_refresh_error": None,
    }
    if cred_path is None or not project_ok:
        out["ready"] = False
        return out
    try:
        refresh_access_token()
        out["token_refresh_ok"] = True
        out["ready"] = True
    except (OSError, ValueError, RuntimeError) as e:
        out["token_refresh_ok"] = False
        out["token_refresh_error"] = str(e)
        out["ready"] = False
    return out


def openai_models_list_payload() -> dict[str, Any]:
    mid = default_model_id()
    return {
        "object": "list",
        "data": [
            {
                "id": mid,
                "object": "model",
                "created": 0,
                "owned_by": "vertex",
            }
        ],
    }
