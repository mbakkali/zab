"""La passerelle LiteLLM est le seul accès de zab aux modèles par API (flowmetrik/flowfactory#238)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from zab.services import llm, skill_ai_router
from zab.services.skill_ai_router import choose_skill_placement

RACINE = Path(__file__).resolve().parents[1]  # le paquet zab/
FOURNISSEURS = re.compile(r"openrouter\.ai|api\.anthropic\.com|api\.openai\.com|generativelanguage")


class _Reponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def appels(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    vus: list[dict[str, Any]] = []

    def faux_post(url: str, **kwargs: Any) -> _Reponse:
        vus.append({"url": url, **kwargs})
        contenu = json.dumps({"scope": "global", "org": "common", "reason": "réutilisable"})
        return _Reponse({"choices": [{"message": {"content": contenu}}]})

    monkeypatch.setattr(llm.httpx, "post", faux_post)
    return vus


def test_adresse_cle_et_modele_viennent_des_variables(monkeypatch: pytest.MonkeyPatch, appels: list) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://passerelle.test/v1/")
    monkeypatch.setenv("LLM_API_KEY", "cle-virtuelle-de-test")
    monkeypatch.setenv("LLM_MODEL", "haiku")

    llm.chat("bonjour")

    assert appels[0]["url"] == "https://passerelle.test/v1/chat/completions"
    assert appels[0]["headers"]["Authorization"] == "Bearer cle-virtuelle-de-test"
    assert appels[0]["json"]["model"] == "haiku"


def test_defauts_passerelle_et_flash(monkeypatch: pytest.MonkeyPatch, appels: list) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "cle-virtuelle-de-test")

    llm.chat("bonjour")

    assert appels[0]["url"] == "https://litellm.tailef30ea.ts.net/v1/chat/completions"
    assert appels[0]["json"]["model"] == "flash"


def test_sans_cle_aucun_appel_et_erreur_explicite(monkeypatch: pytest.MonkeyPatch, appels: list) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "ancienne-cle-qui-ne-doit-pas-servir")

    with pytest.raises(llm.LLMIndisponible, match="LLM_API_KEY"):
        llm.chat("bonjour")
    assert appels == []


def test_le_routeur_de_skills_passe_par_la_passerelle(monkeypatch: pytest.MonkeyPatch, appels: list) -> None:
    monkeypatch.setenv("LLM_API_KEY", "cle-virtuelle-de-test")

    placement = choose_skill_placement("x", "y", use_ai=True, providers=["passerelle"])

    assert placement.provider == "passerelle"
    assert appels[0]["url"].endswith("/chat/completions")
    assert "openrouter" not in appels[0]["url"]


def test_routeur_sans_cle_retombe_sur_l_heuristique(monkeypatch: pytest.MonkeyPatch, appels: list) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    placement = choose_skill_placement("x", "y", use_ai=True, providers=["passerelle"])

    assert placement.provider is None and placement.scope == "global"
    assert appels == []


def test_plus_de_fournisseur_openrouter_dans_le_routeur() -> None:
    assert not hasattr(skill_ai_router, "_run_openrouter")


def test_aucune_adresse_de_fournisseur_dans_le_code() -> None:
    fautifs = [
        f"{p.relative_to(RACINE)}:{n}"
        for p in RACINE.rglob("*")
        if p.suffix in {".py", ".yaml", ".yml", ".toml", ".json"} and p.is_file()
        for n, ligne in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
        if FOURNISSEURS.search(ligne) and p.name != Path(__file__).name
    ]
    assert fautifs == []


def test_un_seul_module_lit_les_variables_de_la_passerelle() -> None:
    lecteurs = sorted(
        str(p.relative_to(RACINE))
        for p in RACINE.rglob("*.py")
        if "tests" not in p.parts and re.search(r"LLM_(BASE_URL|API_KEY|MODEL)", p.read_text(encoding="utf-8"))
    )
    assert lecteurs == ["services/llm.py"]
