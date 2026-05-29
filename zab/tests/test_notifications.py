from __future__ import annotations

from zab.services import notifications


def test_notify_skills_disabled_skips() -> None:
    out = notifications.notify_skills_auto_sync(slugs=["a", "b"], notify=False, channel="evolution")
    assert out.get("skipped") is True
    assert out.get("reason") == "notify_disabled"


def test_notify_skills_evolution_skips_without_env(monkeypatch) -> None:
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)
    out = notifications.notify_skills_auto_sync(slugs=["x"], notify=True, channel="evolution")
    assert out.get("skipped") is True
    assert out.get("reason") == "evolution_env_incomplete"
