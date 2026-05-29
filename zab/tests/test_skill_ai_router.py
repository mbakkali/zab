from __future__ import annotations

import json
from pathlib import Path

from zab.services.skill_ai_router import choose_skill_placement


def test_choose_skill_placement_defaults_to_global_without_project() -> None:
    placement = choose_skill_placement("invoice-match", "Retrouver des justificatifs", use_ai=False)

    assert placement.scope == "global"
    assert placement.org == "common"
    assert placement.reason


def test_choose_skill_placement_prefers_project_when_project_path_is_given(tmp_path: Path) -> None:
    project = tmp_path / "flowmetrik-app"
    project.mkdir()

    placement = choose_skill_placement(
        "deploy-helper",
        "Aide propre à ce projet",
        project_path=project,
        use_ai=False,
    )

    assert placement.scope == "project"
    assert placement.project_path == str(project.resolve())


def test_choose_skill_placement_accepts_ai_json_decision(tmp_path: Path) -> None:
    def fake_runner(provider: str, prompt: str, timeout_sec: int) -> str:
        assert provider == "gemini"
        return json.dumps({"scope": "global", "org": "carrefour", "reason": "Réutilisable Carrefour"})

    placement = choose_skill_placement(
        "etat-actuel-dev",
        "Pilotage dev Carrefour",
        project_path=tmp_path,
        use_ai=True,
        providers=["gemini"],
        runner=fake_runner,
    )

    assert placement.scope == "global"
    assert placement.org == "carrefour"
    assert placement.provider == "gemini"
