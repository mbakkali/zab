"""Tests agrégation connecteurs MCP + proxies."""

from zab.services import connectors_aggregate


def test_normalize_slug():
    assert connectors_aggregate.normalize_connector_slug("user-linear") == "user-linear"
    assert connectors_aggregate.normalize_connector_slug("_TODO-foo-Bar") == "foo-bar"


def test_list_connectors_pagination_structure():
    r = connectors_aggregate.list_connectors(page=1, limit=5)
    assert "data" in r and "pagination" in r
    p = r["pagination"]
    assert "page" in p and "limit" in p and "total" in p and "total_pages" in p
    assert isinstance(r["data"], list)


def test_get_connector_known_or_miss():
    r = connectors_aggregate.list_connectors(limit=500)
    if not r["data"]:
        assert connectors_aggregate.get_connector("___no_such_slug___") is None
        return
    first_slug = str(r["data"][0]["id"])
    detail = connectors_aggregate.get_connector(first_slug)
    assert detail is not None
    assert detail["id"] == first_slug
    assert isinstance(detail.get("forms"), list)
