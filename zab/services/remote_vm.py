"""Monitoring d'une VM de dev distante : coût, heures, connexions SSH et sync.

Le module est générique : aucune ressource cloud n'est codée en dur. Tout vient
de ``~/.config/zab/config.yaml`` sous la clé ``remote_vm`` :

```yaml
remote_vm:
  project: my-gcp-project
  zone: europe-west1-b
  instance: my-dev-vm
  gcloud_config: my-gcloud-configuration   # configuration gcloud pour les lectures Compute
  ssh_alias: my-dev-vm-iap                 # alias ~/.ssh/config utilisé par la sync
  control_path: ~/.ssh/control-%C          # ControlPath ssh (optionnel, informatif)
  vmctl: ~/path/to/vmctl.sh                # script start/stop qui gère aussi la sync
  deploy_config: ~/path/to/config.json     # optionnel : pré-remplit les champs ci-dessus
  auto_stop_idle_minutes: 60
  sync:
    engine: mutagen
  billing:
    gcloud_config: my-billing-configuration
    project: my-billing-query-project
    table: project.dataset.gcp_billing_export_resource_v1_XXXXXX
    currency: EUR
    resource_match: ["%my-dev-vm%"]        # optionnel, sinon dérivé du nom d'instance
```

``deploy_config`` accepte un descripteur JSON de déploiement (clés ``gcp.project``,
``gcp.zone``, ``gcp.instance``, ``gcp.machine_type``, ``gcp.data_disk``,
``gcp.base_image``, ``lifecycle.auto_stop_idle_minutes``) : pratique pour ne pas
dupliquer une configuration d'infrastructure déjà versionnée ailleurs.

Sources de vérité :
- état instantané et heures de la session courante : ``gcloud compute instances describe`` ;
- heures et coûts historiques : export BigQuery de facturation (niveau ressource) ;
- connexions SSH : multiplexage OpenSSH local + processus tunnel ;
- sync : sessions Mutagen dont le beta pointe vers la VM.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from zab.paths import data_dir
from zab.user_config import load_user_config

DEFAULT_CONFIG: dict[str, Any] = {
    "project": "",
    "zone": "",
    "instance": "",
    "gcloud_config": "",
    "ssh_alias": "",
    "control_path": "",
    "vmctl": "",
    "deploy_config": "",
    "auto_stop_idle_minutes": 0,
    "machine_type": "",
    "data_disk": "",
    "base_image": "",
    "sync_engine": "mutagen",
    "billing": {
        "gcloud_config": "",
        "project": "",
        "table": "",
        "currency": "EUR",
        "resource_match": [],
    },
}

COST_CACHE_TTL_SECONDS = 1800
_STATE_DIR = "remote-vm"

_SAFE_TABLE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
_SAFE_MATCH = re.compile(r"^[A-Za-z0-9_%\-.]+$")

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("compute", ("instance core", "instance ram", "instance uptime", "commitment", "licensing", "gpu")),
    ("storage", ("pd capacity", "pd snapshot", "storage image", "storage pd", "ssd backed", "snapshot")),
    ("network", ("network", "ip charge", "ip address", "load balanc", "egress")),
)


# ── configuration ────────────────────────────────────────────────────────────


def _deep_get(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _from_deploy_config(path_value: str) -> dict[str, Any]:
    """Lit un descripteur de déploiement JSON et en extrait les champs utiles."""
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    if path.is_dir():
        path = path / "config.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mapping = {
        "project": "gcp.project",
        "zone": "gcp.zone",
        "instance": "gcp.instance",
        "machine_type": "gcp.machine_type",
        "data_disk": "gcp.data_disk",
        "base_image": "gcp.base_image",
        "auto_stop_idle_minutes": "lifecycle.auto_stop_idle_minutes",
        "sync_engine": "sync.engine",
    }
    out: dict[str, Any] = {}
    for key, dotted in mapping.items():
        value = _deep_get(raw, dotted)
        if value not in (None, ""):
            out[key] = value
    vmctl = path.parent / "vmctl.sh"
    if vmctl.is_file():
        out["vmctl"] = str(vmctl)
    return out


def config() -> dict[str, Any]:
    """Configuration effective, fusion défauts + descripteur de déploiement + config utilisateur."""
    cfg: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))
    raw = load_user_config().get("remote_vm")
    raw = raw if isinstance(raw, dict) else {}

    deploy_path = str(raw.get("deploy_config") or os.environ.get("ZAB_REMOTE_VM_DEPLOY_CONFIG") or "").strip()
    if deploy_path:
        cfg["deploy_config"] = deploy_path
        cfg.update(_from_deploy_config(deploy_path))

    for key, value in raw.items():
        if key == "billing":
            continue
        if value in (None, ""):
            continue
        cfg[key] = value

    billing = raw.get("billing") if isinstance(raw.get("billing"), dict) else {}
    for key, value in billing.items():
        if value in (None, ""):
            continue
        cfg["billing"][key] = value

    _apply_env_overrides(cfg)

    if not cfg["billing"]["project"] and cfg["project"]:
        cfg["billing"]["project"] = cfg["project"]
    if not cfg["billing"]["gcloud_config"]:
        cfg["billing"]["gcloud_config"] = cfg["gcloud_config"]
    if not cfg["billing"]["resource_match"]:
        cfg["billing"]["resource_match"] = _default_resource_match(cfg)
    return cfg


ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "ZAB_REMOTE_VM_PROJECT": ("project",),
    "ZAB_REMOTE_VM_ZONE": ("zone",),
    "ZAB_REMOTE_VM_INSTANCE": ("instance",),
    "ZAB_REMOTE_VM_MACHINE_TYPE": ("machine_type",),
    "ZAB_REMOTE_VM_SSH_ALIAS": ("ssh_alias",),
    "ZAB_REMOTE_VM_BILLING_TABLE": ("billing", "table"),
    "ZAB_REMOTE_VM_BILLING_PROJECT": ("billing", "project"),
    "ZAB_REMOTE_VM_CURRENCY": ("billing", "currency"),
}


def _apply_env_overrides(cfg: dict[str, Any]) -> None:
    """Configuration par l'environnement, indispensable en conteneur (pas de config.yaml)."""
    for env_name, path in ENV_OVERRIDES.items():
        value = os.environ.get(env_name, "").strip()
        if not value:
            continue
        target = cfg
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
    matches = os.environ.get("ZAB_REMOTE_VM_RESOURCE_MATCH", "").strip()
    if matches:
        cfg["billing"]["resource_match"] = [m.strip() for m in matches.split(",") if m.strip()]


