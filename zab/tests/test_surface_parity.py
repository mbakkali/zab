from __future__ import annotations

from zab.services.capabilities import get_capabilities


SURFACE_FIELDS = ("core", "cli", "mcp", "api", "ui")
ALLOWED_STATUSES = {"complete", "partial", "deferred", "missing"}


def test_capabilities_have_explicit_surface_parity_status() -> None:
    payload = get_capabilities()

    assert payload["capabilities"], "capability manifest must not be empty"
    for capability in payload["capabilities"]:
        assert capability["status"] in ALLOWED_STATUSES
        assert capability["risk"] in {"read", "local_write", "external_read", "external_write", "destructive"}
        for field in SURFACE_FIELDS:
            assert field in capability, f"{capability['id']} missing surface field {field}"
            value = capability[field]
            assert value is None or isinstance(value, str)
        if capability["status"] == "complete":
            missing = [field for field in SURFACE_FIELDS if not capability[field]]
            assert not missing, f"{capability['id']} marked complete but missing {missing}"
        if capability["status"] in {"partial", "deferred", "missing"}:
            assert capability.get("parity_notes"), f"{capability['id']} needs parity_notes"


def test_capabilities_manifest_self_describes_exposed_surfaces() -> None:
    payload = get_capabilities()
    manifest = next(cap for cap in payload["capabilities"] if cap["id"] == "capabilities.manifest")

    assert manifest["status"] == "complete"
    assert manifest["core"] == "zab.services.capabilities.get_capabilities"
    assert manifest["cli"] == "zab capabilities --json"
    assert manifest["mcp"] == "capabilities"
    assert manifest["api"] == "GET /api/capabilities"
    assert manifest["ui"] == "Capabilities"
