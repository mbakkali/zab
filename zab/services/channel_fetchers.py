"""Fetchers réels pour les canaux de communication.

Chaque fetcher renvoie un tuple :
    (action_items, sync_summary, status, reason)

- action_items   : list[dict] au schéma des actions du dashboard, ou []
- sync_summary   : dict (peut inclure unread_count, received_today, …) ou None
- status         : "ok" | "degraded" | "error"
- reason         : message d'erreur lisible (None si status == "ok")

Si la source n'est pas configurée (CLI absente, env manquantes), on retourne
status="degraded" et reason explicatif, plutôt que de fabriquer des données.
Les appelants peuvent alors décider de tomber sur un autre fetcher ou d'afficher
un état dégradé dans le cockpit.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx


_DOTENV_PATHS = (
    Path.home() / ".config" / "zab" / ".env",
    Path.home() / ".hermes" / ".env",
)
_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    """Charge nos .env standards dans os.environ sans écraser ce qui est déjà défini."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    for p in _DOTENV_PATHS:
        if not p.is_file():
            continue
        try:
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            continue
    _DOTENV_LOADED = True

_GOG_TIMEOUT_S = 12
_COMPOSIO_TIMEOUT_S = 20
_EVOLUTION_TIMEOUT_S = 10

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _clean_stderr(text: str) -> str:
    """Strip ANSI codes and skip CLI update-notice banners ('Update available:', 'Run … to update')."""
    if not text:
        return ""
    plain = _ANSI_RE.sub("", text)
    keep: list[str] = []
    for line in plain.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("update available") or "to update" in low:
            continue
        keep.append(s)
    return " ".join(keep)


FetcherResult = tuple[list[dict[str, Any]], dict[str, Any] | None, str, str | None]


