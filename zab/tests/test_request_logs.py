from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.services import agent_context, jobs, request_logs


def _isolate_request_logs(monkeypatch, tmp_path: Path) -> Path:
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("ZAB_LOG_DIR", str(log_dir))
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(tmp_path / "zab.db"))
    monkeypatch.setenv("ZAB_ACTOR_ID", "mehdi")
    monkeypatch.delenv("ZAB_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("MEHDI_MEMORY_DATABASE_URL", raising=False)
    return log_dir


def test_request_logs_write_redact_query_and_summary(monkeypatch, tmp_path: Path) -> None:
    log_dir = _isolate_request_logs(monkeypatch, tmp_path)
    raw_secret = "sk-test-secret-value"

    event = request_logs.record_event(
        surface="mcp",
        component="mcp.tool",
        actor=request_logs.actor_context(surface="mcp", source="mcp", client="pytest-agent/1"),
        scope=request_logs.resolve_scope(project="zab"),
        request={
            "name": "capabilities",
            "tool": "capabilities",
            "args_redacted": {"token": raw_secret, "safe": "hello"},
            "input_hash": request_logs.input_hash({"token": raw_secret, "safe": "hello"}),
        },
        result={"status": "ok", "duration_ms": 12},
    )

    assert event["actor"]["id"] == "mehdi"
    requests_text = (log_dir / "requests.jsonl").read_text(encoding="utf-8")
    assert raw_secret not in requests_text
    assert '"token":"[redacted]"' in requests_text
    assert (log_dir / "mcp.jsonl").is_file()

    query = request_logs.query_events(surface="mcp", actor="mehdi", q="capabilities", limit=10)
    assert query["total"] >= 1
    assert query["events"][0]["request"]["name"] == "capabilities"

    summary = request_logs.summary(since="24h")
    assert summary["total"] >= 1
    assert any(row["id"] == "mcp" for row in summary["by_surface"])

    files = request_logs.list_files()
    assert files["log_dir"] == str(log_dir.resolve())
    assert {row["id"] for row in files["files"]} >= {"requests", "mcp", "errors"}


def test_request_logs_rotation_and_scope_resolution(monkeypatch, tmp_path: Path) -> None:
    log_dir = _isolate_request_logs(monkeypatch, tmp_path)
    monkeypatch.setenv("ZAB_LOG_MAX_BYTES", "1024")
    monkeypatch.setenv("ZAB_LOG_BACKUP_COUNT", "2")
    project = tmp_path / "projects" / "zab"
    child = project / "src"
    child.mkdir(parents=True)
    monkeypatch.setattr(
        request_logs,
        "_project_rows",
        lambda: [{"id": "zab", "name": "zab", "org": "nous", "path": str(project), "aliases": ["zb"]}],
    )

    scope = request_logs.resolve_scope(project_path=child)
    assert scope["org"] == "nous"
    assert scope["project_id"] == "zab"
    assert scope["resolution"] == "explicit_path"
    alias_scope = request_logs.resolve_scope(args={"project": "zb"})
    assert alias_scope["org"] == "nous"
    assert alias_scope["project_id"] == "zab"

    for idx in range(20):
        request_logs.record_event(
            surface="cli",
            component="cli",
            request={
                "name": f"command-{idx}",
                "command": "zab capabilities --json",
                "args_redacted": {"project_path": str(child), "payload": "x" * 800},
            },
            result={"status": "ok"},
            scope=scope,
        )

    assert (log_dir / "requests.jsonl").is_file()
    assert (log_dir / "requests.jsonl.1").is_file()


def test_api_request_logs_middleware_and_read_endpoints(monkeypatch, tmp_path: Path) -> None:
    _isolate_request_logs(monkeypatch, tmp_path)
    client = TestClient(create_app())

    response = client.get(
        "/api/health",
        headers={"X-Zab-Actor-Id": "dashboard-user", "X-Zab-Client": "dashboard"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Zab-Request-Id")

    events = client.get("/api/logs/events?surface=api&actor=dashboard-user&limit=10")
    assert events.status_code == 200
    payload = events.json()
    assert payload["total"] >= 1
    event = payload["events"][0]
    assert event["surface"] == "api"
    assert event["actor"]["id"] == "dashboard-user"
    assert event["request"]["path"] == "/api/health"
    assert event["result"]["http_status"] == 200

    summary = client.get("/api/logs/summary?since=24h")
    assert summary.status_code == 200
    assert summary.json()["total"] >= 1

    tail = client.get("/api/logs/tail?file=requests&lines=20")
    assert tail.status_code == 200
    assert any(row.get("surface") == "api" for row in tail.json()["events"])


def test_cli_main_logs_without_polluting_stdout(monkeypatch, tmp_path: Path, capsys) -> None:
    _isolate_request_logs(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["zab", "capabilities", "--json"])

    from zab import cli

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code in (0, None)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["contract"] == "capability-manifest"

    query = request_logs.query_events(surface="cli", actor="mehdi", q="capabilities", limit=10)
    assert query["total"] >= 1
    assert query["events"][0]["surface"] == "cli"
    assert query["events"][0]["request"]["name"] == "capabilities"


def test_mcp_tools_log_client_info_and_expose_log_tools(monkeypatch, tmp_path: Path) -> None:
    _isolate_request_logs(monkeypatch, tmp_path)
    tools = {tool["name"]: tool for tool in agent_context.mcp_tools()}
    assert "logs_summary" in tools
    assert "logs_query" in tools

    payload = agent_context.call_mcp_tool(
        "capabilities",
        {},
        client_info={"name": "pytest-agent", "version": "1"},
    )
    assert payload["contract"] == "capability-manifest"

    query = agent_context.call_mcp_tool(
        "logs_query",
        {"surface": "mcp", "q": "capabilities", "limit": 10},
        client_info={"name": "pytest-agent", "version": "1"},
    )
    assert query["total"] >= 1
    event = query["events"][0]
    assert event["surface"] == "mcp"
    assert event["request"]["name"] == "capabilities"
    assert event["actor"]["client"] == "pytest-agent/1"


def test_job_lifecycle_logs(monkeypatch, tmp_path: Path) -> None:
    _isolate_request_logs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        jobs,
        "build_argv_for_preset",
        lambda preset, extra=None: ([sys.executable, "-c", "pass"], str(tmp_path)),
    )
    store = jobs.JobStore()

    job = store.start("unit_job", {"project_path": str(tmp_path)})
    deadline = time.time() + 5
    while job.status not in {"done", "error", "cancelled"} and time.time() < deadline:
        time.sleep(0.05)

    assert job.status == "done"

    # `job.status` bascule avant que le worker n'ait écrit l'événement « done » :
    # interroger le journal dans la foulée le trouvait encore à « running » une
    # fois sur trois. On attend l'écriture, pas le statut.
    states: set[str] = set()
    while time.time() < deadline:
        query = request_logs.query_events(surface="jobs", q=job.id, limit=20)
        states = {event["result"]["status"] for event in query["events"]}
        if "done" in states:
            break
        time.sleep(0.05)

    query = request_logs.query_events(surface="jobs", q=job.id, limit=20)
    states = {event["result"]["status"] for event in query["events"]}
    assert {"queued", "running", "done"} <= states
    assert any(event["scope"]["project_path"] == str(tmp_path) for event in query["events"])
