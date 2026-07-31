from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.services import remote_vm

TEST_PROJECT = "my-gcp-project"
TEST_ZONE = "europe-west9-b"
TEST_INSTANCE = "my-dev-vm"
TEST_ALIAS = "my-dev-vm-iap"
TEST_TABLE = "my-gcp-project.my_billing_export.gcp_billing_export_resource_v1_AAAAAA"


def _write_config(tmp_path: Path, extra: dict[str, Any] | None = None) -> None:
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    block: dict[str, Any] = {
        "project": TEST_PROJECT,
        "zone": TEST_ZONE,
        "instance": TEST_INSTANCE,
        "ssh_alias": TEST_ALIAS,
        "billing": {"table": TEST_TABLE, "currency": "EUR"},
    }
    if extra:
        block.update(extra)
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump({"remote_vm": block}), encoding="utf-8")


def _write_deploy_config(tmp_path: Path) -> Path:
    deploy = tmp_path / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    path = deploy / "config.json"
    path.write_text(
        json.dumps(
            {
                "gcp": {
                    "project": TEST_PROJECT,
                    "zone": TEST_ZONE,
                    "instance": TEST_INSTANCE,
                    "machine_type": "e2-standard-4",
                    "data_disk": "my-dev-data",
                    "base_image": "my-dev-base-v2",
                },
                "lifecycle": {"auto_stop_idle_minutes": 60},
                "sync": {"engine": "mutagen"},
            }
        ),
        encoding="utf-8",
    )
    (deploy / "vmctl.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return path


def _instance_payload(status: str = "RUNNING") -> dict[str, Any]:
    return {
        "name": TEST_INSTANCE,
        "status": status,
        "machineType": (
            f"https://www.googleapis.com/compute/v1/projects/{TEST_PROJECT}/zones/"
            f"{TEST_ZONE}/machineTypes/e2-standard-4"
        ),
        "disks": [
            {"deviceName": "persistent-disk-0", "diskSizeGb": "40", "boot": True, "type": "PERSISTENT"},
            {"deviceName": "data", "diskSizeGb": "150", "boot": False, "type": "PERSISTENT"},
        ],
        "networkInterfaces": [{"networkIP": "10.61.0.2"}],
        "lastStartTimestamp": "2026-07-30T10:00:00.000-00:00",
        "lastStopTimestamp": "2026-07-29T20:00:00.000-00:00",
        "labels": {"owner": "tester"},
    }


def test_config_merges_deploy_descriptor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    deploy = _write_deploy_config(tmp_path)
    _write_config(tmp_path, {"deploy_config": str(deploy), "project": "", "zone": "", "instance": ""})

    cfg = remote_vm.config()

    assert cfg["project"] == TEST_PROJECT
    assert cfg["zone"] == TEST_ZONE
    assert cfg["instance"] == TEST_INSTANCE
    assert cfg["machine_type"] == "e2-standard-4"
    assert cfg["auto_stop_idle_minutes"] == 60
    assert cfg["vmctl"].endswith("vmctl.sh")
    # Les images sont versionnées : le motif retombe sur la famille.
    assert "%my-dev-base%" in cfg["billing"]["resource_match"]
    assert "%my-dev-data%" in cfg["billing"]["resource_match"]


def test_config_user_keys_override_deploy_descriptor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    deploy = _write_deploy_config(tmp_path)
    _write_config(tmp_path, {"deploy_config": str(deploy), "instance": "override-vm"})

    cfg = remote_vm.config()

    assert cfg["instance"] == "override-vm"
    assert cfg["zone"] == TEST_ZONE


def test_vm_state_reports_running_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)

    def fake_gcloud(cfg: dict[str, Any], args: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
        cmd = " ".join(args)
        if "instances describe" in cmd:
            return 0, json.dumps(_instance_payload("RUNNING")), ""
        if "machine-types describe" in cmd:
            return 0, json.dumps({"guestCpus": 4, "memoryMb": 16384}), ""
        raise AssertionError(args)

    monkeypatch.setattr(remote_vm, "_gcloud", fake_gcloud)

    out = remote_vm.vm_state()

    assert out["found"] is True
    assert out["status"] == "RUNNING"
    assert out["vcpus"] == 4
    assert out["memory_gb"] == 16.0
    assert out["disk_total_gb"] == 190
    assert out["session_seconds"] > 0
    # La VM tourne : la dernière session close n'est pas recalculée à l'envers.
    assert out["last_session_seconds"] is None


def test_vm_state_not_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".config" / "zab").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".config" / "zab" / "config.yaml").write_text(yaml.safe_dump({}), encoding="utf-8")

    out = remote_vm.vm_state()

    assert out["configured"] is False
    assert "remote_vm.project" in out["error"]


