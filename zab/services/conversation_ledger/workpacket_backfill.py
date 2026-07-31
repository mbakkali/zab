"""Réécrit les WorkPackets stockés à partir des faits du ledger.

La découverte crée un paquet par cluster organisation/workstream, mais son titre
reste une étiquette (`Org - Workstream`), ses actions sont le gabarit générique de
l'intake, et son état ne bouge jamais de `candidate`. Résultat : une liste de
paquets indistinguables, dont aucun ne dit quoi faire ensuite.

Ce module ne réinvente rien : il relit les évènements déjà rattachés au paquet et
en dérive des faits vérifiables — dernier échange, sens de cet échange, silence
écoulé, réunion à venir, canaux utilisés — puis en tire un titre, un état et des
actions qui citent ces faits. Toute conclusion est traçable jusqu'à un évènement.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

ACTIVE_WINDOW_DAYS = 14
DORMANT_WINDOW_DAYS = 60
FOLLOW_UP_SILENCE_DAYS = 7

SOURCE_LABELS = {
    "gmail": "e-mail",
    "calendar": "agenda",
    "whatsapp": "WhatsApp",
    "fireflies": "réunion",
    "imessage": "iMessage",
    "attio": "CRM",
}


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _actor_name(event: dict[str, Any]) -> str | None:
    actor = event.get("actor")
    if isinstance(actor, dict):
        name = actor.get("display_name") or actor.get("email")
        if name:
            return str(name)
    for counterparty in event.get("counterparties") or []:
        if isinstance(counterparty, dict):
            name = counterparty.get("display_name") or counterparty.get("address") or counterparty.get("email")
            if name:
                return str(name)
        elif counterparty:
            return str(counterparty)
    return None


def _identity_key(raw: str | None) -> str | None:
    """Clé de comparaison d'identité : l'adresse si présente, sinon le nom."""
    if not raw:
        return None
    value = str(raw).strip().strip('"').strip("'")
    if "<" in value and ">" in value:
        value = value[value.index("<") + 1 : value.index(">")]
    return value.strip().lower() or None


def _self_identities(events: list[dict[str, Any]]) -> set[str]:
    """Identités de l'utilisateur, apprises de ses propres messages sortants.

    Sans cela, un fil où l'utilisateur figure comme expéditeur produit un
    « répondre à soi-même », l'erreur la plus visible d'un backfill naïf.
    """
    identities: set[str] = set()
    for event in events:
        if str(event.get("direction")) != "outbound":
            continue
        key = _identity_key(_actor_name(event))
        if key:
            identities.add(key)
    return identities


def _short_name(raw: str | None) -> str | None:
    """Prénom ou libellé court, à partir d'un nom complet ou d'une adresse."""
    if not raw:
        return None
    value = str(raw).strip().strip('"').strip("'")
    if "<" in value:
        value = value.split("<", 1)[0].strip().strip('"').strip("'")
    if "@" in value:
        value = value.split("@", 1)[0]
    value = value.replace(".", " ").replace("_", " ").strip()
    if not value:
        return None
    first = value.split()[0]
    # Les carnets d'adresses écrivent souvent le patronyme en capitales.
    if first.isupper() and len(first) > 1:
        first = first.capitalize()
    return first[:1].upper() + first[1:]


def _clean_subject(raw: Any, *, max_chars: int = 68) -> str:
    """Objet lisible : un corps de message WhatsApp n'est pas un objet d'e-mail."""
    subject = " ".join(str(raw or "").split())
    for prefix in ("Re :", "Re:", "RE:", "TR :", "TR:", "Fwd:", "Fw:"):
        while subject.startswith(prefix):
            subject = subject[len(prefix):].strip()
    if len(subject) > max_chars:
        subject = subject[: max_chars - 1].rstrip() + "…"
    return subject or "sans objet"


def _is_scheduled(event: dict[str, Any]) -> bool:
    """Seul un évènement d'agenda constitue une échéance à préparer.

    Un e-mail horodaté dans le futur reste un e-mail : le traiter comme une
    réunion produisait des « préparer la réunion » sur de simples messages.
    """
    return str(event.get("source")) == "calendar" or str(event.get("direction")) == "meeting"


def _calendar_days_between(start: datetime, end: datetime) -> int:
    """Écart en jours calendaires, pour ne pas appeler « aujourd'hui » un demain matin."""
    return (end.astimezone(start.tzinfo).date() - start.date()).days


