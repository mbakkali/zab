"""Distingue une intention humaine d'une exécution automatique, dans les conversations d'agents.

Un WorkPacket est une tâche que quelqu'un démarre. Or la majorité des sessions
d'agents ne démarrent rien : ce sont des crons horaires, des tâches planifiées,
ou des amorces injectées par l'outil avant le premier mot de l'utilisateur.

Les compter comme des tâches noierait les vraies sous le bruit — exactement ce
que font les infolettres du côté du courrier. Le critère porte sur la forme du
premier message, jamais sur son sujet.
"""

from __future__ import annotations

import re

# Exécutions déclenchées par une machine : rien n'a été demandé à cet instant.
AUTOMATED_PATTERNS = (
    re.compile(r"^\s*run\s+id\s*:\s*\S", re.I),
    re.compile(r"<scheduled-task\b", re.I),
    re.compile(r"^\s*#\s*(hourly|daily|nightly|weekly|monthly)\b", re.I),
    re.compile(r"\bcurrent\s+utc\s+time\s*:", re.I),
    re.compile(r"^\s*<<autonomous-loop", re.I),
    re.compile(r"^\s*cron\s*:", re.I),
)

# Texte injecté par l'outil avant toute parole de l'utilisateur.
BOILERPLATE_PATTERNS = (
    re.compile(r"^\s*here is a list of plugins", re.I),
    re.compile(r"^\s*<system-reminder", re.I),
    re.compile(r"^\s*caveat\s*:\s*the messages below", re.I),
    re.compile(r"^\s*<command-name>", re.I),
    re.compile(r"^\s*\{\s*\"type\"\s*:\s*\"image\"", re.I),
)

MIN_INTENT_CHARS = 15

HUMAN = "human"
AUTOMATED = "automated"
BOILERPLATE = "boilerplate"
EMPTY = "empty"


def classify_intent(text: str | None) -> str:
    """`human`, `automated`, `boilerplate` ou `empty`."""
    value = str(text or "")
    if any(pattern.search(value) for pattern in AUTOMATED_PATTERNS):
        return AUTOMATED
    if any(pattern.search(value) for pattern in BOILERPLATE_PATTERNS):
        return BOILERPLATE
    if len(value.strip()) < MIN_INTENT_CHARS:
        return EMPTY
    return HUMAN


def is_human_intent(text: str | None) -> bool:
    return classify_intent(text) == HUMAN


_TRAILING_NOISE = re.compile(r"\s*[\-–—:;,.]+\s*$")


def intent_key(text: str | None, *, max_chars: int = 70) -> str:
    """Clé de regroupement : deux reprises d'un même sujet doivent se rejoindre.

    Une session reprise, un `/loop` relancé ou une consigne reformulée décrivent
    la même tâche. Sans clé stable, chaque relance créerait un paquet de plus.
    """
    value = " ".join(str(text or "").lower().split())
    value = re.sub(r"\bhttps?://\S+", "", value)
    value = re.sub(r"\d+", "", value)
    value = re.sub(r"[^\w\sàâäéèêëîïôöùûüç'-]", " ", value)
    value = " ".join(value.split())
    return _TRAILING_NOISE.sub("", value[:max_chars]).strip()


# Préfixes que l'utilisateur tape avant sa demande réelle : commande de boucle,
# fichier joint, mention d'outil. Ils décalent le titre sans rien apprendre.
_LEADING_NOISE = (
    re.compile(r"^\s*(loop\s+)?/\w+(\s+\d+[smhj])?\s*", re.I),
    # Mêmes commandes une fois la barre oblique déjà retirée en amont.
    re.compile(r"^\s*(goal|loop|plan|compact)\s+(?=\S)", re.I),
    re.compile(r"^\s*limit\s+\d+\s+(?=\S)", re.I),
    re.compile(r"^\s*@?\"?/[\w./~-]+\"?\s*", re.I),
    re.compile(r"^\s*[-–—:,]+\s*"),
)


def intent_title(text: str | None, *, max_chars: int = 90) -> str:
    """Première phrase utile, rendue lisible dans une liste de tâches."""
    value = " ".join(str(text or "").split())
    for _ in range(3):
        for pattern in _LEADING_NOISE:
            value = pattern.sub("", value, count=1)
    for separator in (". ", " ; ", " — ", "\n"):
        head, found, _ = value.partition(separator)
        if found and len(head) >= 25:
            value = head
            break
    if len(value) > max_chars:
        value = value[: max_chars - 1].rstrip() + "…"
    return value or "Tâche sans intitulé"
