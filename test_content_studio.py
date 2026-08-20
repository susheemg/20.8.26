"""Tests for the Content Studio ('Admin Change') override layer."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


def test_registry_loads_with_catalog(client):
    r = client.get("/api/v2/content/registry", headers=H).json()
    assert r["total"] >= 100
    assert any(g["group"].startswith("Navigation") for g in r["groups"])


def test_override_appears_in_public_map(client):
    client.put("/api/v2/content/item/nav.home", json={"value": "Start"}, headers=H)
    ov = client.get("/api/v2/content/overrides").json()["overrides"]
    assert ov.get("Home") == "Start"  # keyed by the exact default string


def test_reset_removes_override(client):
    client.put("/api/v2/content/item/brand.tagline", json={"value": "TPRM"}, headers=H)
    client.post("/api/v2/content/item/brand.tagline/reset", headers=H)
    ov = client.get("/api/v2/content/overrides").json()["overrides"]
    assert "ENTERPRISE TPRM" not in ov


def test_setting_to_default_is_a_reset(client):
    # setting a key back to its default value should clear the override
    client.put("/api/v2/content/item/nav.home", json={"value": "Start"}, headers=H)
    client.put("/api/v2/content/item/nav.home", json={"value": "Home"}, headers=H)
    ov = client.get("/api/v2/content/overrides").json()["overrides"]
    assert "Home" not in ov


def test_custom_string_override(client):
    src = "Exposure first. Controls second. Verdict last."
    client.post("/api/v2/content/custom", json={"source_text": src, "value": "Risk first."}, headers=H)
    ov = client.get("/api/v2/content/overrides").json()["overrides"]
    assert ov.get(src) == "Risk first."


def test_unknown_key_404(client):
    r = client.put("/api/v2/content/item/nope.nope", json={"value": "x"}, headers=H)
    assert r.status_code == 404


def test_permission_gate(client):
    # editing requires admin.content; reading overrides is public
    assert client.get("/api/v2/content/registry", headers={"X-User": "buyer"}).status_code in (401, 403)
    assert client.get("/api/v2/content/overrides").status_code == 200


def test_admin_role_has_new_permission(client):
    # the seed refresh must grant the freshly-added admin.content to admin
    from app.features.admin import rbac
    from app.features.domain.models_db import make_engine, make_session_factory
    from sqlalchemy import select
    # admin can reach the gated endpoint => permission present
    assert client.get("/api/v2/content/registry", headers=H).status_code == 200


def test_reset_all(client):
    client.put("/api/v2/content/item/nav.home", json={"value": "Start"}, headers=H)
    client.post("/api/v2/content/reset-all", headers=H)
    assert client.get("/api/v2/content/overrides").json()["overrides"] == {}
