"""Wizard interactif pour configurer un canal dans communication_channels."""

from __future__ import annotations

import shutil
from typing import Any

import typer

from zab.services.communication_channels import add_channel_config, check_channel_config

_CHANNEL_TYPES = ("email", "slack", "whatsapp")
_TYPE_LABELS = {
    "email": "E-mail",
    "slack": "Slack",
    "whatsapp": "WhatsApp",
}


def available_email_connectors() -> list[dict[str, str]]:
    """Connecteurs email détectés localement (priorité gog puis composio)."""
    options: list[dict[str, str]] = []
    seen: set[str] = set()

    if shutil.which("gog"):
        options.append({"connector": "gmail", "label": "Gmail via gog CLI", "transport": "gog"})
        seen.add("gmail")

    if shutil.which("composio"):
        if "gmail" not in seen:
            options.append({"connector": "gmail", "label": "Gmail via Composio", "transport": "composio"})
            seen.add("gmail")
        options.append({"connector": "outlook", "label": "Outlook via Composio", "transport": "composio"})

    return options


def _prompt_choice(label: str, choices: list[str], *, default: str | None = None) -> str:
    mapping = {str(i + 1): c for i, c in enumerate(choices)}
    lines = [f"{i + 1}) {c}" for i, c in enumerate(choices)]
    typer.echo(label)
    for line in lines:
        typer.echo(f"  {line}")
    while True:
        raw = typer.prompt("Choix", default=default or "1").strip()
        if raw in mapping:
            return mapping[raw]
        if raw in choices:
            return raw
        typer.echo(typer.style("Choix invalide — réessayez.", fg=typer.colors.RED))


def _prompt_credentials_whatsapp() -> dict[str, str]:
    typer.echo("\nCredentials WhatsApp (Evolution API) :")
    return {
        "evolution_api_url": typer.prompt("URL Evolution API", default="https://wa.fmetrik.com").strip().rstrip("/"),
        "evolution_api_key": typer.prompt("Clé API Evolution", hide_input=True).strip(),
        "evolution_instance": typer.prompt("Nom d'instance Evolution").strip(),
    }


def _prompt_credentials_slack() -> dict[str, str]:
    typer.echo("\nCredentials Slack :")
    creds: dict[str, str] = {
        "slack_bot_token": typer.prompt("Bot token (xoxb-…)", hide_input=True).strip(),
    }
    channel_id = typer.prompt("Channel ID (optionnel)", default="").strip()
    if channel_id:
        creds["slack_channel_id"] = channel_id
    return creds


def _documentation_for_type(channel_type: str) -> str:
    defaults = {
        "slack": "https://api.slack.com/authentication/token-types#bot",
        "whatsapp": "https://doc.evolution-api.com/",
    }
    default = defaults.get(channel_type, "")
    doc = typer.prompt("Documentation / URL de référence", default=default).strip()
    return doc


def build_channel_payload(
    *,
    label: str,
    org: str,
    channel_type: str,
    connector: str,
    email_address: str | None = None,
    documentation: str | None = None,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "label": label,
        "type": channel_type,
        "connector": connector,
        "org": org,
        "email_address": email_address,
        "documentation": documentation,
        "credentials": credentials,
    }


def setup_channel_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Écrit le canal dans config.yaml puis exécute un check de connexion."""
    new_chan = add_channel_config(
        label=str(payload["label"]),
        channel_type=str(payload["type"]),
        connector=str(payload["connector"]),
        email_address=payload.get("email_address"),
        org=str(payload.get("org") or "personal"),
        documentation=payload.get("documentation"),
        credentials=payload.get("credentials"),
    )
    return check_channel_config(str(new_chan["id"]))


def run_channel_setup_wizard() -> dict[str, Any]:
    """Wizard CLI : email si connecteur présent, sinon API Slack/WhatsApp."""
    typer.echo(typer.style("\n=== zab channels setup ===\n", bold=True))

    label = typer.prompt("Nom d'affichage du canal").strip()
    if not label:
        raise typer.Exit(code=1)

    org = typer.prompt("Organisation (slug)", default="personal").strip() or "personal"

    type_choices = list(_CHANNEL_TYPES)
    type_labels = [_TYPE_LABELS[t] for t in type_choices]
    picked_label = _prompt_choice("\nType de canal :", type_labels)
    channel_type = type_choices[type_labels.index(picked_label)]

    documentation: str | None = None
    credentials: dict[str, Any] | None = None
    connector = ""
    email_address: str | None = None

    if channel_type == "email":
        options = available_email_connectors()
        if not options:
            typer.echo(
                typer.style(
                    "Aucun connecteur email détecté (gog ou composio). Installez-en un puis relancez.",
                    fg=typer.colors.RED,
                )
            )
            raise typer.Exit(code=1)

        labels = [o["label"] for o in options]
        picked = _prompt_choice("\nConnecteur email disponible :", labels)
        selected = next(o for o in options if o["label"] == picked)
        connector = selected["connector"]
        email_address = typer.prompt("Adresse e-mail").strip()
        if not email_address:
            typer.echo(typer.style("Adresse e-mail requise.", fg=typer.colors.RED))
            raise typer.Exit(code=1)
        documentation = typer.prompt(
            "Documentation (optionnel)",
            default="https://github.com/steipete/gogcli" if connector == "gmail" else "https://docs.composio.dev",
        ).strip() or None

    elif channel_type == "whatsapp":
        connector = "evolution-api"
        documentation = _documentation_for_type("whatsapp")
        credentials = _prompt_credentials_whatsapp()

    elif channel_type == "slack":
        connector = "slack"
        documentation = _documentation_for_type("slack")
        credentials = _prompt_credentials_slack()

    payload = build_channel_payload(
        label=label,
        org=org,
        channel_type=channel_type,
        connector=connector,
        email_address=email_address,
        documentation=documentation,
        credentials=credentials,
    )

    typer.echo(typer.style("\nÉcriture dans config.yaml…", fg=typer.colors.YELLOW))
    checked = setup_channel_from_payload(payload)

    status = checked.get("last_check_status") or checked.get("status") or "unknown"
    reason = checked.get("last_check_reason") or checked.get("reason")

    typer.echo("")
    typer.echo(typer.style(f"Canal créé : {checked.get('id')} ({checked.get('label')})", bold=True))
    if status == "ok":
        typer.echo(typer.style("Check connexion : OK", fg=typer.colors.GREEN))
    elif status == "degraded":
        typer.echo(typer.style(f"Check connexion : à configurer — {reason}", fg=typer.colors.YELLOW))
    else:
        typer.echo(typer.style(f"Check connexion : échec — {reason}", fg=typer.colors.RED))

    typer.echo(typer.style("Lancez `zab channels sync` pour rafraîchir le cockpit.", dim=True))
    return checked