def _default_resource_match(cfg: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("instance", "data_disk"):
        name = str(cfg.get(key) or "").strip()
        if name:
            out.append(f"%{name}%")
    image = str(cfg.get("base_image") or "").strip()
    if image:
        # Les images sont versionnées (`-v1`, `-v2`) : on matche la famille.
        out.append(f"%{re.sub(r'-v[0-9]+$', '', image)}%")
    return sorted(set(out))


def is_configured(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or config()
    return bool(cfg["project"] and cfg["zone"] and cfg["instance"])


def _not_configured(section: str) -> dict[str, Any]:
    return {
        "configured": False,
        "section": section,
        "error": (
            "Configure remote_vm.project / remote_vm.zone / remote_vm.instance "
            "dans ~/.config/zab/config.yaml (ou remote_vm.deploy_config)."
        ),
    }


# ── exécution externe ────────────────────────────────────────────────────────


_BIN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "gcloud": (
        "~/google-cloud-sdk/bin/gcloud",
        "/opt/homebrew/bin/gcloud",
        "/usr/local/bin/gcloud",
        "/usr/bin/gcloud",
    ),
    "bq": (
        "~/google-cloud-sdk/bin/bq",
        "/opt/homebrew/bin/bq",
        "/usr/local/bin/bq",
    ),
    "mutagen": (
        "/opt/homebrew/bin/mutagen",
        "/usr/local/bin/mutagen",
        "~/.local/bin/mutagen",
    ),
    "ssh": ("/usr/bin/ssh", "/opt/homebrew/bin/ssh"),
}


def resolve_bin(name: str) -> str | None:
    """Résout un binaire hors PATH (le serveur API n'hérite pas du PATH du shell)."""
    override = os.environ.get(f"ZAB_{name.upper()}_BIN", "").strip()
    if override and Path(override).expanduser().is_file():
        return str(Path(override).expanduser())
    found = shutil.which(name)
    if found:
        return found
    for candidate in _BIN_CANDIDATES.get(name, ()):
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path)
    return None


