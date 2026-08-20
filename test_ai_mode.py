"""v4.14 — Fast Track / Deep Research mode: the `deep` flag is accepted on every
AI endpoint and threaded into the engines (review loop on/off)."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


def test_chat_accepts_deep(client):
    sid = client.post("/api/v1/agent/sessions", json={}, headers=H).json()["session_id"]
    for deep in (True, False):
        r = client.post("/api/v1/agent/send",
                        json={"session_id": sid, "message": "hi", "deep": deep}, headers=H)
        assert r.status_code == 200


def test_management_accepts_deep(client):
    for deep in (True, False):
        r = client.post("/api/v2/management/chat",
                        json={"question": "top risks?", "deep": deep}, headers=H)
        assert r.status_code == 200


def test_proassess_accepts_deep(client):
    for deep in (True, False):
        r = client.post("/api/v2/proassess/autonomous",
                        json={"free_text": "cloud vendor", "deep": deep}, headers=H)
        assert r.status_code == 200


def test_engine_threads_deep_to_review(monkeypatch):
    # _run_turn_live must pass review=deep through to llm_config.complete
    import app.features.assessment.agent_engine as AE
    captured = {}
    import app.agents.llm_config as L
    monkeypatch.setattr(L, "complete",
                        lambda *a, **k: captured.update(k) or "BODY. STAGE_COMPLETE: done")
    monkeypatch.setattr(AE, "_live_available", lambda: True)
    AE.run_turn("bro", 0, {}, [], "hello", deep=True)
    assert captured.get("review") is True
    AE.run_turn("bro", 0, {}, [], "hello", deep=False)
    assert captured.get("review") is False


def test_deep_defaults_false(client):
    # omitting deep is treated as Fast Track (no review)
    sid = client.post("/api/v1/agent/sessions", json={}, headers=H).json()["session_id"]
    r = client.post("/api/v1/agent/send", json={"session_id": sid, "message": "hi"}, headers=H)
    assert r.status_code == 200
