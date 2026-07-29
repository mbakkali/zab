from __future__ import annotations

from zab.services import conversation_sync


def test_conversation_sync_skips_overlapping_run(monkeypatch, tmp_path):
    monkeypatch.setattr(conversation_sync, "data_dir", lambda: tmp_path)

    with conversation_sync._conversation_sync_lock() as (acquired, owner):
        assert acquired is True
        assert owner["pid"] > 0

        result = conversation_sync.run_sync(
            dry_run=True,
            append=False,
            with_mempalace=False,
            workspace_storage_cursor=False,
            providers=["codex"],
            batch_id="test-overlap",
        )

    assert result["status"] == "skipped"
    assert result["reason"] == "conversation_sync_already_running"
    assert result["lock_owner"]["pid"] == owner["pid"]
