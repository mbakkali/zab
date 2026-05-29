"""Tests pour la source de connecteurs Composio."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from zab.services import composio_connectors as cc


@pytest.fixture(autouse=True)
def _clear_composio_cache():
    cc.clear_forms_cache()
    yield
    cc.clear_forms_cache()


_SAMPLE_ACCOUNTS = [
    {
        "id": "ca_abc123",
        "status": "ACTIVE",
        "toolkit": {"slug": "gmail", "name": "Gmail"},
        "auth_config": {"auth_scheme": "OAUTH2"},
    },
    {
        "id": "ca_def456",
        "status": "INITIATED",
        "toolkit": {"slug": "notion", "name": "Notion"},
        "auth_config": {"auth_scheme": "OAUTH2"},
    },
]


def _patch_key(monkeypatch: pytest.MonkeyPatch, key: str | None = "uak_test") -> None:
    monkeypatch.setattr(cc, "_composio_api_key", lambda: key)
    monkeypatch.setattr(cc, "_composio_base_url", lambda: "https://backend.composio.dev")


def test_fetch_connected_accounts_items_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_key(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") == "uak_test"
        return httpx.Response(200, json={"items": _SAMPLE_ACCOUNTS})

    _RealClient = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: _RealClient(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))
    accounts = cc.fetch_connected_accounts()
    assert len(accounts) == 2
    assert accounts[0]["id"] == "ca_abc123"


def test_fetch_connected_accounts_returns_empty_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_key(monkeypatch, None)
    assert cc.fetch_connected_accounts() == []


def test_fetch_connected_accounts_graceful_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_key(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    _RealClient = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: _RealClient(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))
    assert cc.fetch_connected_accounts() == []


def test_fetch_connected_accounts_graceful_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_key(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    _RealClient = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: _RealClient(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))
    assert cc.fetch_connected_accounts() == []


def test_composio_forms_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc, "fetch_connected_accounts", lambda timeout=4.0: list(_SAMPLE_ACCOUNTS))
    monkeypatch.setenv("COMPOSIO_MCP", "https://connect.composio.dev/mcp")
    forms = cc.composio_forms()
    assert [slug for slug, _ in forms] == ["gmail", "notion"]
    _, gmail_form = forms[0]
    assert gmail_form["kind"] == "composio"
    assert gmail_form["transport_kind"] == "http"
    assert gmail_form["enabled"] is True
    assert gmail_form["target"].startswith("gmail")
    assert gmail_form["meta"]["auth_scheme"] == "OAUTH2"
    assert gmail_form["meta"]["connected_account_id"] == "ca_abc123"
    assert gmail_form["meta"]["mcp_url"] == "https://connect.composio.dev/mcp"
    _, notion_form = forms[1]
    assert notion_form["enabled"] is False  # status != ACTIVE


def test_composio_forms_multiple_accounts_same_toolkit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cc,
        "fetch_connected_accounts",
        lambda timeout=4.0: [
            {
                "id": "ca_perso",
                "status": "ACTIVE",
                "toolkit": {"slug": "gmail", "name": "Gmail"},
                "auth_config": {"auth_scheme": "OAUTH2"},
                "user_id": "user_perso",
                "data": {"email": "alice@perso.com"},
            },
            {
                "id": "ca_pro",
                "status": "ACTIVE",
                "toolkit": {"slug": "gmail", "name": "Gmail"},
                "auth_config": {"auth_scheme": "OAUTH2"},
                "user_id": "user_pro",
                "data": {"email": "alice@boite.com"},
            },
        ],
    )
    forms = cc.composio_forms()
    assert [slug for slug, _ in forms] == ["gmail", "gmail"]
    ids = {f["id"] for _, f in forms}
    assert ids == {"composio-ca_perso", "composio-ca_pro"}
    targets = {f["target"] for _, f in forms}
    assert targets == {"gmail · alice@perso.com", "gmail · alice@boite.com"}
    emails = {f["meta"]["account_email"] for _, f in forms}
    assert emails == {"alice@perso.com", "alice@boite.com"}


def test_aggregator_groups_multiple_composio_accounts_under_one_row(monkeypatch: pytest.MonkeyPatch) -> None:
    from zab.services import connectors_aggregate as agg

    monkeypatch.setattr(agg, "list_mcp_servers_flat", lambda: [])
    monkeypatch.setattr(agg, "_api_forms_from_proxies", lambda: [])
    monkeypatch.setattr(
        agg,
        "composio_forms",
        lambda: [
            (
                "gmail",
                {"id": "composio-ca_a", "kind": "composio", "transport_kind": "http", "enabled": True, "target": "gmail · a@x.com", "source_label": "composio", "config_path": None, "source_ref": "x", "meta": {"toolkit_slug": "gmail", "toolkit_name": "Gmail"}},
            ),
            (
                "gmail",
                {"id": "composio-ca_b", "kind": "composio", "transport_kind": "http", "enabled": True, "target": "gmail · b@x.com", "source_label": "composio", "config_path": None, "source_ref": "x", "meta": {"toolkit_slug": "gmail", "toolkit_name": "Gmail"}},
            ),
        ],
    )
    rows = agg._build_connectors_raw()
    assert len(rows) == 1
    assert rows[0]["id"] == "gmail"
    assert len(rows[0]["forms"]) == 2
    assert rows[0]["tags"] == ["composio"]


def test_composio_forms_cache_avoids_double_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_fetch(timeout: float = 4.0) -> list[dict[str, Any]]:
        calls["n"] += 1
        return [{"id": "ca_1", "status": "ACTIVE", "toolkit": {"slug": "gmail"}}]

    monkeypatch.setattr(cc, "fetch_connected_accounts", fake_fetch)
    cc.composio_forms()
    cc.composio_forms()
    assert calls["n"] == 1
    cc.clear_forms_cache()
    cc.composio_forms()
    assert calls["n"] == 2


def test_composio_forms_handles_missing_toolkit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cc,
        "fetch_connected_accounts",
        lambda timeout=4.0: [{"id": "ca_x", "status": "ACTIVE", "app_name": "slack"}],
    )
    forms = cc.composio_forms()
    assert forms[0][0] == "slack"


def test_aggregator_includes_composio_with_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    from zab.services import connectors_aggregate as agg

    monkeypatch.setattr(agg, "list_mcp_servers_flat", lambda: [])
    monkeypatch.setattr(agg, "_api_forms_from_proxies", lambda: [])
    monkeypatch.setattr(
        agg,
        "composio_forms",
        lambda: [
            (
                "gmail",
                {
                    "id": "composio-ca_abc",
                    "kind": "composio",
                    "transport_kind": "http",
                    "enabled": True,
                    "target": "gmail",
                    "source_label": "composio",
                    "config_path": None,
                    "source_ref": "composio/connected_accounts/ca_abc",
                    "meta": {"toolkit_slug": "gmail", "toolkit_name": "Gmail", "auth_scheme": "OAUTH2", "connected_account_id": "ca_abc", "status": "ACTIVE", "mcp_url": None},
                },
            )
        ],
    )
    rows = agg._build_connectors_raw()
    assert len(rows) == 1
    assert rows[0]["id"] == "gmail"
    assert "composio" in rows[0]["tags"]
    assert rows[0]["forms"][0]["kind"] == "composio"

    listed = agg.list_connectors(tag="composio")
    assert listed["pagination"]["total"] == 1
    assert listed["data"][0]["tags"] == ["composio"]


def test_state_index_connector_agent_hints_for_composio(monkeypatch: pytest.MonkeyPatch) -> None:
    from zab.services import state_index

    monkeypatch.setattr(
        state_index.connectors_aggregate,
        "list_connectors",
        lambda limit=200: {
            "data": [
                {
                    "id": "gmail",
                    "display_name": "Gmail",
                    "tags": ["composio"],
                    "forms": [],
                }
            ]
        },
    )
    monkeypatch.setattr(
        state_index.connectors_aggregate,
        "get_connector",
        lambda slug: {
            "id": slug,
            "display_name": "Gmail",
            "tags": ["composio"],
            "forms": [
                {
                    "id": "composio-gmail_a",
                    "kind": "composio",
                    "target": "gmail · a@example.com",
                    "meta": {
                        "connected_account_id": "gmail_a",
                        "status": "ACTIVE",
                        "account_email": "a@example.com",
                    },
                },
                {
                    "id": "composio-gmail_b",
                    "kind": "composio",
                    "target": "gmail · b@example.com",
                    "meta": {
                        "connected_account_id": "gmail_b",
                        "status": "ACTIVE",
                        "account_email": "b@example.com",
                    },
                },
            ],
        },
    )

    rows = state_index._collect_connectors()
    hints = rows["gmail"]["agent_hints"]

    assert hints["forms_count"] == 2
    assert hints["accounts"][0]["id"] == "gmail_a"
    assert "list_accounts" in hints["commands"]
    assert any("multi_account" in warning for warning in hints["warnings"])
