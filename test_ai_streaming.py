"""v4.13 — AI responsiveness: SSE streaming chat, single-pass interactive calls,
faster fail-fast gateway. Verified without live keys via the deterministic path."""
import os, time
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app
from app.agents import llm_config as L

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


def test_stream_endpoint_sse_shape(client):
    sid = client.post("/api/v1/agent/sessions", json={}, headers=H).json()["session_id"]
    with client.stream("POST", "/api/v1/agent/stream",
                       json={"session_id": sid, "message": "risks?"}, headers=H) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        body = "".join(list(r.iter_lines()))
    assert "event: meta" in body and "event: delta" in body and "event: done" in body


def test_stream_ai_off_is_instant(client):
    sid = client.post("/api/v1/agent/sessions", json={}, headers=H).json()["session_id"]
    t0 = time.time()
    with client.stream("POST", "/api/v1/agent/stream",
                       json={"session_id": sid, "message": "hi"}, headers=H) as r:
        list(r.iter_lines())
    assert time.time() - t0 < 5  # deterministic holding path must not hang


def test_gateway_defaults_fast_fail():
    # retries default reduced to 1 (was 2) so failover is quicker
    assert L._llm_max_retries() == 1


def test_complete_accepts_timeout_s():
    # signature accepts a per-call timeout; AI-off returns None quickly
    assert L.complete("s", "u", timeout_s=5) is None


def test_stream_complete_empty_when_ai_off():
    assert list(L.stream_complete("s", "u")) == []


def test_stream_persists_assistant_message(client):
    sid = client.post("/api/v1/agent/sessions", json={}, headers=H).json()["session_id"]
    with client.stream("POST", "/api/v1/agent/stream",
                       json={"session_id": sid, "message": "hello"}, headers=H) as r:
        list(r.iter_lines())
    hist = client.get(f"/api/v1/agent/sessions/{sid}", headers=H).json()
    msgs = hist.get("messages", [])
    assert any(m.get("role") in ("agent", "assistant") for m in msgs)
