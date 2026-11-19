"""Le seul endroit de zab qui parle à un modèle par API : la passerelle LiteLLM.

Contrat : docs/knowledge/litellm-contrat-applications.md du cowork (décision du 2026-11-08).

- `LLM_BASE_URL` : l'adresse OpenAI-compatible de la passerelle (défaut ci-dessous, tailnet seulement).
- `LLM_API_KEY`  : la clé virtuelle de zab. Absente → `LLMIndisponible`, jamais de repli sur un fournisseur.
- `LLM_MODEL`    : un alias de la passerelle (`flash`, `haiku`, `sonnet`, `gemini-flash`), défaut `flash`.
"""

from __future__ import annotations

import os

import httpx

ENV_URL = "LLM_BASE_URL"
ENV_CLE = "LLM_API_KEY"
ENV_MODELE = "LLM_MODEL"
URL_PAR_DEFAUT = "https://litellm.tailef30ea.ts.net/v1"
MODELE_PAR_DEFAUT = "flash"


class LLMIndisponible(RuntimeError):
    """La passerelle n'est pas configurée (clé absente) ou a mal répondu."""


def base_url() -> str:
    return (os.environ.get(ENV_URL) or URL_PAR_DEFAUT).strip().rstrip("/")


def api_key() -> str:
    cle = (os.environ.get(ENV_CLE) or "").strip()
    if not cle:
        raise LLMIndisponible(f"{ENV_CLE} absente : zab n'appelle aucun modèle sans la clé de la passerelle")
    return cle


def modele(choisi: str | None = None) -> str:
    return (choisi or os.environ.get(ENV_MODELE) or MODELE_PAR_DEFAUT).strip()


def chat(prompt: str, *, model: str | None = None, temperature: float = 0, timeout: float = 20) -> str:
    """Un message utilisateur, une réponse texte, par `POST {LLM_BASE_URL}/chat/completions`."""
    reponse = httpx.post(
        f"{base_url()}/chat/completions",
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
        json={
            "model": modele(model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
        timeout=timeout,
    )
    reponse.raise_for_status()
    payload = reponse.json()
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise LLMIndisponible("réponse de la passerelle sans choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LLMIndisponible("réponse de la passerelle sans contenu")
    return content
