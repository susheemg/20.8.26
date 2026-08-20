"""Tests for the Nav & Layout config (structural 'Admin Change' — change c)."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


def test_catalog_lists_groups_and_items(client):
    cat = client.get("/api/v2/layout/catalog", headers=H).json()
    assert len(cat["groups"]) == 7
    slugs = {g["slug"] for g in cat["groups"]}
    assert {"assess", "monitor_manage", "analyse"} <= slugs


def test_hide_item_reflects_in_public_config(client):
    client.put("/api/v2/layout/item/reputation", json={"hidden": True}, headers=H)
    cfg = client.get("/api/v2/layout/config").json()
    assert cfg["items"].get("reputation", {}).get("hidden") is True


def test_hide_group(client):
    client.put("/api/v2/layout/group/documentation", json={"hidden": True}, headers=H)
    cfg = client.get("/api/v2/layout/config").json()
    assert cfg["groups"].get("documentation", {}).get("hidden") is True


def test_reorder_persists_order(client):
    order = ["vendors", "proassess", "assess"]
    client.post("/api/v2/layout/reorder", json={"slug": "assess", "order": order}, headers=H)
    cfg = client.get("/api/v2/layout/config").json()
    assert cfg["items"]["vendors"]["order"] < cfg["items"]["assess"]["order"]


def test_show_again_clears_override(client):
    client.put("/api/v2/layout/item/reputation", json={"hidden": True}, headers=H)
    client.put("/api/v2/layout/item/reputation", json={"hidden": False}, headers=H)
    cfg = client.get("/api/v2/layout/config").json()
    assert "reputation" not in cfg["items"]


def test_gated_item_rejected(client):
    r = client.put("/api/v2/layout/item/methodology", json={"hidden": True}, headers=H)
    assert r.status_code == 400


def test_unknown_item_404(client):
    r = client.put("/api/v2/layout/item/nope", json={"hidden": True}, headers=H)
    assert r.status_code == 404


def test_permission_gate(client):
    assert client.get("/api/v2/layout/catalog", headers={"X-User": "buyer"}).status_code in (401, 403)
    assert client.get("/api/v2/layout/config").status_code == 200


def test_reset_all(client):
    client.put("/api/v2/layout/item/reputation", json={"hidden": True}, headers=H)
    client.post("/api/v2/layout/reset-all", headers=H)
    assert client.get("/api/v2/layout/config").json() == {"items": {}, "groups": {}}
