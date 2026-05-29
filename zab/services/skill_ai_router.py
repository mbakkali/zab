"""Choix de placement d'une nouvelle skill, avec IA best-effort puis fallback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from zab.services.workspace_projects import infer_org_slug


@dataclass
class SkillPlacement:
    scope: str
    org: str
    reason: str
    project_path: str | None = None
    provider: str | None = None


Runner = Callable[[str, str, int], str]


def _prompt(name: str, description: str, project_path: Path | None, org: str | None) -> str:
    return (
        "Tu dois choisir où créer une Agent Skill zab.\n"
        "Réponds uniquement en JSON compact avec: scope ('global' ou 'project'), org, reason.\n"
        "Règles: project = spécifique au repo courant; global = réutilisable cross-projets.\n"
        f"Nom: {name}\n"
        f"Description: {description}\n"
        f"Projet courant: {project_path or ''}\n"
        f"Org suggérée: {org or ''}\n"
    )


def _extract_json(text: str) -> dict[str, object] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def _run_local_cli(provider: str, prompt: str, timeout_sec: int) -> str:
    if provider == "openrouter":
        return _run_openrouter(prompt, timeout_sec)
    if shutil.which(provider) is None:
        raise RuntimeError(f"{provider} absent du PATH")
    cmd_by_provider = {
        "gemini": ["gemini", "-p", prompt],
        "claude": ["claude", "-p", prompt],
        "codex": ["codex", "exec", prompt],
        "kimi": ["kimi", "-p", prompt],
    }
    cmd = cmd_by_provider.get(provider, [provider, prompt])
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_sec, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"{provider} failed")
    return proc.stdout


def _run_openrouter(prompt: str, timeout_sec: int) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY absent")
    import httpx

    model = os.environ.get("OPENROUTER_SKILL_ROUTER_MODEL", "deepseek/deepseek-chat")
    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=timeout_sec,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise RuntimeError("OpenRouter response without choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise RuntimeError("OpenRouter response without content")
    return content


def _heuristic(name: str, description: str, project_path: Path | None, org: str | None) -> SkillPlacement:
    if project_path is not None:
        resolved = project_path.expanduser().resolve()
        inferred = org or infer_org_slug(resolved.name)
        return SkillPlacement(
            scope="project",
            org=inferred,
            project_path=str(resolved),
            reason="Projet fourni: placement local pour éviter de publier une skill spécifique.",
        )
    return SkillPlacement(
        scope="global",
        org=org or "common",
        reason="Aucun projet fourni: placement global par défaut.",
    )


def _from_ai(raw: dict[str, object], *, project_path: Path | None, fallback_org: str, provider: str) -> SkillPlacement | None:
    scope = str(raw.get("scope") or "").strip().lower()
    if scope not in ("global", "project"):
        return None
    org = str(raw.get("org") or fallback_org or "common").strip().lower() or "common"
    reason = str(raw.get("reason") or "Décision IA").strip()
    if scope == "project" and project_path is None:
        scope = "global"
        reason += " (corrigé: aucun projet fourni)"
    return SkillPlacement(
        scope=scope,
        org=org,
        reason=reason,
        project_path=str(project_path.expanduser().resolve()) if scope == "project" and project_path else None,
        provider=provider,
    )


def choose_skill_placement(
    name: str,
    description: str = "",
    *,
    project_path: str | Path | None = None,
    org: str | None = None,
    use_ai: bool = True,
    providers: list[str] | None = None,
    timeout_sec: int = 20,
    runner: Runner | None = None,
) -> SkillPlacement:
    project = Path(project_path).expanduser().resolve() if project_path else None
    fallback = _heuristic(name, description, project, org)
    if not use_ai:
        return fallback
    run = runner or _run_local_cli
    prompt = _prompt(name, description, project, org)
    for provider in providers or ["gemini", "claude", "codex", "kimi", "openrouter"]:
        try:
            raw = _extract_json(run(provider, prompt, timeout_sec))
            if raw is None:
                continue
            placement = _from_ai(raw, project_path=project, fallback_org=fallback.org, provider=provider)
            if placement is not None:
                return placement
        except Exception:
            continue
    return fallback
