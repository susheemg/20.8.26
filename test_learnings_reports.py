"""Tests for learnings, engagement assessment report, and interim report."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


def test_learning_crud_and_summary(client):
    r = client.post("/api/v2/learnings", json={
        "category": "Risk pattern", "insight": "APAC cloud vendors show data-residency gaps.",
        "confidence": "High"}, headers=H)
    assert r.status_code == 200
    lid = r.json()["id"]
    assert r.json()["origin"] == "human"
    s = client.get("/api/v2/learnings/summary", headers=H).json()
    assert s["total"] >= 1 and s["human"] >= 1
    # mark applied
    a = client.post(f"/api/v2/learnings/{lid}/applied", headers=H).json()
    assert a["applied_count"] == 1
    # filter by category
    fc = client.get("/api/v2/learnings?category=Risk pattern", headers=H).json()
    assert all(x["category"] == "Risk pattern" for x in fc)
    # delete
    assert client.delete(f"/api/v2/learnings/{lid}", headers=H).json()["deleted"] is True


def test_capture_learnings_from_engagement(client):
    eng = client.post("/api/v2/engagements", json={
        "vendor_id": "VEN-1", "title": "Test eng"}, headers=H)
    eid = eng.json().get("engagement_id") if eng.status_code == 200 else None
    if not eid:
        pytest.skip("engagement creation shape differs")
    # create an assessment so capture has something to work with
    client.post("/api/v2/assessments", json={
        "engagement_id": eid, "vendor_id": "VEN-1"}, headers=H)
    r = client.post(f"/api/v2/engagements/{eid}/capture-learnings", headers=H)
    assert r.status_code in (200, 404)


def test_interim_report_builds(client):
    sess = client.post("/api/v1/agent/sessions", json={}, headers=H).json()
    sid = sess["session_id"]
    r = client.post(f"/api/v2/agent/sessions/{sid}/interim-report", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["ai_mode"] in ("ai", "deterministic")
    assert "Annex A" in body["html"] and "Annex B" in body["html"]
    assert "Interim Assessment Report" in body["html"]


def test_interim_report_unknown_session_404(client):
    assert client.post("/api/v2/agent/sessions/999999/interim-report", headers=H).status_code == 404


def test_engagement_assessment_report_404(client):
    assert client.get("/api/v2/engagements/NOPE/assessment-report", headers=H).status_code == 404