def _slug(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return s or "x"


def _parse_iso(dt_str: str | None, fallback: datetime) -> datetime:
    if not dt_str:
        return fallback
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return fallback


# =============================================================================
# Gmail via gog
# =============================================================================

def fetch_gmail_via_gog(channel: dict[str, Any], now_dt: datetime) -> FetcherResult:
    """Récupère les non-lus via la CLI `gog gmail messages search`.

    Retourne degraded si gog est absent ou si l'OAuth n'est pas configuré.
    """
    if not shutil.which("gog"):
        return [], None, "degraded", "gog_cli_not_installed"

    address = (channel.get("email_address") or "").strip()
    if not address:
        return [], None, "degraded", "missing_email_address"

    base_cmd = ["gog", "gmail", "messages", "search", "is:unread", "-a", address, "-j", "--no-input"]
    # gog gère des clients OAuth nommés (un par compte). Si on connaît le client à partir
    # de l'org du canal (carrefour, flowmetrik, upfund…), on le passe explicitement.
    client_name = (channel.get("org") or "").strip().lower()
    if client_name and client_name not in ("personal", "perso"):
        base_cmd.extend(["--client", client_name])

    def _run(extra_flags: list[str]) -> tuple[int, str, str]:
        cp = subprocess.run(
            base_cmd + extra_flags,
            capture_output=True,
            text=True,
            timeout=_GOG_TIMEOUT_S,
        )
        return cp.returncode, cp.stdout, cp.stderr

    try:
        rc, out, err = _run(["--max", "10"])
    except FileNotFoundError:
        return [], None, "degraded", "gog_cli_not_installed"
    except subprocess.TimeoutExpired:
        return [], None, "error", "gog_timeout"

    if rc != 0:
        msg = _clean_stderr(err) or _clean_stderr(out) or f"gog_exit_{rc}"
        if "credentials" in msg.lower() or "oauth" in msg.lower():
            return [], None, "degraded", f"gog_oauth_missing: {msg[:160]}"
        return [], None, "error", msg[:200]

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [], None, "error", "gog_invalid_json"

    messages = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(messages, list):
        messages = []

    actions: list[dict[str, Any]] = []
    today_utc = now_dt.astimezone(timezone.utc).date()
    week_start = today_utc - timedelta(days=7)
    received_today = 0
    received_this_week = 0

    for m in messages[:10]:
        if not isinstance(m, dict):
            continue
        msg_id = str(m.get("id") or m.get("messageId") or m.get("threadId") or "")
        subject = str(m.get("subject") or m.get("Subject") or "(sans objet)")
        sender = str(m.get("from") or m.get("From") or "Expéditeur inconnu")
        snippet = str(m.get("snippet") or m.get("Snippet") or "")
        date_raw = m.get("date") or m.get("Date") or m.get("internalDate")
        if isinstance(date_raw, (int, float)):
            try:
                dt_obj = datetime.fromtimestamp(float(date_raw) / 1000.0, tz=timezone.utc)
            except Exception:
                dt_obj = now_dt
        else:
            dt_obj = _parse_iso(str(date_raw) if date_raw else None, now_dt)

        d = dt_obj.astimezone(timezone.utc).date()
        if d == today_utc:
            received_today += 1
        if d >= week_start:
            received_this_week += 1

        thread_id = str(m.get("threadId") or msg_id)
        url = f"https://mail.google.com/mail/u/0/#inbox/{thread_id}" if thread_id else f"mailto:{address}"

        actions.append({
            "id": f"act_gmail_{_slug(channel.get('id', 'email'))}_{_slug(msg_id)[:32]}",
            "channel_id": channel.get("id"),
            "channel_label": channel.get("label"),
            "type": "email",
            "sender": sender[:255],
            "subject": subject[:255],
            "content": snippet[:1000],
            "date": dt_obj.isoformat(),
            "url": url,
            "org": channel.get("org") or "personal",
            "is_actionable": True,
        })

    summary = {
        "unread_count": len(messages),
        "received_today": received_today,
        "received_this_week": received_this_week,
    }
    return actions, summary, "ok", None


# =============================================================================
# Email via Composio (fallback Gmail/Outlook)
# =============================================================================

_COMPOSIO_TOOLKIT_BY_CONNECTOR = {
    "outlook": "outlook",
    "microsoft365": "outlook",
    "gmail": "gmail",
}


def fetch_email_via_composio(channel: dict[str, Any], now_dt: datetime) -> FetcherResult:
    """Fallback Composio (`composio execute …`). Couvre Gmail et Outlook.

    Le slug exact dépend du toolkit Composio installé chez l'utilisateur ;
    si l'exécution échoue, on dégrade proprement.
    """
    if not shutil.which("composio"):
        return [], None, "degraded", "composio_cli_not_installed"

    connector = (channel.get("connector") or "").lower()
    toolkit = _COMPOSIO_TOOLKIT_BY_CONNECTOR.get(connector)
    if toolkit is None:
        return [], None, "degraded", f"composio_no_toolkit_for_connector:{connector or 'unset'}"

    slug = "GMAIL_FETCH_EMAILS" if toolkit == "gmail" else "OUTLOOK_LIST_MESSAGES"
    payload = {"query": "is:unread", "max_results": 10} if toolkit == "gmail" else {"top": 10, "filter": "isRead eq false"}

    try:
        cp = subprocess.run(
            ["composio", "execute", slug, "-d", json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=_COMPOSIO_TIMEOUT_S,
        )
    except FileNotFoundError:
        return [], None, "degraded", "composio_cli_not_installed"
    except subprocess.TimeoutExpired:
        return [], None, "error", "composio_timeout"

    if cp.returncode != 0:
        msg = _clean_stderr(cp.stderr) or _clean_stderr(cp.stdout) or f"composio_exit_{cp.returncode}"
        low = msg.lower()
        if "401" in msg or "unauthorized" in low or "not connected" in low or "no connected account" in low:
            return [], None, "degraded", f"composio_not_authenticated: {msg[:160]}"
        return [], None, "error", msg[:200]

    try:
        data = json.loads(cp.stdout)
    except json.JSONDecodeError:
        return [], None, "error", "composio_invalid_json"

    # On accepte plusieurs formats : { data: { messages: [...] } } ou { messages: [...] } ou liste brute.
    container = data.get("data", data) if isinstance(data, dict) else data
    messages = []
    if isinstance(container, dict):
        for key in ("messages", "value", "items", "results"):
            if isinstance(container.get(key), list):
                messages = container[key]
                break
    elif isinstance(container, list):
        messages = container

    actions: list[dict[str, Any]] = []
    for m in messages[:10]:
        if not isinstance(m, dict):
            continue
        msg_id = str(m.get("id") or m.get("messageId") or "")
        subject = str(m.get("subject") or m.get("Subject") or "(sans objet)")
        from_field = m.get("from") or m.get("From") or m.get("sender")
        if isinstance(from_field, dict):
            sender = str(from_field.get("name") or from_field.get("emailAddress", {}).get("name") or from_field.get("email") or from_field.get("emailAddress", {}).get("address") or "")
        else:
            sender = str(from_field or "Expéditeur inconnu")
        snippet = str(m.get("snippet") or m.get("bodyPreview") or "")
        date_raw = m.get("date") or m.get("receivedDateTime") or m.get("Date")
        dt_obj = _parse_iso(str(date_raw) if date_raw else None, now_dt)
        url = m.get("webLink") or m.get("url") or f"mailto:{channel.get('email_address') or ''}"

        actions.append({
            "id": f"act_composio_{_slug(channel.get('id', 'email'))}_{_slug(msg_id)[:32]}",
            "channel_id": channel.get("id"),
            "channel_label": channel.get("label"),
            "type": "email",
            "sender": sender[:255],
            "subject": subject[:255],
            "content": snippet[:1000],
            "date": dt_obj.isoformat(),
            "url": str(url),
            "org": channel.get("org") or "personal",
            "is_actionable": True,
        })

    summary = {"unread_count": len(messages)}
    return actions, summary, "ok", None


# =============================================================================
# WhatsApp via Evolution API
# =============================================================================

def _first_non_empty_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            v = value.strip()
            if v:
                return v
    return ""


def _evolution_env(channel: dict[str, Any] | None = None) -> tuple[str, str, str] | None:
    """Résout la config Evolution API depuis le canal YAML, puis l'env.

    Priorité:
    1) communication_channels[].credentials (config.yaml)
    2) clés directes du canal (config.yaml)
    3) variables d'environnement / .env
    """
    ch = channel if isinstance(channel, dict) else {}
    creds = ch.get("credentials")
    creds_dict = creds if isinstance(creds, dict) else {}

    _load_dotenv_once()

    base = _first_non_empty_str(
        creds_dict.get("evolution_api_url"),
        creds_dict.get("api_url"),
        ch.get("evolution_api_url"),
        ch.get("api_url"),
        os.environ.get("EVOLUTION_API_URL"),
    ).rstrip("/")
    key = _first_non_empty_str(
        creds_dict.get("evolution_api_key"),
        creds_dict.get("api_key"),
        ch.get("evolution_api_key"),
        ch.get("api_key"),
        os.environ.get("EVOLUTION_API_KEY"),
    )
    # Accepter EVOLUTION_INSTANCE et l'alias EVOLUTION_INSTANCE_NAME utilisé par flowmetrikwa.
    instance = _first_non_empty_str(
        creds_dict.get("evolution_instance"),
        creds_dict.get("instance"),
        ch.get("evolution_instance"),
        ch.get("instance"),
        os.environ.get("EVOLUTION_INSTANCE"),
        os.environ.get("EVOLUTION_INSTANCE_NAME"),
    )

    if not (base and key and instance):
        return None
    return base, key, instance


def _phone_from_jid(jid: str) -> str:
    return (jid or "").split("@", 1)[0]


def fetch_whatsapp_via_evolution(channel: dict[str, Any], now_dt: datetime) -> FetcherResult:
    """Liste les derniers messages WhatsApp non lus via Evolution API.

    Endpoint Evolution v2 : POST /chat/findMessages/{instance}
    """
    env = _evolution_env(channel)
    if env is None:
        return [], None, "degraded", "evolution_env_incomplete"
    base, key, instance = env

    url = f"{base}/chat/findMessages/{instance}"
    body = {
        "where": {"key": {"fromMe": False}},
        "limit": 20,
    }
    headers = {"apikey": key, "Content-Type": "application/json"}

    try:
        r = httpx.post(url, json=body, headers=headers, timeout=_EVOLUTION_TIMEOUT_S)
    except httpx.HTTPError as exc:
        return [], None, "error", f"evolution_http_error: {exc}"[:200]

    if r.status_code >= 400:
        return [], None, "error", f"evolution_http_{r.status_code}: {(r.text or '')[:160]}"

    try:
        data = r.json()
    except ValueError:
        return [], None, "error", "evolution_invalid_json"

    # Evolution renvoie selon les versions : { messages: { records: [...] } } ou liste brute.
    records: list[Any] = []
    if isinstance(data, dict):
        msgs = data.get("messages")
        if isinstance(msgs, dict) and isinstance(msgs.get("records"), list):
            records = msgs["records"]
        elif isinstance(msgs, list):
            records = msgs
        elif isinstance(data.get("records"), list):
            records = data["records"]
    elif isinstance(data, list):
        records = data

    actions: list[dict[str, Any]] = []
    seen_jids: set[str] = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        key_block = rec.get("key") or {}
        jid = str(key_block.get("remoteJid") or rec.get("remoteJid") or "")
        if not jid or jid.endswith("@g.us"):  # ignorer les groupes pour l'instant
            continue
        if jid in seen_jids:
            continue
        seen_jids.add(jid)

        push_name = str(rec.get("pushName") or rec.get("notifyName") or "").strip()
        # Tentative de récupérer un vrai numéro : participantAlt en s.whatsapp.net, sinon remoteJid.
        alt = str(rec.get("participantAlt") or key_block.get("participantAlt") or "")
        if alt.endswith("@s.whatsapp.net"):
            phone = _phone_from_jid(alt)
        elif jid.endswith("@s.whatsapp.net"):
            phone = _phone_from_jid(jid)
        else:
            phone = ""  # LID anonymisé : pas de numéro exploitable
        if phone and push_name:
            sender = f"{push_name} (+{phone})"
        elif phone:
            sender = f"+{phone}"
        elif push_name:
            sender = push_name
        else:
            sender = "Contact WhatsApp"

        message = rec.get("message") or {}
        content = (
            message.get("conversation")
            or (message.get("extendedTextMessage") or {}).get("text")
            or (message.get("imageMessage") or {}).get("caption")
            or (message.get("videoMessage") or {}).get("caption")
            or ""
        )
        content_str = str(content).strip()
        if not content_str:
            content_str = "(message non textuel)"

        ts = rec.get("messageTimestamp") or rec.get("timestamp")
        try:
            dt_obj = datetime.fromtimestamp(float(ts), tz=timezone.utc) if ts else now_dt
        except Exception:
            dt_obj = now_dt

        subject = content_str.splitlines()[0][:80] if content_str else "Message WhatsApp"

        actions.append({
            "id": f"act_wa_{_slug(channel.get('id', 'whatsapp'))}_{_slug(key_block.get('id') or jid)[:32]}",
            "channel_id": channel.get("id"),
            "channel_label": channel.get("label"),
            "type": "whatsapp",
            "sender": sender[:255],
            "subject": subject,
            "content": content_str[:1000],
            "date": dt_obj.isoformat(),
            "url": f"https://wa.me/{phone}" if phone else f"https://web.whatsapp.com/send?phone={_phone_from_jid(jid)}" if jid.endswith("@s.whatsapp.net") else "https://web.whatsapp.com/",
            "org": channel.get("org") or "personal",
            "is_actionable": True,
        })

    summary = {"unread_count": len(actions)}
    return actions, summary, "ok", None


# =============================================================================
# Dispatcher
# =============================================================================

def _slack_bot_token(channel: dict[str, Any]) -> str:
    creds = channel.get("credentials")
    creds_dict = creds if isinstance(creds, dict) else {}
    return _first_non_empty_str(
        creds_dict.get("slack_bot_token"),
        creds_dict.get("bot_token"),
        creds_dict.get("token"),
        channel.get("slack_bot_token"),
        channel.get("bot_token"),
        os.environ.get("SLACK_BOT_TOKEN"),
        os.environ.get("SLACK_TOKEN"),
    )


def check_slack_connection(channel: dict[str, Any]) -> tuple[str, str | None]:
    """Teste un token Slack via auth.test."""
    token = _slack_bot_token(channel)
    if not token:
        return "degraded", "slack_credentials_missing"

    try:
        r = httpx.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_EVOLUTION_TIMEOUT_S,
        )
        data = r.json()
    except httpx.HTTPError as exc:
        return "error", f"slack_http_error: {exc}"[:200]
    except ValueError:
        return "error", "slack_invalid_json"

    if data.get("ok"):
        return "ok", None
    return "error", str(data.get("error") or "slack_auth_failed")[:200]


def check_channel_connection(channel: dict[str, Any], now_dt: datetime) -> dict[str, Any]:
    """Exécute un check read-only pour un canal et retourne un payload normalisé."""
    ctype = (channel.get("type") or "").lower()

    if ctype == "slack":
        status, reason = check_slack_connection(channel)
        summary = {"unread_count": 0} if status == "ok" else None
        return {"status": status, "reason": reason, "sync_summary": summary, "actions_count": 0}

    actions, summary, status, reason = fetch_for_channel(channel, now_dt)
    return {
        "status": status,
        "reason": reason,
        "sync_summary": summary,
        "actions_count": len(actions),
    }


def fetch_for_channel(channel: dict[str, Any], now_dt: datetime) -> FetcherResult:
    """Choisit le bon fetcher selon le type/connecteur du canal."""
    ctype = (channel.get("type") or "").lower()
    connector = (channel.get("connector") or "").lower()

    if ctype == "email":
        if connector == "gmail":
            actions, summary, status, reason = fetch_gmail_via_gog(channel, now_dt)
            if status == "ok":
                return actions, summary, status, reason
            # fallback composio
            fb_actions, fb_summary, fb_status, fb_reason = fetch_email_via_composio(channel, now_dt)
            if fb_status == "ok":
                return fb_actions, fb_summary, "ok", f"gog_unavailable_fallback_composio (gog: {reason})"
            return [], None, "degraded", f"gog: {reason} | composio: {fb_reason}"
        # outlook / autres → composio
        actions, summary, status, reason = fetch_email_via_composio(channel, now_dt)
        return actions, summary, status, reason

    if ctype == "whatsapp":
        return fetch_whatsapp_via_evolution(channel, now_dt)

    # Types non gérés (slack, telegram) — pas de fetcher pour l'instant.
    return [], None, "degraded", f"no_fetcher_for_type:{ctype or 'unknown'}"
