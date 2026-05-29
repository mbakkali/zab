import json

import yaml

from zab.services.system_check_persist import (
    load_last_system_check,
    persist_system_check_report,
    system_check_last_path,
)
from zab.user_config import load_user_config, user_config_path


def test_persist_system_check_report(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    report = {
        "generated_at_utc": "2026-05-28T18:00:00+00:00",
        "percentage": 79,
        "score": 9.5,
        "total": 12,
        "ok": 5,
        "warn": 5,
        "fail": 2,
        "checks": [
            {
                "id": "config_yaml",
                "label": "Configuration zab",
                "category": "core",
                "status": "ok",
                "message": "ok",
                "detail": {},
            }
        ],
    }

    path = persist_system_check_report(report)
    assert path.is_file()
    assert path == system_check_last_path()

    loaded = load_last_system_check()
    assert loaded is not None
    assert loaded["report"]["percentage"] == 79
    assert len(loaded["report"]["checks"]) == 1

    cfg = load_user_config()
    assert cfg["last_system_check_at_utc"] == "2026-05-28T18:00:00+00:00"
    meta = cfg["system_check_last"]
    assert meta["saved_at_utc"]
    assert meta["report_path"] == str(path.resolve())
    assert meta["percentage"] == 79
    assert meta["report"]["total"] == 12

    raw_json = json.loads(path.read_text(encoding="utf-8"))
    assert raw_json["report"]["ok"] == 5

    cfg_path = user_config_path()
    assert cfg_path.is_file()
    disk_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert disk_cfg["system_check_last"]["fail"] == 2
