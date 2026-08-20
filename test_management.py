"""Tests for the Management dashboard (risk + ops views) and chat."""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H = {"x-user": "admin"}

def _seed(c):
    v = c.post("/api/v2/vendors", json={"legal_name": "Meridian Ltd", "tier": "Tier 1"}, headers=H).json()["vendor_id"]
    e = c.post("/api/v2/engagements", json={"vendor_id": v, "title": "Card processing"}, headers=H).json()["engagement_id"]
    c.post("/api/v2/assessments", json={"engagement_id": e, "vendor_id": v, "inherent_band": "HIGH"}, headers=H)
    c.post("/api/v2/findings", json={"title": "No MFA", "severity": "Critical", "engagement_id": e, "vendor_id": v}, headers=H)
    return v, e

def _c():
    c = TestClient(create_app("sqlite:///:memory:")); _seed(c); return c

def test_risk_view():
    c = _c()
    r = c.get("/api/v2/management/risk-view", headers=H).json()
    assert r["totals"]["vendors"] >= 1
    assert r["totals"]["open_findings"] >= 1
    assert "residual_distribution" in r and "findings_by_severity" in r

def test_ops_view():
    c = _c()
    o = c.get("/api/v2/management/ops-view", headers=H).json()
    assert "assessment_pipeline" in o
    assert o["actions"]["open"] >= 1
    assert len(o["awaiting_signoff"]) >= 1   # HIGH assessment awaiting sign-off

def test_chat_critical():
    c = _c()
    r = c.post("/api/v2/management/chat", json={"question": "which vendors are critical?"}, headers=H).json()
    assert r["engine"] == "deterministic"
    assert "critical" in r["answer"].lower()

def test_chat_findings():
    c = _c()
    r = c.post("/api/v2/management/chat", json={"question": "open findings by severity"}, headers=H).json()
    assert "open" in r["answer"].lower()
    assert "actions" in r["data"]

def test_chat_default_summary():
    c = _c()
    r = c.post("/api/v2/management/chat", json={"question": "give me an overview"}, headers=H).json()
    assert "portfolio" in r["answer"].lower()

def test_suggested_questions():
    c = _c()
    r = c.get("/api/v2/management/suggested", headers=H).json()
    assert len(r["questions"]) >= 5

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
