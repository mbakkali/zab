"""Reconnaît les expéditeurs automatiques, qui ne sont jamais un interlocuteur.

Un fil de recrutement, une alerte de facturation ou une infolettre citent
volontiers des noms d'entreprises. Sans ce filtre, une alerte d'offres d'emploi
mentionnant un client se retrouve rattachée à ce client, et le ledger accumule
des rattachements qui n'ont jamais existé.

La règle porte sur l'expéditeur, jamais sur le contenu : c'est l'adresse qui dit
si un humain a écrit, pas les mots employés.
"""

from __future__ import annotations

import re
from typing import Any

# Parties locales sans destinataire humain, y compris en français.
AUTOMATED_LOCAL_PARTS = (
    "no-reply",
    "noreply",
    "no_reply",
    "donotreply",
    "do-not-reply",
    "ne-pas-repondre",
    "nepasrepondre",
    "mailer-daemon",
    "postmaster",
    "bounce",
    "bounces",
    "notification",
    "notifications",
    "newsletter",
    "newsletters",
    "mailing",
    "jobalerts",
    "job-alerts",
    "alerts",
    "alerte",
    "alertes",
    "automated",
    "automatique",
    "noreponse",
)

# Diffuseurs dont aucune adresse ne correspond à un interlocuteur direct.
BULK_DOMAINS = (
    "linkedin.com",
    "glassdoor.com",
    "indeed.com",
    "welcometothejungle.com",
    "mailchimp.com",
    "sendgrid.net",
    "substack.com",
    "eventbrite.com",
    "meetup.com",
    "calendar.google.com",
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _first_email(value: Any) -> str | None:
    if isinstance(value, dict):
        for field in ("email", "address", "display_name"):
            raw = value.get(field)
            if raw and (match := _EMAIL_RE.search(str(raw))):
                return match.group(0).lower()
        return None
    if value and (match := _EMAIL_RE.search(str(value))):
        return match.group(0).lower()
    return None


def is_automated_address(address: str | None) -> bool:
    if not address or "@" not in address:
        return False
    local, _, domain = address.lower().partition("@")
    if any(domain == d or domain.endswith(f".{d}") for d in BULK_DOMAINS):
        return True
    # Comparaison sur les segments : `alerts@` compte, `real-estate@` non.
    segments = set(re.split(r"[.\-_+]", local)) | {local}
    return any(part in segments for part in AUTOMATED_LOCAL_PARTS)


def is_automated_event(event: dict[str, Any]) -> bool:
    """Vrai si l'évènement provient d'un émetteur automatique.

    Seuls les messages sont concernés : un évènement d'agenda porte souvent une
    adresse technique alors qu'il représente un vrai rendez-vous.
    """
    if str(event.get("source")) == "calendar" or str(event.get("direction")) == "meeting":
        return False
    return is_automated_address(_first_email(event.get("actor")))


def automated_reason(event: dict[str, Any]) -> str | None:
    address = _first_email(event.get("actor"))
    if not address or not is_automated_event(event):
        return None
    domain = address.partition("@")[2]
    if any(domain == d or domain.endswith(f".{d}") for d in BULK_DOMAINS):
        return f"bulk_domain:{domain}"
    return f"automated_local_part:{address.partition('@')[0]}"
