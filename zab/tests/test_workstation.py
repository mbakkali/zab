from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.services import workstation

TEST_PROJECT = "my-gcp-project"
TEST_INSTANCE = "my-workstation"
TEST_REGION = "europe-west9"
TEST_ZONE = "europe-west9-b"
TEST_CLUSTER = "my-cluster"
TEST_CONFIG = "my-dev-config"
TEST_GCLOUD_CONFIG = "my-gcloud-config"
TEST_FIREWALL = "allow-my-ip"


def _workstation_config_yaml(
    *,
    include_cloud: bool = False,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "project_id": TEST_PROJECT,
        "instance_name": TEST_INSTANCE,
        "region": TEST_REGION,
        "bucket": "gs://my-workstation-sync",
        "firewall_rule": TEST_FIREWALL,
        "gcloud_config": TEST_GCLOUD_CONFIG,
    }
    if include_cloud:
        cfg["workstation_cluster"] = TEST_CLUSTER
        cfg["workstation_config"] = TEST_CONFIG
    return {"workstation": cfg}


def _write_test_config(tmp_path: Path, *, include_cloud: bool = False) -> None:
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(_workstation_config_yaml(include_cloud=include_cloud)),
        encoding="utf-8",
    )


def _instance_payload(status: str = "TERMINATED") -> list[dict[str, Any]]:
    return [
        {
            "name": TEST_INSTANCE,
            "zone": f"https://www.googleapis.com/compute/v1/projects/{TEST_PROJECT}/zones/{TEST_ZONE}",
            "machineType": (
                f"https://www.googleapis.com/compute/v1/projects/{TEST_PROJECT}/zones/"
                f"{TEST_ZONE}/machineTypes/e2-standard-4"
            ),
            "status": status,
            "networkInterfaces": [
                {
                    "networkIP": "10.1.2.3",
                    "accessConfigs": [{"natIP": "34.1.2.3"}],
                }
            ],
            "disks": [{"diskSizeGb": "200"}],
            "labels": {"owner": "tester"},
        }
    ]


def test_workstation_status_parses_instance_list(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_test_config(tmp_path)

    def fake_run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        cmd = " ".join(args)
        if "workstations list" in cmd:
            return 0, "[]", ""
        if "instances list" in cmd:
            return 0, json.dumps(_instance_payload("RUNNING")), ""
        if "firewall-rules describe" in cmd:
            return 0, json.dumps({"sourceRanges": ["82.121.188.168/32"], "targetTags": ["workstation"]}), ""
        if "config configurations list" in cmd:
            return 0, f"{TEST_GCLOUD_CONFIG}\n", ""
        raise AssertionError(args)

    monkeypatch.setattr(workstation, "_run_gcloud", fake_run)
    monkeypatch.setattr(workstation, "_detect_public_ip", lambda: "82.121.188.168")

    out = workstation.get_workstation_status()

    assert out["found"] is True
    assert out["status"] == "RUNNING"
    assert out["zone"] == TEST_ZONE
    assert out["machine_type"] == "e2-standard-4"
    assert out["internal_ip"] == "10.1.2.3"
    assert out["external_ip"] == "34.1.2.3"
    assert out["disk_gb"] == 200
    assert out["firewall"]["source_ranges"] == ["82.121.188.168/32"]
    assert f"gcloud compute ssh {TEST_INSTANCE}" in out["ssh_command"]


def test_workstation_status_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_test_config(tmp_path)

    def fake_run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        cmd = " ".join(args)
        if "workstations list" in cmd:
            return 0, "[]", ""
        if "instances list" in cmd:
            return 0, "[]", ""
        if "firewall-rules describe" in cmd:
            return 1, "", "not found"
        if "config configurations list" in cmd:
            return 0, f"{TEST_GCLOUD_CONFIG}\n", ""
        raise AssertionError(args)

    monkeypatch.setattr(workstation, "_run_gcloud", fake_run)
    monkeypatch.setattr(workstation, "_detect_public_ip", lambda: None)

    out = workstation.get_workstation_status()

    assert out["found"] is False
    assert out["status"] == "not_found"
    assert out["firewall"]["found"] is False


def test_workstation_status_not_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump({}), encoding="utf-8")

    out = workstation.get_workstation_status()

    assert out["found"] is False
    assert out["status"] == "not_configured"
    assert "project_id" in out["error"]


