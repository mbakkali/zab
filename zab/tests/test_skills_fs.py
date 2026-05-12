import pytest

from zab.services import skills_fs


def test_reject_path_traversal():
    with pytest.raises(skills_fs.SkillPathError):
        skills_fs.read_skill("orgs/../pyproject.toml")


def test_reject_wrong_prefix():
    with pytest.raises(skills_fs.SkillPathError):
        skills_fs.read_skill("mcps/foo/SKILL.md")


def test_reject_non_skill_name():
    with pytest.raises(skills_fs.SkillPathError):
        skills_fs.read_skill("orgs/flowmetrik/skills/foo/README.md")
