"""Notifications non bloquantes pour zab (imports skills, etc.)."""

from __future__ import annotations

import os
from typing import Any

import httpx


def notify_skills_auto_sync(
    *,
    slugs: list[str],
    notify: bool,
    channel: str,
) -> dict[str, Any]:
    """
    Envoie un résumé d'import de skills. Ne lève pas : erreurs réseau → dict avec ``error``.
    Secrets uniquement via variables d'environnement (jamais dans le YAML zab).
    """
    if not notify:
        return {"sent": False, "skipped": True, "reason": "notify_disabled"}
    if not slugs:
        return {"sent": False, "skipped": True, "reason": "empty_slugs"}
    title = f"zab: {len(slugs)} skill(s) importée(s)"
    body = ", ".join(slugs[:40]) + ("…" if len(slugs) > 40 else "")
    text = f"{title}: {body}"
    ch = (channel or "evolution").strip().lower()
    if ch == "telegram":
        return _telegram_send(text)
    return _evolution_send(text)


def _evolution_send(text: str) -> dict[str, Any]:
    base = (os.environ.get("EVOLUTION_API_URL") or "").strip().rstrip("/")
    key = (os.environ.get("EVOLUTION_API_KEY") or "").strip()
    instance = (os.environ.get("EVOLUTION_INSTANCE") or "").strip()
    number = (os.environ.get("EVOLUTION_NOTIFY_NUMBER") or "").strip()
    if not all([base, key, instance, number]):
        return {
            "sent": False,
            "skipped": True,
            "reason": "evolution_env_incomplete",
            "channel": "evolution",
        }
    url = f"{base}/message/sendText/{instance}"
    headers = {"apikey": key}
    try:
        r = httpx.post(url, json={"number": number, "text": text}, headers=headers, timeout=15.0)
        ok = 200 <= r.status_code < 300
        out: dict[str, Any] = {
            "sent": bool(ok),
            "skipped": False,
            "channel": "evolution",
            "status_code": r.status_code,
        }
        if not ok:
            out["error"] = (r.text or "")[:500]
        return out
    except Exception as exc:  # noqa: BLE001 — notification best-effort
        return {"sent": False, "skipped": False, "channel": "evolution", "error": str(exc)}


def _telegram_send(text: str) -> dict[str, Any]:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_NOTIFY_CHAT_ID") or "").strip()
    if not token or not chat:
        return {
            "sent": False,
            "skipped": True,
            "reason": "telegram_env_incomplete",
            "channel": "telegram",
        }
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = httpx.post(url, json={"chat_id": chat, "text": text[:4000]}, timeout=15.0)
        ok = 200 <= r.status_code < 300
        payload: dict[str, Any] | None = None
        try:
            payload = r.json()
        except Exception:
            payload = None
        if ok and isinstance(payload, dict) and payload.get("ok") is False:
            ok = False
        out: dict[str, Any] = {
            "sent": bool(ok),
            "skipped": False,
            "channel": "telegram",
            "status_code": r.status_code,
        }
        if not ok and isinstance(payload, dict):
            desc = payload.get("description")
            if isinstance(desc, str):
                out["error"] = desc[:500]
        elif not ok:
            out["error"] = (r.text or "")[:500]
        return out
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "skipped": False, "channel": "telegram", "error": str(exc)}
