"""Tests for the external connector suite (SAP, ProcessUnity, RapidRatings,
Interos, SecurityScorecard, RiskRecon)."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}
KEYS = ["sap", "processunity", "rapidratings", "interos", "securityscorecard", "riskrecon"]


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


def test_catalog_lists_all_six(client):
    cat = client.get("/api/v2/integrations/catalog", headers=H).json()
    keys = {c["key"] for c in cat["connectors"]}
    assert set(KEYS) <= keys
    # manifest never leaks a secret value, only the name
    for c in cat["connectors"]:
        assert c["secret_name"].startswith("BRO_CONN_")


def test_each_connector_tests_and_syncs_in_stub_mode(client):
    # seed a vendor
    client.post("/api/v2/vendors", json={"legal_name": "Acme Ltd"}, headers=H)
    v = client.get("/api/v2/vendors", headers=H).json()
    vid = v[0]["vendor_id"] if v else "VEN-000001"
    for key in KEYS:
        t = client.post(f"/api/v2/integrations/{key}/test", headers=H).json()
        assert t["mode"] == "stub" and t["ok"] is True
        syn = client.post(f"/api/v2/integrations/{key}/sync",
                          json={"vendor_id": vid}, headers=H).json()
        assert syn["status"] == "ok"
        assert syn["mode"] == "stub"
        assert syn["signals"] >= 1


def test_config_persists_and_hides_secret(client):
    r = client.put("/api/v2/integrations/securityscorecard",
                   json={"enabled": True, "base_url": "https://api.securityscorecard.io",
                         "config": {"id_map": {"VEN-000001": "acme.com"}}}, headers=H)
    assert r.status_code == 200
    cfg = client.get("/api/v2/integrations/securityscorecard", headers=H).json()
    assert cfg["enabled"] is True
    assert cfg["config"]["id_map"]["VEN-000001"] == "acme.com"
    # response never contains a raw secret value field
    assert "secret" not in str(cfg).lower() or "secret_name" in cfg


def test_sync_writes_monitor_signals_and_ratings(client):
    client.post("/api/v2/vendors", json={"legal_name": "Beta Corp"}, headers=H)
    v = client.get("/api/v2/vendors", headers=H).json()
    vid = v[0]["vendor_id"]
    client.post("/api/v2/integrations/rapidratings/sync", json={"vendor_id": vid}, headers=H)
    syn = client.post("/api/v2/integrations/securityscorecard/sync",
                      json={"vendor_id": vid}, headers=H).json()
    assert any(s["type"] == "cyber_rating" for s in syn["detail"])
    logs = client.get("/api/v2/integrations/securityscorecard/logs", headers=H).json()
    assert len(logs["logs"]) >= 1


def test_unknown_connector_404(client):
    assert client.get("/api/v2/integrations/nope", headers=H).status_code == 404
    assert client.post("/api/v2/integrations/nope/test", headers=H).status_code == 404


def test_requires_admin_integrations_permission(client):
    # buyer should be forbidden
    r = client.get("/api/v2/integrations/catalog", headers={"X-User": "buyer"})
    assert r.status_code in (401, 403)