def test_cost_sql_rejects_unsafe_inputs() -> None:
    with pytest.raises(ValueError):
        remote_vm._cost_sql("not-a-table", ["%vm%"], 30)
    with pytest.raises(ValueError):
        remote_vm._cost_sql(TEST_TABLE, ["'; DROP TABLE x; --"], 30)
    sql = remote_vm._cost_sql(TEST_TABLE, ["%my-dev-vm%"], 30)
    assert TEST_TABLE in sql
    assert "INTERVAL 30 DAY" in sql


def test_cost_report_derives_hours_and_categories(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, {"machine_type": "e2-standard-4"})

    # Le cache des types de machines fournit le nombre de vCPU sans appeler gcloud.
    cache = tmp_path / ".local" / "share" / "zab" / "remote-vm"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "machine-types.json").write_text(
        json.dumps({"e2-standard-4": {"vcpus": 4, "memory_gb": 16.0}}), encoding="utf-8"
    )

    rows = [
        {"day": "2026-07-01", "sku": "E2 Instance Core running in EMEA", "cost": 0.5, "credits": 0.0, "units": 24.0, "unit": "hour", "currency": "EUR"},
        {"day": "2026-07-01", "sku": "E2 Instance Ram running in EMEA", "cost": 0.3, "credits": -0.1, "units": 96.0, "unit": "gibibyte hour", "currency": "EUR"},
        {"day": "2026-07-01", "sku": "Balanced PD Capacity", "cost": 0.2, "credits": 0.0, "units": 1.0, "unit": "gibibyte month", "currency": "EUR"},
        {"day": "2026-07-01", "sku": "Network Internet Data Transfer Out from EMEA to EMEA", "cost": 0.05, "credits": 0.0, "units": 0.1, "unit": "gibibyte", "currency": "EUR"},
    ]
    monkeypatch.setattr(remote_vm, "_run_billing_query", lambda cfg, days: rows)

    report = remote_vm.cost_report(days=30, refresh=True)

    day = report["days"][0]
    assert day["hours"] == pytest.approx(6.0)  # 24 core-heures / 4 vCPU
    assert day["compute"] == pytest.approx(0.8)
    assert day["storage"] == pytest.approx(0.2)
    assert day["network"] == pytest.approx(0.05)
    assert day["net_cost"] == pytest.approx(0.95)
    assert report["totals"]["window_hours"] == pytest.approx(6.0)
    assert report["totals"]["hourly_rate"] == pytest.approx(0.1333, abs=1e-3)
    assert report["by_sku"][0]["sku"] == "E2 Instance Core running in EMEA"


def test_cost_report_uses_cache_then_refresh(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)

    calls: list[int] = []

    def fake_query(cfg: dict[str, Any], days: int) -> list[dict[str, Any]]:
        calls.append(days)
        return []

    monkeypatch.setattr(remote_vm, "_run_billing_query", fake_query)

    remote_vm.cost_report(days=30, refresh=True)
    cached = remote_vm.cost_report(days=30)

    assert calls == [30]
    assert cached["cached"] is True


def test_cost_report_falls_back_to_stale_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)

    monkeypatch.setattr(remote_vm, "_run_billing_query", lambda cfg, days: [])
    remote_vm.cost_report(days=30, refresh=True)

    def boom(cfg: dict[str, Any], days: int) -> list[dict[str, Any]]:
        raise RuntimeError("BigQuery indisponible")

    monkeypatch.setattr(remote_vm, "_run_billing_query", boom)
    out = remote_vm.cost_report(days=30, refresh=True)

    assert out["stale"] is True
    assert "BigQuery indisponible" in out["error"]


def test_cost_report_requires_billing_table(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"remote_vm": {"project": TEST_PROJECT, "zone": TEST_ZONE, "instance": TEST_INSTANCE}}),
        encoding="utf-8",
    )

    out = remote_vm.cost_report()

    assert out["configured"] is False
    assert "billing.table" in out["error"]


def test_elapsed_to_seconds_handles_ps_formats() -> None:
    assert remote_vm._elapsed_to_seconds("12:34") == 754
    assert remote_vm._elapsed_to_seconds("01:02:03") == 3723
    assert remote_vm._elapsed_to_seconds("2-03:04:05") == 2 * 86400 + 11045
    assert remote_vm._elapsed_to_seconds("bogus") is None


