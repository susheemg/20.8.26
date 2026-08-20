"""Tests for platform documentation (SOP/TDA) + version history."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


def test_get_sop_and_tda(client):
    for kind in ("sop", "tda"):
        r = client.get(f"/api/v2/platform-docs/{kind}", headers=H)
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == kind
        assert len(body["html"]) > 1000
        assert body["doc_version"]


def test_unknown_doc_404(client):
    assert client.get("/api/v2/platform-docs/nope", headers=H).status_code == 404


def test_version_history_parses(client):
    vh = client.get("/api/v2/platform-docs/versions", headers=H).json()
    assert len(vh) >= 4
    versions = [e["version"] for e in vh]
    assert "4.3.0" in versions
    # newest first, semver-shaped, with sections
    assert all(v.count(".") == 2 for v in versions)
    assert any(e["sections"] for e in vh)


def test_ai_update_injects_panel_and_stamps_version(client):
    before = client.get("/api/v2/platform-docs/sop", headers=H).json()
    r = client.post("/api/v2/platform-docs/sop/ai-update", headers=H)
    assert r.status_code == 200
    assert r.json()["ai_mode"] in ("deterministic", "gateway-enriched")
    after = client.get("/api/v2/platform-docs/sop", headers=H).json()
    assert "recent-platform-updates" in after["html"]
    assert after["doc_version"] == r.json()["doc_version"]
    # idempotent: second update replaces, not duplicates, the panel
    client.post("/api/v2/platform-docs/sop/ai-update", headers=H)
    again = client.get("/api/v2/platform-docs/sop", headers=H).json()
    assert again["html"].count('id="recent-platform-updates"') == 1