def _run(cmd: list[str], *, timeout: int = 30, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False, env=merged
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout après {timeout}s"
    except OSError as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _gcloud(cfg: dict[str, Any], args: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
    gcloud = resolve_bin("gcloud")
    if not gcloud:
        return 127, "", "gcloud introuvable"
    cmd = [gcloud]
    if cfg.get("gcloud_config"):
        cmd += ["--configuration", str(cfg["gcloud_config"])]
    return _run(cmd + args, timeout=timeout)


# ── transport REST ───────────────────────────────────────────────────────────
#
# Le SDK Google pèse près d'un gigaoctet dans une image de conteneur, pour un
# service qui n'a besoin que de trois appels Compute et d'une requête BigQuery.
# Quand les binaires sont absents — typiquement une exécution en conteneur — on
# passe donc par les API REST avec les identifiants par défaut de l'environnement.

_API_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _adc_token() -> str:
    import google.auth
    from google.auth.transport.requests import Request

    creds, _ = google.auth.default(scopes=[_API_SCOPE])
    creds.refresh(Request())
    token = getattr(creds, "token", None)
    if not token:
        raise RuntimeError("identifiants par défaut indisponibles")
    return str(token)


def _api_call(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        response = client.request(
            method,
            url,
            json=json_body,
            headers={"Authorization": f"Bearer {_adc_token()}"},
        )
    if response.status_code >= 400:
        detail = ""
        try:
            detail = str(response.json().get("error", {}).get("message", ""))
        except Exception:  # noqa: BLE001 - le corps peut ne pas être du JSON
            detail = response.text[:200]
        raise RuntimeError(f"{method} {url.split('/v1/')[-1]}: {response.status_code} {detail}".strip())
    if not response.content:
        return {}
    return response.json()


def _compute_url(cfg: dict[str, Any], suffix: str) -> str:
    return (
        "https://compute.googleapis.com/compute/v1/projects/"
        f"{cfg['project']}/zones/{cfg['zone']}/{suffix}"
    )


def _fetch_instance(cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Description de l'instance, par gcloud si présent, sinon par l'API REST."""
    if resolve_bin("gcloud"):
        code, raw, err = _gcloud(
            cfg,
            [
                "compute",
                "instances",
                "describe",
                cfg["instance"],
                f"--project={cfg['project']}",
                f"--zone={cfg['zone']}",
                "--format=json",
            ],
            timeout=45,
        )
        if code != 0:
            return None, (err or raw or "gcloud instances describe a échoué").strip().splitlines()[0][:400]
        try:
            return json.loads(raw), None
        except json.JSONDecodeError:
            return None, "réponse gcloud illisible"
    try:
        return _api_call("GET", _compute_url(cfg, f"instances/{cfg['instance']}")), None
    except (RuntimeError, httpx.HTTPError) as exc:
        return None, str(exc)[:400]


def _fetch_machine_type(cfg: dict[str, Any], machine_type: str) -> dict[str, Any] | None:
    if resolve_bin("gcloud"):
        code, out, _ = _gcloud(
            cfg,
            [
                "compute",
                "machine-types",
                "describe",
                machine_type,
                f"--project={cfg['project']}",
                f"--zone={cfg['zone']}",
                "--format=json",
            ],
        )
        if code != 0:
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None
    try:
        return _api_call("GET", _compute_url(cfg, f"machineTypes/{machine_type}"))
    except (RuntimeError, httpx.HTTPError):
        return None


# ── état de la VM ────────────────────────────────────────────────────────────


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _machine_shape(cfg: dict[str, Any], machine_type: str) -> dict[str, Any]:
    """vCPU / RAM d'un type de machine, mis en cache (les types sont immuables)."""
    if not machine_type:
        return {"vcpus": None, "memory_gb": None}
    cache_path = data_dir() / _STATE_DIR / "machine-types.json"
    cache: dict[str, Any] = {}
    if cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            cache = {}
    if machine_type in cache:
        return cache[machine_type]

    shape: dict[str, Any] = {"vcpus": None, "memory_gb": None}
    data = _fetch_machine_type(cfg, machine_type)
    if data:
        try:
            shape = {
                "vcpus": int(data.get("guestCpus") or 0) or None,
                "memory_gb": round(int(data.get("memoryMb") or 0) / 1024, 2) or None,
            }
        except (TypeError, ValueError):
            shape = {"vcpus": None, "memory_gb": None}
    if shape["vcpus"] is None:
        match = re.search(r"-(\d+)$", machine_type)
        if match:
            shape["vcpus"] = int(match.group(1))
    if shape["vcpus"]:
        cache[machine_type] = shape
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2) + "\n")
    return shape


def vm_state() -> dict[str, Any]:
    """État Compute Engine + durée de la session en cours."""
    cfg = config()
    if not is_configured(cfg):
        return _not_configured("vm")

    out: dict[str, Any] = {
        "configured": True,
        "project": cfg["project"],
        "zone": cfg["zone"],
        "instance": cfg["instance"],
        "auto_stop_idle_minutes": cfg.get("auto_stop_idle_minutes") or None,
        "found": False,
        "status": None,
        "error": None,
    }
    inst, error = _fetch_instance(cfg)
    if inst is None:
        out["status"] = "error"
        out["error"] = error
        return out

    machine_type = str(inst.get("machineType") or "").rstrip("/").split("/")[-1]
    disks = inst.get("disks") or []
    disk_rows = []
    for disk in disks:
        if not isinstance(disk, dict):
            continue
        try:
            size = int(disk.get("diskSizeGb") or 0) or None
        except (TypeError, ValueError):
            size = None
        disk_rows.append(
            {
                "name": str(disk.get("deviceName") or disk.get("source") or "").rstrip("/").split("/")[-1],
                "size_gb": size,
                "boot": bool(disk.get("boot")),
                "type": str(disk.get("type") or ""),
            }
        )

    nets = inst.get("networkInterfaces") or []
    internal_ip = external_ip = None
    if nets and isinstance(nets[0], dict):
        internal_ip = nets[0].get("networkIP")
        access = nets[0].get("accessConfigs") or []
        if access and isinstance(access[0], dict):
            external_ip = access[0].get("natIP")

    started = _parse_ts(inst.get("lastStartTimestamp"))
    stopped = _parse_ts(inst.get("lastStopTimestamp"))
    now = datetime.now(timezone.utc)
    status = str(inst.get("status") or "UNKNOWN")
    session_seconds = None
    if status == "RUNNING" and started:
        session_seconds = max(0, int((now - started).total_seconds()))
    last_session_seconds = None
    if started and stopped and stopped > started:
        last_session_seconds = int((stopped - started).total_seconds())

    shape = _machine_shape(cfg, machine_type)
    out.update(
        {
            "found": True,
            "status": status,
            "machine_type": machine_type,
            "vcpus": shape.get("vcpus"),
            "memory_gb": shape.get("memory_gb"),
            "disks": disk_rows,
            "disk_total_gb": sum(d["size_gb"] or 0 for d in disk_rows) or None,
            "internal_ip": internal_ip,
            "external_ip": external_ip,
            "last_start": inst.get("lastStartTimestamp"),
            "last_stop": inst.get("lastStopTimestamp"),
            "session_seconds": session_seconds,
            "last_session_seconds": last_session_seconds,
            "labels": inst.get("labels") if isinstance(inst.get("labels"), dict) else {},
            "console_url": (
                "https://console.cloud.google.com/compute/instancesDetail/zones/"
                f"{cfg['zone']}/instances/{cfg['instance']}?project={cfg['project']}"
            ),
            "checked_at": now.replace(microsecond=0).isoformat(),
        }
    )
    return out


# ── coûts et heures (export BigQuery de facturation) ─────────────────────────


def _categorize(sku: str) -> str:
    low = sku.lower()
    for category, needles in CATEGORY_RULES:
        if any(needle in low for needle in needles):
            return category
    return "other"


def _cost_sql(table: str, matches: list[str], days: int) -> str:
    if not _SAFE_TABLE.match(table):
        raise ValueError(f"table de facturation invalide: {table}")
    safe_matches = [m for m in matches if _SAFE_MATCH.match(m)]
    if not safe_matches:
        raise ValueError("aucun motif de ressource valide (billing.resource_match)")
    predicate = " OR ".join(
        f"LOWER(IFNULL(resource.name,'')) LIKE '{m}' OR LOWER(IFNULL(resource.global_name,'')) LIKE '{m}'"
        for m in (m.lower() for m in safe_matches)
    )
    return f"""
SELECT
  FORMAT_DATE('%Y-%m-%d', DATE(usage_start_time)) AS day,
  sku.description AS sku,
  SUM(cost) AS cost,
  SUM((SELECT IFNULL(SUM(c.amount), 0) FROM UNNEST(credits) c)) AS credits,
  SUM(IFNULL(usage.amount_in_pricing_units, 0)) AS units,
  ANY_VALUE(usage.pricing_unit) AS unit,
  ANY_VALUE(currency) AS currency
FROM `{table}`
WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {int(days)} DAY)
  AND ({predicate})
GROUP BY day, sku
ORDER BY day
""".strip()


def _billing_query_rest(project: str, sql: str) -> list[dict[str, Any]]:
    """Exécute la requête via l'API BigQuery et remet les lignes à plat."""
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries"
    payload = _api_call(
        "POST",
        url,
        json_body={"query": sql, "useLegacySql": False, "timeoutMs": 120000, "maxResults": 5000},
        timeout=180.0,
    )
    if not payload.get("jobComplete"):
        job_id = (payload.get("jobReference") or {}).get("jobId")
        if not job_id:
            raise RuntimeError("requête BigQuery inachevée sans identifiant de job")
        payload = _api_call("GET", f"{url}/{job_id}?timeoutMs=120000&maxResults=5000", timeout=180.0)
        if not payload.get("jobComplete"):
            raise RuntimeError("requête BigQuery toujours inachevée")

    fields = [f.get("name") for f in (payload.get("schema") or {}).get("fields", [])]
    rows: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        cells = [cell.get("v") for cell in row.get("f") or []]
        rows.append(dict(zip(fields, cells)))
    return rows


def _run_billing_query(cfg: dict[str, Any], days: int) -> list[dict[str, Any]]:
    billing = cfg["billing"]
    sql = _cost_sql(str(billing["table"]), list(billing["resource_match"]), days)
    bq = resolve_bin("bq")
    if not bq:
        project = str(billing.get("project") or cfg["project"])
        try:
            return _billing_query_rest(project, sql)
        except (RuntimeError, httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(str(exc)[:400]) from exc
    env = {}
    if billing.get("gcloud_config"):
        env["CLOUDSDK_ACTIVE_CONFIG_NAME"] = str(billing["gcloud_config"])
    cmd = [bq, "query", "--nouse_legacy_sql", "--format=json", "--max_rows=5000", "--quiet"]
    if billing.get("project"):
        cmd.append(f"--project_id={billing['project']}")
    cmd.append(sql)
    code, out, err = _run(cmd, timeout=180, env=env)
    if code != 0:
        raise RuntimeError((err or out or "requête BigQuery échouée").strip().splitlines()[-1][:400])
    text = out.strip()
    start = text.find("[")
    if start < 0:
        return []
    return json.loads(text[start:])


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_cost_report(cfg: dict[str, Any], rows: list[dict[str, Any]], days: int) -> dict[str, Any]:
    # Les heures d'exécution se déduisent des core-heures facturées : sans le
    # nombre de vCPU, la fenêtre entière s'afficherait à zéro heure.
    shape = _machine_shape(cfg, str(cfg.get("machine_type") or ""))
    vcpus = shape.get("vcpus")
    memory_gb = shape.get("memory_gb")

    by_day: dict[str, dict[str, Any]] = {}
    by_sku: dict[str, dict[str, Any]] = {}
    currency = str(cfg["billing"].get("currency") or "EUR")

    for row in rows:
        day = str(row.get("day") or "")
        if not day:
            continue
        sku = str(row.get("sku") or "")
        cost = _float(row.get("cost"))
        credits = _float(row.get("credits"))
        units = _float(row.get("units"))
        currency = str(row.get("currency") or currency)
        category = _categorize(sku)

        bucket = by_day.setdefault(
            day,
            {"day": day, "cost": 0.0, "credits": 0.0, "compute": 0.0, "storage": 0.0, "network": 0.0, "other": 0.0, "core_hours": 0.0, "ram_gb_hours": 0.0},
        )
        bucket["cost"] += cost
        bucket["credits"] += credits
        bucket[category] += cost
        low = sku.lower()
        if "instance core" in low:
            bucket["core_hours"] += units
        elif "instance ram" in low:
            bucket["ram_gb_hours"] += units

        agg = by_sku.setdefault(sku, {"sku": sku, "category": category, "cost": 0.0, "units": 0.0, "unit": row.get("unit")})
        agg["cost"] += cost
        agg["units"] += units

    days_rows: list[dict[str, Any]] = []
    for day in sorted(by_day):
        row = by_day[day]
        hours = None
        if vcpus and row["core_hours"]:
            hours = row["core_hours"] / vcpus
        elif memory_gb and row["ram_gb_hours"]:
            hours = row["ram_gb_hours"] / memory_gb
        row["hours"] = round(hours, 3) if hours is not None else 0.0
        row["net_cost"] = round(row["cost"] + row["credits"], 6)
        for key in ("cost", "credits", "compute", "storage", "network", "other", "core_hours", "ram_gb_hours"):
            row[key] = round(row[key], 6)
        days_rows.append(row)

    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1)

    def _sum(rows_: list[dict[str, Any]], key: str) -> float:
        return round(sum(r[key] for r in rows_), 4)

    mtd_rows = [r for r in days_rows if date.fromisoformat(r["day"]) >= month_start]
    last7_rows = [r for r in days_rows if date.fromisoformat(r["day"]) >= today - timedelta(days=7)]
    # Le jour courant n'est que partiellement facturé : il fausse toute moyenne.
    complete_rows = [r for r in days_rows if date.fromisoformat(r["day"]) < today]
    running_days = [r for r in days_rows if r["hours"] > 0]
    idle_days = [r for r in complete_rows if r["hours"] <= 0.01]

    total_hours = _sum(days_rows, "hours")
    compute_cost = _sum(days_rows, "compute")
    hourly_rate = round(compute_cost / total_hours, 4) if total_hours else None
    if idle_days:
        fixed_daily = round(_sum(idle_days, "net_cost") / len(idle_days), 4)
    elif complete_rows:
        fixed_daily = round(
            (_sum(complete_rows, "storage") + _sum(complete_rows, "other")) / len(complete_rows), 4
        )
    else:
        fixed_daily = None

    days_in_month = ((month_start + timedelta(days=32)).replace(day=1) - month_start).days
    mtd_net = _sum(mtd_rows, "net_cost")
    mtd_complete = [r for r in mtd_rows if date.fromisoformat(r["day"]) < today]
    if mtd_complete:
        projection = round(_sum(mtd_complete, "net_cost") / len(mtd_complete) * days_in_month, 2)
    elif today.day:
        projection = round(mtd_net / today.day * days_in_month, 2)
    else:
        projection = None

    last_day = days_rows[-1]["day"] if days_rows else None
    lag_days = (today - date.fromisoformat(last_day)).days if last_day else None
    billed_through = complete_rows[-1]["day"] if complete_rows else None

    return {
        "configured": True,
        "currency": currency,
        "window_days": days,
        "days": days_rows,
        "by_sku": sorted(by_sku.values(), key=lambda r: -r["cost"])[:12],
        "totals": {
            "window_cost": _sum(days_rows, "net_cost"),
            "window_hours": total_hours,
            "mtd_cost": mtd_net,
            "mtd_hours": _sum(mtd_rows, "hours"),
            "last7_cost": _sum(last7_rows, "net_cost"),
            "last7_hours": _sum(last7_rows, "hours"),
            "today_cost": _sum([r for r in days_rows if r["day"] == today.isoformat()], "net_cost"),
            "today_hours": _sum([r for r in days_rows if r["day"] == today.isoformat()], "hours"),
            "running_days": len(running_days),
            "hourly_rate": hourly_rate,
            "fixed_daily_cost": fixed_daily,
            "month_projection": projection,
        },
        "freshness": {
            "last_billed_day": last_day,
            "billed_through": billed_through,
            "lag_days": lag_days,
        },
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _cost_cache_path(days: int) -> Path:
    return data_dir() / _STATE_DIR / f"cost-{int(days)}d.json"


def cost_report(days: int = 30, *, refresh: bool = False) -> dict[str, Any]:
    """Coûts et heures d'exécution issus de l'export de facturation, avec cache disque."""
    cfg = config()
    if not is_configured(cfg):
        return _not_configured("cost")
    if not cfg["billing"].get("table"):
        return {
            "configured": False,
            "section": "cost",
            "error": (
                "Configure remote_vm.billing.table (export BigQuery de facturation, "
                "table niveau ressource) dans ~/.config/zab/config.yaml."
            ),
        }

    cache_path = _cost_cache_path(days)
    if not refresh and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text())
            generated = _parse_ts(cached.get("generated_at"))
            if generated and (datetime.now(timezone.utc) - generated).total_seconds() < COST_CACHE_TTL_SECONDS:
                cached["cached"] = True
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    try:
        rows = _run_billing_query(cfg, days)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        stale = None
        if cache_path.is_file():
            try:
                stale = json.loads(cache_path.read_text())
            except (OSError, json.JSONDecodeError):
                stale = None
        if stale:
            stale["cached"] = True
            stale["stale"] = True
            stale["error"] = str(exc)
            return stale
        return {"configured": True, "section": "cost", "error": str(exc), "days": [], "by_sku": []}

    report = _build_cost_report(cfg, rows, days)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    report["cached"] = False
    return report


# ── connexions SSH ───────────────────────────────────────────────────────────


def _elapsed_to_seconds(value: str) -> int | None:
    """Convertit le format `etime` de ps ([[dd-]hh:]mm:ss) en secondes."""
    value = value.strip()
    if not value:
        return None
    days = 0
    if "-" in value:
        head, _, value = value.partition("-")
        try:
            days = int(head)
        except ValueError:
            return None
    parts = value.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.insert(0, 0)
    return days * 86400 + nums[0] * 3600 + nums[1] * 60 + nums[2]


def ssh_state() -> dict[str, Any]:
    """Connexions SSH locales vers la VM : multiplexage, tunnels et agents de sync."""
    cfg = config()
    if not is_configured(cfg):
        return _not_configured("ssh")

    alias = str(cfg.get("ssh_alias") or cfg["instance"])
    instance = str(cfg["instance"])
    out: dict[str, Any] = {
        "configured": True,
        "alias": alias,
        "control_master": {"state": "unknown", "detail": None},
        "connections": [],
        "tunnels": 0,
        "sync_agents": 0,
        "shells": 0,
        "mutagen_daemon": False,
    }

    ssh = resolve_bin("ssh")
    # Les connexions SSH et la synchronisation sont des faits **locaux** : seule la
    # machine qui les porte peut les voir. Un serveur distant doit le dire, sinon
    # « zéro connexion » se lit comme « rien ne tourne » au lieu de « je ne sais pas ».
    out["observable"] = ssh is not None
    if ssh and cfg.get("ssh_alias"):
        code, sout, serr = _run([ssh, "-O", "check", alias], timeout=10)
        detail = (sout or serr or "").strip().splitlines()
        detail_line = detail[0][:200] if detail else None
        if code == 0:
            out["control_master"] = {"state": "up", "detail": detail_line}
        elif "No such file or directory" in (serr or "") or "not found" in (serr or "").lower():
            out["control_master"] = {"state": "down", "detail": "aucun socket de contrôle"}
        else:
            out["control_master"] = {"state": "down", "detail": detail_line}

    code, ps_out, _ = _run(["ps", "-eo", "pid=,etime=,command="], timeout=15)
    if code != 0:
        out["observable"] = False
    if code == 0:
        for line in ps_out.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(None, 2)
            if len(parts) < 3:
                continue
            pid_raw, etime, command = parts
            if instance not in command and alias not in command:
                continue
            low = command.lower()
            is_ssh = "/ssh" in low or low.startswith("ssh ") or " ssh " in low
            is_tunnel = "start-iap-tunnel" in low or "tunnel-through-iap" in low
            if not (is_ssh or is_tunnel):
                continue
            if "mutagen" in low and "daemon" in low:
                continue
            kind = "tunnel" if is_tunnel else ("sync-agent" if "mutagen" in low else "shell")
            if "-mnf" in low or "controlmaster" in low:
                kind = "control-master"
            try:
                pid = int(pid_raw)
            except ValueError:
                continue
            out["connections"].append(
                {
                    "pid": pid,
                    "kind": kind,
                    "elapsed_seconds": _elapsed_to_seconds(etime),
                    "command": command[:180],
                }
            )
        out["mutagen_daemon"] = "mutagen daemon" in ps_out

    out["tunnels"] = sum(1 for c in out["connections"] if c["kind"] == "tunnel")
    out["sync_agents"] = sum(1 for c in out["connections"] if c["kind"] == "sync-agent")
    out["shells"] = sum(1 for c in out["connections"] if c["kind"] in {"shell", "control-master"})
    out["active"] = bool(out["connections"]) or out["control_master"]["state"] == "up"
    out["checked_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return out


# ── état de synchronisation (Mutagen) ────────────────────────────────────────


def _endpoint_summary(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    staging = data.get("stagingProgress") if isinstance(data.get("stagingProgress"), dict) else {}
    return {
        "protocol": data.get("protocol"),
        "host": data.get("host"),
        "path": data.get("path"),
        "connected": bool(data.get("connected")),
        "scanned": bool(data.get("scanned")),
        "files": int(data.get("files") or 0),
        "directories": int(data.get("directories") or 0),
        "symlinks": int(data.get("symbolicLinks") or 0),
        "total_size": int(data.get("totalFileSize") or 0),
        "scan_problems": len(data.get("scanProblems") or []),
        "transition_problems": len(data.get("transitionProblems") or []),
        "staging": (
            {
                "path": staging.get("path"),
                "received": int(staging.get("receivedFiles") or 0),
                "total": int(staging.get("totalFiles") or 0),
            }
            if staging
            else None
        ),
    }


def sync_state() -> dict[str, Any]:
    """Sessions Mutagen dont le beta pointe vers la VM : fichiers, écart et conflits."""
    cfg = config()
    if not is_configured(cfg):
        return _not_configured("sync")

    alias = str(cfg.get("ssh_alias") or cfg["instance"])
    out: dict[str, Any] = {
        "configured": True,
        "engine": str(cfg.get("sync_engine") or "mutagen"),
        "alias": alias,
        "sessions": [],
        "error": None,
    }

    mutagen = resolve_bin("mutagen")
    out["observable"] = mutagen is not None
    if not mutagen:
        out["error"] = "synchronisation non observable depuis cet hôte (mutagen absent)"
        return out

    code, raw, err = _run([mutagen, "sync", "list", "--template={{ json . }}"], timeout=45)
    if code != 0:
        out["error"] = (err or raw or "mutagen sync list a échoué").strip().splitlines()[0][:300]
        return out
    try:
        sessions = json.loads(raw or "[]")
    except json.JSONDecodeError:
        out["error"] = "sortie mutagen illisible"
        return out
    if not isinstance(sessions, list):
        sessions = []

    rows: list[dict[str, Any]] = []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        beta = session.get("beta") if isinstance(session.get("beta"), dict) else {}
        host = str(beta.get("host") or "")
        if host and alias and host != alias and cfg["instance"] not in host:
            continue
        alpha_sum = _endpoint_summary(session.get("alpha"))
        beta_sum = _endpoint_summary(beta)
        conflicts = session.get("conflicts") or []
        rows.append(
            {
                "name": session.get("name") or session.get("identifier"),
                "status": session.get("status"),
                "paused": bool(session.get("paused")),
                "mode": session.get("mode"),
                "last_error": (str(session.get("lastError") or "") or None),
                "successful_cycles": int(session.get("successfulCycles") or 0),
                "conflicts": len(conflicts),
                "excluded_conflicts": int(session.get("excludedConflicts") or 0),
                "alpha": alpha_sum,
                "beta": beta_sum,
                "file_delta": alpha_sum["files"] - beta_sum["files"],
                "problems": (
                    alpha_sum["scan_problems"]
                    + alpha_sum["transition_problems"]
                    + beta_sum["scan_problems"]
                    + beta_sum["transition_problems"]
                ),
            }
        )

    rows.sort(key=lambda r: str(r["name"] or ""))
    connected = sum(1 for r in rows if r["alpha"]["connected"] and r["beta"]["connected"])
    watching = sum(1 for r in rows if str(r["status"] or "") == "watching")
    out.update(
        {
            "sessions": rows,
            "totals": {
                "sessions": len(rows),
                "connected": connected,
                "watching": watching,
                "paused": sum(1 for r in rows if r["paused"]),
                "conflicts": sum(r["conflicts"] for r in rows),
                "problems": sum(r["problems"] for r in rows),
                "alpha_files": sum(r["alpha"]["files"] for r in rows),
                "beta_files": sum(r["beta"]["files"] for r in rows),
                "file_delta": sum(abs(r["file_delta"]) for r in rows),
                "alpha_size": sum(r["alpha"]["total_size"] for r in rows),
                "beta_size": sum(r["beta"]["total_size"] for r in rows),
                "staging_total": sum((r["beta"]["staging"] or {}).get("total", 0) for r in rows),
                "staging_received": sum((r["beta"]["staging"] or {}).get("received", 0) for r in rows),
            },
            "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
    )
    return out


# ── vue agrégée et actions ───────────────────────────────────────────────────


# ── préparation d'un agent (readiness) ───────────────────────────────────────

_READINESS_REQUIRED_BINS: tuple[str, ...] = ("git", "node", "python3")


def readiness_report(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Vérifie, en lecture seule, qu'un agent lancé par SSH sur la VM aura ce
    qu'il faut pour tourner.

    Un shell de connexion interactif (login) lit les profils (`.bash_profile`,
    `.zprofile`...) et expose souvent un PATH plus riche qu'une commande SSH
    non-interactive (`ssh alias cmd`) — c'est pourtant ce second PATH qu'hérite
    un agent lancé par l'automatisation, jamais le premier. Un binaire présent
    en interactif mais absent du non-login casse silencieusement sous
    l'automatisation, un piège déjà rencontré en pratique (voir
    AGENT_IMPROVEMENTS.md, 2026-08-01) et jusqu'ici jamais vérifié par du code,
    seulement par un audit manuel ponctuel.
    """
    cfg = cfg if cfg is not None else config()
    if not is_configured(cfg):
        return _not_configured("readiness")

    alias = str(cfg.get("ssh_alias") or cfg["instance"])
    out: dict[str, Any] = {"configured": True, "alias": alias, "observable": False, "checks": []}

    ssh = resolve_bin("ssh")
    if not ssh:
        out["error"] = "ssh introuvable localement"
        return out
    out["observable"] = True

    checks: list[dict[str, Any]] = []

    login_code, login_out, login_err = _run([ssh, alias, "bash", "-lc", "echo $PATH"], timeout=15)
    login_path = login_out.strip()
    checks.append(
        {
            "id": "login_shell_reachable",
            "status": "ok" if login_code == 0 and login_path else "error",
            "detail": login_path[:300] if login_path else (login_err or "aucune sortie").strip()[:300],
        }
    )

    nonlogin_code, nonlogin_out, nonlogin_err = _run([ssh, alias, "echo $PATH"], timeout=15)
    nonlogin_path = nonlogin_out.strip()
    checks.append(
        {
            "id": "non_login_shell_reachable",
            "status": "ok" if nonlogin_code == 0 and nonlogin_path else "error",
            "detail": nonlogin_path[:300] if nonlogin_path else (nonlogin_err or "aucune sortie").strip()[:300],
        }
    )

    path_parity = bool(login_path) and login_path == nonlogin_path
    checks.append(
        {
            "id": "path_parity",
            "status": "ok" if path_parity else "degraded",
            "detail": (
                "PATH identique entre shell login et non-login"
                if path_parity
                else f"login={login_path[:150]!r} non_login={nonlogin_path[:150]!r}"
            ),
        }
    )

    if nonlogin_code == 0:
        probe = " ; ".join(
            f"command -v {bin_name} >/dev/null 2>&1 && echo {bin_name}=ok || echo {bin_name}=missing"
            for bin_name in _READINESS_REQUIRED_BINS
        )
        probe_code, probe_out, probe_err = _run([ssh, alias, probe], timeout=15)
        results = dict(line.split("=", 1) for line in probe_out.strip().splitlines() if "=" in line)
        missing = [b for b in _READINESS_REQUIRED_BINS if results.get(b) != "ok"]
        checks.append(
            {
                "id": "non_login_binaries",
                "status": "ok" if probe_code == 0 and not missing else "error",
                "detail": (
                    f"manquants du PATH non-login: {', '.join(missing)}"
                    if missing
                    else "présents dans le PATH non-login: " + ", ".join(_READINESS_REQUIRED_BINS)
                ),
            }
        )
    else:
        checks.append(
            {
                "id": "non_login_binaries",
                "status": "unknown",
                "detail": "non vérifiable : non_login_shell_reachable a échoué",
            }
        )

    # Vérifie $HOME plutôt que ~/.config directement : un test en écriture reste
    # en lecture seule (aucune création de répertoire), et $HOME existe toujours.
    home_code, home_out, home_err = _run(
        [ssh, alias, 'test -w "$HOME" && echo writable || echo not_writable'], timeout=15
    )
    home_detail = home_out.strip()
    checks.append(
        {
            "id": "home_writable",
            "status": "ok" if home_code == 0 and home_detail == "writable" else "error",
            "detail": home_detail or (home_err or "aucune sortie").strip()[:200],
        }
    )

    out["checks"] = checks
    out["ok"] = all(c["status"] == "ok" for c in checks)
    out["checked_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return out


def overview() -> dict[str, Any]:
    """VM + SSH + sync en une lecture (sans requête de facturation)."""
    cfg = config()
    return {
        "configured": is_configured(cfg),
        "config": {
            "project": cfg["project"],
            "zone": cfg["zone"],
            "instance": cfg["instance"],
            "ssh_alias": cfg.get("ssh_alias"),
            "gcloud_config": cfg.get("gcloud_config"),
            "billing_configured": bool(cfg["billing"].get("table")),
            "vmctl": cfg.get("vmctl"),
            "auto_stop_idle_minutes": cfg.get("auto_stop_idle_minutes") or None,
        },
        "vm": vm_state(),
        "ssh": ssh_state(),
        "sync": sync_state(),
    }


def _vmctl(cfg: dict[str, Any], command: str, *, timeout: int) -> dict[str, Any] | None:
    script = str(cfg.get("vmctl") or "").strip()
    if not script:
        return None
    path = Path(script).expanduser()
    if not path.is_file():
        return None
    env = {}
    gcloud = resolve_bin("gcloud")
    if gcloud:
        env["GCLOUD"] = gcloud
        env["PATH"] = f"{Path(gcloud).parent}:{os.environ.get('PATH', '')}"
    code, out, err = _run(["bash", str(path), command], timeout=timeout, env=env)
    return {
        "ok": code == 0,
        "action": command,
        "via": "vmctl",
        "exit_code": code,
        "output": (out + err)[-4000:],
        "error": None if code == 0 else (err or out or "échec").strip()[-400:],
    }


def _instance_action(action: str, *, timeout: int) -> dict[str, Any]:
    cfg = config()
    if not is_configured(cfg):
        return {"ok": False, "action": action, "error": _not_configured("vm")["error"]}

    via_script = _vmctl(cfg, action, timeout=timeout)
    if via_script is not None:
        return via_script

    if resolve_bin("gcloud"):
        code, out, err = _gcloud(
            cfg,
            [
                "compute",
                "instances",
                action,
                cfg["instance"],
                f"--project={cfg['project']}",
                f"--zone={cfg['zone']}",
                "--quiet",
            ],
            timeout=timeout,
        )
        return {
            "ok": code == 0,
            "action": action,
            "via": "gcloud",
            "exit_code": code,
            "output": (out + err)[-4000:],
            "error": None if code == 0 else (err or out or "échec").strip()[-400:],
        }

    try:
        operation = _api_call("POST", _compute_url(cfg, f"instances/{cfg['instance']}/{action}"))
    except (RuntimeError, httpx.HTTPError) as exc:
        return {"ok": False, "action": action, "via": "api", "error": str(exc)[:400]}
    # L'opération Compute est asynchrone : la VM met encore une minute à être
    # utilisable. L'appelant suit la suite via `vm_state`.
    return {
        "ok": True,
        "action": action,
        "via": "api",
        "operation": operation.get("name"),
        "output": f"opération {operation.get('status', 'PENDING')}",
        "error": None,
    }


def start_vm() -> dict[str, Any]:
    return _instance_action("start", timeout=600)


def stop_vm() -> dict[str, Any]:
    return _instance_action("stop", timeout=600)


def sync_action(action: str) -> dict[str, Any]:
    """Actions de sync sûres (flush / resume / pause) via le script de pilotage."""
    allowed = {"sync-flush", "sync-resume", "sync-pause"}
    if action not in allowed:
        return {"ok": False, "action": action, "error": f"action non autorisée (attendu: {', '.join(sorted(allowed))})"}
    cfg = config()
    result = _vmctl(cfg, action, timeout=300)
    if result is None:
        return {"ok": False, "action": action, "error": "remote_vm.vmctl non configuré"}
    return result