def test_ssh_state_classifies_local_processes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)

    ps_output = "\n".join(
        [
            f"  101 01:02:03 /usr/bin/ssh -MNf {TEST_ALIAS}",
            f"  102 00:10:00 /usr/bin/ssh {TEST_ALIAS} mutagen-agent synchronizer",
            f"  103 00:05:00 gcloud compute start-iap-tunnel {TEST_INSTANCE} 22 --listen-on-stdin",
            "  104 10:00:00 /opt/homebrew/bin/mutagen daemon run",
            "  105 00:01:00 /usr/bin/ssh some-other-host",
        ]
    )

    monkeypatch.setattr(remote_vm, "resolve_bin", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd: list[str], *, timeout: int = 30, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        if cmd[0].endswith("ssh"):
            return 0, "Master running (pid=101)", ""
        if cmd[0] == "ps":
            return 0, ps_output, ""
        raise AssertionError(cmd)

    monkeypatch.setattr(remote_vm, "_run", fake_run)

    out = remote_vm.ssh_state()

    assert out["control_master"]["state"] == "up"
    kinds = sorted(c["kind"] for c in out["connections"])
    assert kinds == ["control-master", "sync-agent", "tunnel"]
    assert out["tunnels"] == 1
    assert out["sync_agents"] == 1
    assert out["mutagen_daemon"] is True
    assert out["active"] is True


def _mutagen_session(name: str, *, status: str, alpha_files: int, beta_files: int, conflicts: int = 0) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "paused": False,
        "mode": "two-way-safe",
        "successfulCycles": 3,
        "conflicts": [{"root": "x"}] * conflicts,
        "alpha": {"protocol": "local", "path": f"/local/{name}", "connected": True, "scanned": True, "files": alpha_files, "directories": 5, "totalFileSize": 1024},
        "beta": {
            "protocol": "ssh",
            "host": TEST_ALIAS,
            "path": f"/remote/{name}",
            "connected": True,
            "scanned": True,
            "files": beta_files,
            "directories": 5,
            "totalFileSize": 512,
            "stagingProgress": {"path": "a/b", "receivedFiles": 2, "totalFiles": 10},
        },
    }


def test_sync_state_filters_and_aggregates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)

    sessions = [
        _mutagen_session("one", status="watching", alpha_files=100, beta_files=100),
        _mutagen_session("two", status="staging-beta", alpha_files=80, beta_files=75, conflicts=2),
        # Session sans rapport avec la VM : elle doit être ignorée.
        {"name": "other", "status": "watching", "alpha": {"connected": True}, "beta": {"host": "unrelated-host", "connected": True}},
    ]

    monkeypatch.setattr(remote_vm, "resolve_bin", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        remote_vm,
        "_run",
        lambda cmd, *, timeout=30, env=None: (0, json.dumps(sessions), ""),
    )

    out = remote_vm.sync_state()

    assert [s["name"] for s in out["sessions"]] == ["one", "two"]
    totals = out["totals"]
    assert totals["sessions"] == 2
    assert totals["connected"] == 2
    assert totals["watching"] == 1
    assert totals["alpha_files"] == 180
    assert totals["beta_files"] == 175
    assert totals["file_delta"] == 5
    assert totals["conflicts"] == 2
    assert totals["staging_total"] == 20
    assert totals["staging_received"] == 4


def test_sync_state_reports_missing_binary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)
    monkeypatch.setattr(remote_vm, "resolve_bin", lambda name: None)

    out = remote_vm.sync_state()

    assert out["sessions"] == []
    assert "mutagen" in out["error"]


def test_sync_action_rejects_unknown_action(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)

    out = remote_vm.sync_action("rm-rf")

    assert out["ok"] is False
    assert "non autorisée" in out["error"]


def test_api_overview_and_cost(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)

    monkeypatch.setattr(remote_vm, "vm_state", lambda: {"configured": True, "found": True, "status": "RUNNING"})
    monkeypatch.setattr(remote_vm, "ssh_state", lambda: {"configured": True, "connections": []})
    monkeypatch.setattr(remote_vm, "sync_state", lambda: {"configured": True, "sessions": []})
    monkeypatch.setattr(remote_vm, "_run_billing_query", lambda cfg, days: [])

    client = TestClient(create_app())

    overview = client.get("/api/remote-vm/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["configured"] is True
    assert body["config"]["instance"] == TEST_INSTANCE
    assert body["config"]["billing_configured"] is True

    cost = client.get("/api/remote-vm/cost?days=7&refresh=true")
    assert cost.status_code == 200
    assert cost.json()["window_days"] == 7
