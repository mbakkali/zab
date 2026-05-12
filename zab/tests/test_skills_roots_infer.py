"""inférence skills_roots depuis les SKILL.md du scan."""

from pathlib import Path

from zab.services.skills_roots_infer import infer_skills_repo_roots, roots_from_proposal


def test_infer_finds_org_parent(tmp_path: Path) -> None:
    repo = tmp_path / "monorepo"
    (repo / "orgs").mkdir(parents=True)
    skill_md = repo / "teams" / "ai" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text("---\nname: x\n---\n", encoding="utf-8")
    rel = str(skill_md.relative_to(repo))
    roots = infer_skills_repo_roots(repo, [rel])
    assert roots == [repo.resolve()]


def test_infer_falls_back_to_scan_base_when_no_orgs(tmp_path: Path) -> None:
    base = tmp_path / "workspace"
    skill_md = base / "skills" / "foo" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text("---\nname: y\n---\n", encoding="utf-8")
    rel = str(skill_md.relative_to(base))
    roots = infer_skills_repo_roots(base, [rel])
    assert roots == [base.resolve()]


def test_roots_from_proposal_filters_non_strings() -> None:
    doc = {"roots": [" /tmp/a ", " ", 3, None], "other": 1}
    assert roots_from_proposal(doc) == ["/tmp/a"]
