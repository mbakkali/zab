"""Local GCP workstation management for the zab dashboard.

Configure your workstation in ``~/.config/zab/config.yaml`` under the
``workstation`` key (project_id, instance_name, region, bucket, etc.).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

from zab.user_config import load_user_config

DEFAULT_CONFIG: dict[str, str] = {
    "project_id": "",
    "instance_name": "",
    "region": "",
    "bucket": "",
    "firewall_rule": "",
    "gcloud_config": "default",
    "workstation_cluster": "",
    "workstation_config": "",
}

_CLOUD_STATE_MAP = {
    "STATE_RUNNING": "RUNNING",
    "STATE_STOPPED": "STOPPED",
    "STATE_STARTING": "STARTING",
    "STATE_STOPPING": "STOPPING",
}

SYNC_EXCLUDE = "(^|/)(node_modules|\\.venv|venv|__pycache__|\\.next|dist|build)(/|$)"


def workstation_config() -> dict[str, str]:
    """Merge ``~/.config/zab/config.yaml`` workstation block with defaults."""
    cfg = dict(DEFAULT_CONFIG)
    raw = load_user_config().get("workstation")
    if isinstance(raw, dict):
        for key in DEFAULT_CONFIG:
            val = raw.get(key)
            if val is not None and str(val).strip():
                cfg[key] = str(val).strip()
    return cfg


def _run_gcloud(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    gcloud = shutil.which("gcloud")
    if not gcloud:
        return 127, "", "gcloud not found"
    cfg = workstation_config()
    cmd = [gcloud, "--configuration", cfg["gcloud_config"], *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def _detect_public_ip() -> str | None:
    try:
        with httpx.Client(timeout=5.0) as client:
            for url in (
                "https://api.ipify.org",
                "https://ifconfig.me/ip",
                "https://icanhazip.com",
            ):
                try:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        ip = resp.text.strip()
                        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip):
                            return ip
                except httpx.HTTPError:
                    continue
    except Exception:
        pass
    return None


def _zone_from_url(zone_url: str) -> str | None:
    if not zone_url:
        return None
    return zone_url.rstrip("/").split("/")[-1] or None


def _machine_type_from_url(machine_type_url: str) -> str | None:
    if not machine_type_url:
        return None
    return machine_type_url.rstrip("/").split("/")[-1] or None


def _parse_instance(inst: dict[str, Any]) -> dict[str, Any]:
    nets = inst.get("networkInterfaces") or []
    internal_ip = None
    external_ip = None
    if nets and isinstance(nets[0], dict):
        internal_ip = nets[0].get("networkIP")
        access = nets[0].get("accessConfigs") or []
        if access and isinstance(access[0], dict):
            external_ip = access[0].get("natIP")

    disk_gb = None
    disks = inst.get("disks") or []
    if disks and isinstance(disks[0], dict):
        try:
            disk_gb = int(disks[0].get("diskSizeGb") or 0) or None
        except (TypeError, ValueError):
            disk_gb = None

    return {
        "zone": _zone_from_url(str(inst.get("zone") or "")),
        "machine_type": _machine_type_from_url(str(inst.get("machineType") or "")),
        "status": inst.get("status"),
        "internal_ip": internal_ip,
        "external_ip": external_ip,
        "disk_gb": disk_gb,
        "labels": inst.get("labels") if isinstance(inst.get("labels"), dict) else {},
    }


def _parse_cloud_workstation(ws: dict[str, Any], *, instance_name: str) -> dict[str, Any]:
    name = str(ws.get("name") or "")
    short_name = name.split("/workstations/")[-1] if "/workstations/" in name else instance_name
    raw_state = str(ws.get("state") or "")
    status = _CLOUD_STATE_MAP.get(raw_state, raw_state.removeprefix("STATE_") or raw_state)

    runtime = ws.get("runtimeHost") if isinstance(ws.get("runtimeHost"), dict) else {}
    gce = runtime.get("gceInstanceHost") if isinstance(runtime.get("gceInstanceHost"), dict) else {}

    region = None
    match = re.search(r"/locations/([^/]+)/", name)
    if match:
        region = match.group(1)

    return {
        "name": short_name,
        "status": status,
        "host": ws.get("host"),
        "zone": gce.get("zone"),
        "runtime_instance_name": gce.get("name"),
        "region": region,
        "resource_type": "cloud_workstation",
    }


def _base_status(cfg: dict[str, str]) -> dict[str, Any]:
    return {
        "found": False,
        "project_id": cfg["project_id"],
        "name": cfg["instance_name"],
        "region": cfg["region"],
        "bucket": cfg["bucket"],
        "gcloud_config_expected": cfg["gcloud_config"],
        "gcloud_config_active": None,
        "firewall": {"rule": cfg["firewall_rule"], "found": False},
        "public_ip_detected": _detect_public_ip(),
        "resource_type": "compute_instance",
        "console_url": None,
        "ssh_command": None,
        "error": None,
    }


def _get_firewall_info(cfg: dict[str, str]) -> dict[str, Any]:
    fw: dict[str, Any] = {"rule": cfg["firewall_rule"], "found": False}
    if not cfg["firewall_rule"] or not cfg["project_id"]:
        return fw

    code, out, err = _run_gcloud(
        [
            "compute",
            "firewall-rules",
            "describe",
            cfg["firewall_rule"],
            f"--project={cfg['project_id']}",
            "--format=json",
        ]
    )
    if code != 0:
        fw["error"] = (err or out or "not found").strip()
        return fw

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        fw["error"] = "invalid json from firewall describe"
        return fw

    if isinstance(data, dict):
        fw["found"] = True
        fw["source_ranges"] = data.get("sourceRanges") or []
        fw["target_tags"] = data.get("targetTags") or []
    return fw


def _get_active_gcloud_config() -> str | None:
    code, out, _ = _run_gcloud(["config", "configurations", "list", "--format=value(name)"])
    if code != 0:
        return None
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return lines[0] if lines else None


def gcp_console_url(
    project_id: str,
    zone: str | None,
    name: str,
    resource_type: str,
) -> str | None:
    if not project_id or not name:
        return None
    if resource_type == "cloud_workstation":
        return f"https://console.cloud.google.com/workstations/list?project={project_id}"
    if zone:
        return (
            "https://console.cloud.google.com/compute/instancesDetail/zones/"
            f"{zone}/instances/{name}?project={project_id}"
        )
    return f"https://console.cloud.google.com/compute/instances?project={project_id}"


def _workstations_list_args(cfg: dict[str, str]) -> list[str]:
    args = [
        "workstations",
        "list",
        f"--project={cfg['project_id']}",
        "--format=json",
    ]
    if cfg["region"]:
        args.append(f"--region={cfg['region']}")
    if cfg["workstation_cluster"]:
        args.append(f"--cluster={cfg['workstation_cluster']}")
    if cfg["workstation_config"]:
        args.append(f"--config={cfg['workstation_config']}")
    return args


def _match_cloud_workstation(items: list[dict[str, Any]], instance_name: str) -> dict[str, Any] | None:
    for item in items:
        name = str(item.get("name") or "")
        if name.endswith(f"/workstations/{instance_name}"):
            return item
    return items[0] if items else None


def _instances_list_args(cfg: dict[str, str]) -> list[str]:
    return [
        "compute",
        "instances",
        "list",
        f"--project={cfg['project_id']}",
        f"--filter=name={cfg['instance_name']}",
        "--format=json",
    ]


def _enrich_from_compute_instance(out: dict[str, Any], cfg: dict[str, str]) -> None:
    code, raw, _ = _run_gcloud(_instances_list_args(cfg))
    if code != 0:
        return
    try:
        instances = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(instances, list) or not instances:
        return
    parsed = _parse_instance(instances[0])
    for key in ("zone", "machine_type", "internal_ip", "external_ip", "disk_gb", "labels"):
        if parsed.get(key) is not None:
            out[key] = parsed[key]


def _build_ssh_command(cfg: dict[str, str], status: dict[str, Any]) -> str | None:
    if status.get("resource_type") == "cloud_workstation":
        if not all(
            [
                cfg["project_id"],
                cfg["region"],
                cfg["workstation_cluster"],
                cfg["workstation_config"],
                cfg["instance_name"],
            ]
        ):
            return None
        return (
            f"gcloud workstations ssh {cfg['instance_name']} "
            f"--project={cfg['project_id']} "
            f"--cluster={cfg['workstation_cluster']} "
            f"--config={cfg['workstation_config']} "
            f"--region={cfg['region']}"
        )

    zone = status.get("zone")
    if cfg["project_id"] and cfg["instance_name"] and zone:
        return (
            f"gcloud compute ssh {cfg['instance_name']} "
            f"--project={cfg['project_id']} "
            f"--zone={zone}"
        )
    return None


def get_workstation_status() -> dict[str, Any]:
    cfg = workstation_config()
    out = _base_status(cfg)

    if not cfg["project_id"] or not cfg["instance_name"]:
        out["status"] = "not_configured"
        out["error"] = (
            "Configure workstation.project_id and workstation.instance_name "
            "in ~/.config/zab/config.yaml"
        )
        return out

    out["gcloud_config_active"] = _get_active_gcloud_config()
    out["firewall"] = _get_firewall_info(cfg)

    code, raw, err = _run_gcloud(_workstations_list_args(cfg))
    if code == 0:
        try:
            workstations = json.loads(raw)
        except json.JSONDecodeError:
            workstations = None
        if isinstance(workstations, list) and workstations:
            ws_item = _match_cloud_workstation(
                [w for w in workstations if isinstance(w, dict)],
                cfg["instance_name"],
            )
            if ws_item is not None:
                out.update(_parse_cloud_workstation(ws_item, instance_name=cfg["instance_name"]))
                out["found"] = True
                _enrich_from_compute_instance(out, cfg)
                out["ssh_command"] = _build_ssh_command(cfg, out)
                out["console_url"] = gcp_console_url(
                    cfg["project_id"],
                    out.get("zone"),
                    cfg["instance_name"],
                    "cloud_workstation",
                )
                return out

    code, raw, err = _run_gcloud(_instances_list_args(cfg))
    if code != 0:
        out["status"] = "error"
        out["error"] = (err or raw or "gcloud instances list failed").strip()
        return out

    try:
        instances = json.loads(raw)
    except json.JSONDecodeError:
        out["status"] = "error"
        out["error"] = "invalid json from instances list"
        return out

    if not isinstance(instances, list) or not instances:
        out["status"] = "not_found"
        return out

    parsed = _parse_instance(instances[0])
    out.update(parsed)
    out["found"] = True
    out["status"] = parsed.get("status") or "UNKNOWN"
    out["resource_type"] = "compute_instance"
    out["ssh_command"] = _build_ssh_command(cfg, out)
    out["console_url"] = gcp_console_url(
        cfg["project_id"],
        out.get("zone"),
        cfg["instance_name"],
        "compute_instance",
    )
    return out


def start_workstation() -> dict[str, Any]:
    cfg = workstation_config()
    if not cfg["project_id"] or not cfg["instance_name"]:
        return {"ok": False, "action": "start", "error": "workstation not configured"}

    status = get_workstation_status()
    if not status.get("found"):
        return {
            "ok": False,
            "action": "start",
            "error": status.get("error") or "workstation not found",
            "status": status,
        }

    if status.get("resource_type") == "cloud_workstation":
        code, output, err = _run_gcloud(
            [
                "workstations",
                "start",
                cfg["instance_name"],
                f"--project={cfg['project_id']}",
                f"--cluster={cfg['workstation_cluster']}",
                f"--config={cfg['workstation_config']}",
                f"--region={cfg['region']}",
                "--quiet",
            ],
            timeout=120,
        )
        return {
            "ok": code == 0,
            "action": "start",
            "exit_code": code,
            "output": output,
            "error": err.strip() or None,
        }

    zone = status.get("zone")
    if not zone:
        return {"ok": False, "action": "start", "error": "zone unknown", "status": status}

    code, output, err = _run_gcloud(
        [
            "compute",
            "instances",
            "start",
            cfg["instance_name"],
            f"--project={cfg['project_id']}",
            f"--zone={zone}",
            "--quiet",
        ],
        timeout=120,
    )
    return {
        "ok": code == 0,
        "action": "start",
        "exit_code": code,
        "output": output,
        "error": err.strip() or None,
    }


def stop_workstation() -> dict[str, Any]:
    cfg = workstation_config()
    if not cfg["project_id"] or not cfg["instance_name"]:
        return {"ok": False, "action": "stop", "error": "workstation not configured"}

    status = get_workstation_status()
    if not status.get("found"):
        return {
            "ok": False,
            "action": "stop",
            "error": status.get("error") or "workstation not found",
            "status": status,
        }

    if status.get("resource_type") == "cloud_workstation":
        code, output, err = _run_gcloud(
            [
                "workstations",
                "stop",
                cfg["instance_name"],
                f"--project={cfg['project_id']}",
                f"--cluster={cfg['workstation_cluster']}",
                f"--config={cfg['workstation_config']}",
                f"--region={cfg['region']}",
                "--quiet",
            ],
            timeout=120,
        )
        return {
            "ok": code == 0,
            "action": "stop",
            "exit_code": code,
            "output": output,
            "error": err.strip() or None,
        }

    zone = status.get("zone")
    if not zone:
        return {"ok": False, "action": "stop", "error": "zone unknown", "status": status}

    code, output, err = _run_gcloud(
        [
            "compute",
            "instances",
            "stop",
            cfg["instance_name"],
            f"--project={cfg['project_id']}",
            f"--zone={zone}",
            "--quiet",
        ],
        timeout=120,
    )
    return {
        "ok": code == 0,
        "action": "stop",
        "exit_code": code,
        "output": output,
        "error": err.strip() or None,
    }


def ssh_workstation_command() -> dict[str, Any]:
    status = get_workstation_status()
    command = status.get("ssh_command")
    if not command:
        return {
            "command": None,
            "error": status.get("error") or "ssh command unavailable",
            "status": status,
        }
    return {"command": command}


def sync_workstation(*, dry_run: bool = False) -> dict[str, Any]:
    cfg = workstation_config()
    bucket = cfg.get("bucket") or ""
    if not bucket:
        return {"ok": False, "action": "sync", "error": "workstation.bucket not configured"}

    projects_dir = Path.home() / "projects"
    if not projects_dir.is_dir():
        return {
            "ok": False,
            "action": "sync",
            "error": f"projects directory not found: {projects_dir}",
        }

    gcloud = shutil.which("gcloud")
    if not gcloud:
        return {"ok": False, "action": "sync", "error": "gcloud not found"}

    dest = f"{bucket.rstrip('/')}/projects"
    cmd = [
        gcloud,
        "storage",
        "rsync",
        str(projects_dir),
        dest,
        "--recursive",
        "--ignore-symlinks",
        f"--exclude={SYNC_EXCLUDE}",
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "action": "sync", "error": "timeout"}

    output = (proc.stdout or "") + (proc.stderr or "")
    result: dict[str, Any] = {
        "ok": proc.returncode == 0,
        "action": "sync",
        "dry_run": dry_run,
        "exit_code": proc.returncode,
        "output": output,
    }
    if dry_run:
        files_affected: list[str] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("WARNING"):
                continue
            parts = stripped.split(None, 1)
            files_affected.append(parts[1] if len(parts) == 2 else stripped)
        result["files_affected"] = files_affected
    return result
