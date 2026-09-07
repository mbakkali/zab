"""Code retour de `zab channels sync` — ce que la routine `ledger` relit.

Le cache a toujours dit la vérité (`status: "error"`) ; la commande sortait
quand même en 0. Trois semaines de WhatsApp déconnecté sont passées par ce trou,
avec 47 passages de la routine tous marqués `ok`. Ces tests tiennent la
frontière : `error` alerte, `degraded` et `disabled` ne réveillent personne.
"""

from __future__ import annotations

from typer.testing import CliRunner

from zab.cli import app

runner = CliRunner()


def _payload(*channels: dict) -> dict:
    return {
        "generated_at_utc": "2026-09-07T10:00:00+00:00",
        "channels": list(channels),
        "action_items": [],
        "total_actions_count": 0,
    }


def _patch_sync(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(
        "zab.services.communication_channels.sync_communication_channels",
        lambda: payload,
    )


def test_sync_sort_en_zero_quand_tout_va_bien(monkeypatch) -> None:
    _patch_sync(monkeypatch, _payload({"id": "alegria-email", "type": "email", "status": "ok", "sync_summary": {"unread_count": 3}}))
    result = runner.invoke(app, ["channels", "sync"])
    assert result.exit_code == 0


def test_sync_echoue_sur_un_canal_en_erreur_et_le_nomme(monkeypatch) -> None:
    _patch_sync(
        monkeypatch,
        _payload(
            {"id": "alegria-email", "type": "email", "status": "ok", "sync_summary": {"unread_count": 0}},
            {
                "id": "whatsapp-evo",
                "label": "WhatsApp (Evolution API)",
                "type": "whatsapp",
                "status": "error",
                "reason": "evolution_http_error: timed out",
            },
        ),
    )
    result = runner.invoke(app, ["channels", "sync"])
    assert result.exit_code == 1
    # Nommer le canal et la raison : sans ça, le journal dit « rc=1 » et il faut
    # rouvrir le cache pour savoir lequel des sept canaux est tombé.
    assert "whatsapp-evo" in result.stdout
    assert "timed out" in result.stdout
    # `step()` ne consigne que les deux dernières lignes : le récapitulatif qui
    # nomme les canaux doit être la dernière, sinon il n'atteint pas le journal.
    derniere = [l for l in result.stdout.splitlines() if l.strip()][-1]
    assert "whatsapp-evo" in derniere


def test_sync_ne_echoue_pas_sur_degraded_ni_disabled(monkeypatch) -> None:
    # Trois canaux sur sept sont durablement dégradés (Slack sans fetcher, gog
    # sans OAuth). Les compter comme des échecs rendrait la routine rouge à
    # chaque passage — le même silence, par un autre chemin.
    _patch_sync(
        monkeypatch,
        _payload(
            {"id": "slack-carrefour", "type": "slack", "status": "degraded", "reason": "no_fetcher_for_type:slack"},
            {"id": "perso-email", "type": "email", "status": "degraded", "reason": "gog: gog_oauth_missing"},
            {"id": "vieux-canal", "type": "email", "status": "disabled", "reason": "channel_disabled"},
        ),
    )
    result = runner.invoke(app, ["channels", "sync"])
    assert result.exit_code == 0
    assert "dégradé" in result.stdout