def collect_facts(events: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    """Faits vérifiables extraits des évènements rattachés à un paquet."""
    reference = now or datetime.now(timezone.utc)
    dated = [(ts, e) for e in events if (ts := _parse(e.get("timestamp"))) is not None]
    dated.sort(key=lambda pair: pair[0])
    # Un message ne peut pas être futur : un horodatage en avance vient d'un fuseau
    # ou d'une horloge décalée. Le rejeter faisait disparaître le dernier échange
    # de l'analyse, et le contact retenu devenait celui de la veille.
    past = [(ts, e) for ts, e in dated if ts <= reference or not _is_scheduled(e)]
    upcoming = [(ts, e) for ts, e in dated if ts > reference and _is_scheduled(e)]

    last_ts, last_event = past[-1] if past else (None, None)
    next_ts, next_event = upcoming[0] if upcoming else (None, None)

    mine = _self_identities(events)
    counterparty = None
    for _ts, event in reversed(past):
        if str(event.get("direction")) != "inbound":
            continue
        raw = _actor_name(event)
        if _identity_key(raw) in mine:
            continue
        counterparty = _short_name(raw)
        if counterparty:
            break

    return {
        "event_count": len(events),
        "dated_event_count": len(dated),
        "last_event_at": last_ts.isoformat() if last_ts else None,
        "last_direction": str(last_event.get("direction")) if last_event else None,
        "last_source": str(last_event.get("source")) if last_event else None,
        "last_subject": _clean_subject(last_event.get("title")) if last_event else None,
        "days_since_last_event": max(0, _calendar_days_between(last_ts, reference)) if last_ts else None,
        "last_is_message": bool(last_event and not _is_scheduled(last_event)),
        "next_event_at": next_ts.isoformat() if next_ts else None,
        "next_event_title": _clean_subject(next_event.get("title")) if next_event else None,
        "next_event_in_days": _calendar_days_between(reference, next_ts) if next_ts else None,
        "awaiting_reply_from_us": bool(
            last_event
            and str(last_event.get("direction")) == "inbound"
            and _identity_key(_actor_name(last_event)) not in mine
        ),
        "counterparty": counterparty,
        "channel_mix": dict(Counter(str(e.get("source") or "inconnu") for e in events).most_common()),
    }


def derive_state(facts: dict[str, Any]) -> str:
    """État canonique déduit de l'activité, jamais d'une intuition."""
    if facts.get("next_event_at"):
        return "active"
    days = facts.get("days_since_last_event")
    if days is None:
        return "candidate"
    if days <= ACTIVE_WINDOW_DAYS:
        return "active"
    if days <= DORMANT_WINDOW_DAYS:
        return "candidate"
    return "archived"


def _horizon(days: int | None) -> str:
    if days == 0:
        return "aujourd'hui"
    if days == 1:
        return "demain"
    return f"dans {days} j"


def _follow_up_date(facts: dict[str, Any]) -> str | None:
    last = _parse(facts.get("last_event_at"))
    if not last:
        return None
    return (last + timedelta(days=FOLLOW_UP_SILENCE_DAYS)).date().isoformat()


def _scope(organization_label: str, workstream_label: str) -> str:
    """Organisation, plus le workstream quand il distingue deux paquets du même client."""
    org = organization_label.strip() or "Sans organisation"
    workstream = workstream_label.strip()
    if not workstream or workstream.lower() in {org.lower(), "unclassified"}:
        return org
    # Séparateur distinct du « / » présent dans beaucoup de noms de clients.
    return f"{org} · {workstream}"


def derive_title(facts: dict[str, Any], *, organization_label: str, workstream_label: str) -> str:
    scope = _scope(organization_label, workstream_label)
    subject = facts.get("last_subject") or workstream_label or "sujet inconnu"
    days = facts.get("days_since_last_event")
    is_message = facts.get("last_is_message")

    if facts.get("next_event_at"):
        return f"{scope} — préparer « {facts.get('next_event_title')} » ({_horizon(facts.get('next_event_in_days'))})"
    if facts.get("awaiting_reply_from_us"):
        who = facts.get("counterparty")
        return f"{scope} — répondre {f'à {who}' if who else 'au dernier message'} : {subject}"
    if not is_message and days is not None:
        return f"{scope} — donner suite à « {subject} »"
    if days is not None and days >= FOLLOW_UP_SILENCE_DAYS:
        return f"{scope} — relancer après {days} j de silence : {subject}"
    if days is not None:
        return f"{scope} — en attente de réponse : {subject}"
    return f"{scope} — sujet à qualifier"


def derive_actions(facts: dict[str, Any], *, organization_label: str) -> list[str]:
    """Une à trois actions concrètes, chacune adossée à un fait daté."""
    actions: list[str] = []
    days = facts.get("days_since_last_event")
    channel = SOURCE_LABELS.get(str(facts.get("last_source")), str(facts.get("last_source") or "canal inconnu"))
    who = facts.get("counterparty")

    if facts.get("next_event_at"):
        actions.append(
            f"Préparer « {facts.get('next_event_title')} » prévu le {str(facts.get('next_event_at'))[:10]} "
            f"({_horizon(facts.get('next_event_in_days'))}) : ordre du jour et points à trancher."
        )
    if facts.get("awaiting_reply_from_us"):
        since = "reçu aujourd'hui" if not days else f"sans réponse depuis {days} j"
        actions.append(
            f"Répondre à {who or 'l’interlocuteur'} sur « {facts.get('last_subject')} » — {channel}, {since}."
        )
    elif not facts.get("last_is_message") and days is not None:
        # Le dernier fait est un point d'agenda, pas un message : on n'attend
        # aucune réponse, on doit une suite.
        when = "aujourd'hui" if days == 0 else f"il y a {days} j"
        actions.append(
            f"Donner suite à « {facts.get('last_subject')} » ({when}) : relevé de décisions et prochaine étape."
        )
    elif days is not None and days >= FOLLOW_UP_SILENCE_DAYS:
        actions.append(
            f"Relancer {organization_label} : dernier message sortant par {channel} il y a {days} j, sans réponse."
        )
    elif days is not None:
        due = _follow_up_date(facts)
        wait = f"Attendre la réponse{f' de {who}' if who else ''} — envoyé il y a {days} j par {channel}"
        actions.append(f"{wait} ; relancer à partir du {due}." if due else f"{wait}.")

    if days is not None and days > DORMANT_WINDOW_DAYS:
        actions.append(
            f"Confirmer si le sujet est clos : aucune activité depuis {days} j sur {facts.get('event_count')} échanges."
        )

    if not actions:
        actions.append(
            f"Qualifier le sujet : {facts.get('event_count')} échanges rattachés, aucune échéance ni attente identifiée."
        )
    return actions[:3]


def rebuild_packet(
    packet: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Renvoie (paquet réécrit, différences). Le paquet d'entrée n'est pas muté."""
    facts = collect_facts(events, now=now)
    organization_label = str(packet.get("organization_label") or "")
    workstream_label = str(packet.get("client_workstream_label") or "")

    updated = dict(packet)
    updated["title"] = derive_title(
        facts, organization_label=organization_label, workstream_label=workstream_label
    )
    updated["state"] = derive_state(facts)
    updated["actions"] = derive_actions(facts, organization_label=organization_label)

    if updated.get("confidence") in (None, "") and events:
        scores = [float(e.get("workstream_confidence") or 0) for e in events]
        if any(scores):
            updated["confidence"] = round(sum(scores) / len(scores), 2)

    metadata = dict(updated.get("metadata") or {})
    metadata["ledger_facts"] = facts
    updated["metadata"] = metadata
    updated["updated_at"] = (now or datetime.now(timezone.utc)).isoformat()

    changes = {
        field: {"before": packet.get(field), "after": updated.get(field)}
        for field in ("title", "state", "actions", "confidence")
        if packet.get(field) != updated.get(field)
    }
    return updated, changes
