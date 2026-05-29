from __future__ import annotations

from pathlib import Path

import pytest

from zab.services.skills_scaffold import SkillScaffoldError, create_global_skill, create_skill, validate_skill_slug


def test_create_skill_writes_agent_skill_under_org(tmp_path: Path) -> None:
    result = create_skill(
        "invoice-match",
        org="flowmetrik",
        description="Retrouver des justificatifs depuis des transactions",
        repo_root=tmp_path,
    )

    skill_path = tmp_path / "orgs" / "flowmetrik" / "skills" / "invoice-match" / "SKILL.md"
    assert result["path"] == str(skill_path.resolve())
    text = skill_path.read_text(encoding="utf-8")
    assert "name: invoice-match" in text
    assert "description: Retrouver des justificatifs depuis des transactions" in text
    assert "# invoice-match" in text
    assert "## When to use" in text


def test_create_skill_without_org_uses_common_org(tmp_path: Path) -> None:
    result = create_skill("research-pack", repo_root=tmp_path)

    assert result["org"] == "common"
    assert result["scope"] == "global"
    assert (tmp_path / "common" / "skills" / "research-pack" / "SKILL.md").is_file()


def test_create_global_skill_is_explicit_alias(tmp_path: Path) -> None:
    result = create_global_skill(
        "shared-review",
        description="Review shared workflows",
        repo_root=tmp_path,
    )

    assert result["scope"] == "global"
    assert result["org"] == "common"
    assert (tmp_path / "common" / "skills" / "shared-review" / "SKILL.md").is_file()


def test_create_skill_rejects_invalid_slug(tmp_path: Path) -> None:
    with pytest.raises(SkillScaffoldError, match="slug invalide"):
        create_skill("../bad", repo_root=tmp_path)

    with pytest.raises(SkillScaffoldError, match="slug invalide"):
        validate_skill_slug("Bad Name")


def test_create_skill_refuses_overwrite_without_force(tmp_path: Path) -> None:
    create_skill("existing", org="acme", repo_root=tmp_path)

    with pytest.raises(SkillScaffoldError, match="existe déjà"):
        create_skill("existing", org="acme", repo_root=tmp_path)

    create_skill("existing", org="acme", repo_root=tmp_path, force=True, description="Nouvelle description")
    text = (tmp_path / "orgs" / "acme" / "skills" / "existing" / "SKILL.md").read_text(encoding="utf-8")
    assert "Nouvelle description" in text