def test_workstation_start_calls_gcloud_with_project_and_zone(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_test_config(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        calls.append(args)
        cmd = " ".join(args)
        if "workstations list" in cmd:
            return 0, "[]", ""
        if "instances list" in cmd:
            return 0, json.dumps(_instance_payload("TERMINATED")), ""
        if "firewall-rules describe" in cmd:
            return 0, json.dumps({"sourceRanges": []}), ""
        if "config configurations list" in cmd:
            return 0, f"{TEST_GCLOUD_CONFIG}\n", ""
        if "instances start" in cmd:
            return 0, "started", ""
        raise AssertionError(args)

    monkeypatch.setattr(workstation, "_run_gcloud", fake_run)
    monkeypatch.setattr(workstation, "_detect_public_ip", lambda: None)

    out = workstation.start_workstation()

    assert out["ok"] is True
    start_call = next(c for c in calls if c[:3] == ["compute", "instances", "start"])
    assert f"--project={TEST_PROJECT}" in start_call
    assert f"--zone={TEST_ZONE}" in start_call
    assert "--quiet" in start_call


def test_cloud_workstation_status_and_start(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_test_config(tmp_path, include_cloud=True)
    calls: list[list[str]] = []
    ws_payload = [
        {
            "name": (
                f"projects/{TEST_PROJECT}/locations/{TEST_REGION}/workstationClusters/"
                f"{TEST_CLUSTER}/workstationConfigs/{TEST_CONFIG}/workstations/{TEST_INSTANCE}"
            ),
            "state": "STATE_RUNNING",
            "host": "my-workstation.example.dev",
            "runtimeHost": {
                "gceInstanceHost": {
                    "name": "workstations-generated",
                    "zone": TEST_ZONE,
                }
            },
        }
    ]

    def fake_run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        calls.append(args)
        cmd = " ".join(args)
        if "workstations list" in cmd:
            return 0, json.dumps(ws_payload), ""
        if "instances list" in cmd:
            return 0, json.dumps(_instance_payload("RUNNING")), ""
        if "firewall-rules describe" in cmd:
            return 0, json.dumps({"sourceRanges": []}), ""
        if "config configurations list" in cmd:
            return 0, f"{TEST_GCLOUD_CONFIG}\n", ""
        if "workstations start" in cmd:
            return 0, "started", ""
        raise AssertionError(args)

    monkeypatch.setattr(workstation, "_run_gcloud", fake_run)
    monkeypatch.setattr(workstation, "_detect_public_ip", lambda: None)

    status = workstation.get_workstation_status()
    assert status["resource_type"] == "cloud_workstation"
    assert status["status"] == "RUNNING"
    assert status["runtime_instance_name"] == "workstations-generated"
    assert f"gcloud workstations ssh {TEST_INSTANCE}" in status["ssh_command"]

    out = workstation.start_workstation()
    assert out["ok"] is True
    start_call = next(c for c in calls if c[:2] == ["workstations", "start"])
    assert f"--project={TEST_PROJECT}" in start_call
    assert f"--cluster={TEST_CLUSTER}" in start_call
    assert f"--config={TEST_CONFIG}" in start_call
    assert f"--region={TEST_REGION}" in start_call


def test_workstation_routes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump({"cli_watchlist": []}), encoding="utf-8")

    monkeypatch.setattr(
        workstation,
        "get_workstation_status",
        lambda: {"found": True, "status": "RUNNING", "name": TEST_INSTANCE},
    )
    monkeypatch.setattr(workstation, "start_workstation", lambda: {"ok": True, "action": "start"})
    monkeypatch.setattr(workstation, "stop_workstation", lambda: {"ok": True, "action": "stop"})
    monkeypatch.setattr(workstation, "ssh_workstation_command", lambda: {"command": "gcloud compute ssh x"})

    client = TestClient(create_app())
    assert client.get("/api/workstation/status").json()["status"] == "RUNNING"
    assert client.post("/api/workstation/start").json()["action"] == "start"
    assert client.post("/api/workstation/stop").json()["action"] == "stop"
    assert client.get("/api/workstation/ssh-command").json()["command"].startswith("gcloud")
