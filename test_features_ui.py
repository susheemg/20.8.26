"""
Tests for the expanded feature routes (Group B–G parity) and the web UI.
"""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"
sys.path.insert(0, "/home/claude/tprm")

from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"x-user": "admin"}


def _client():
    return TestClient(create_app("sqlite:///:memory:"))


def _vendor(c, name="Acme", tier="Tier 1"):
    return c.post("/api/v1/vendors", json={"name": name, "tier": tier}, headers=H).json()["vendor_id"]


def _engagement(c, vid):
    return c.post("/api/v1/engagements", json={"vendor_id": vid, "title": "T"}, headers=H).json()["engagement_id"]


def test_web_ui_served_at_root():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200
    assert "BRO" in r.text and "<html" in r.text.lower()
    assert "brata" in r.text.lower()


def test_certifications():
    c = _client(); vid = _vendor(c)
    r = c.post("/api/v1/certifications",
               json={"vendor_id": vid, "name": "ISO 27001", "valid_until": "2027-01-01"}, headers=H)
    assert r.status_code == 200
    lst = c.get(f"/api/v1/vendors/{vid}/certifications", headers=H).json()
    assert any(x["name"] == "ISO 27001" for x in lst)


def test_documents_and_expiring_evidence():
    c = _client(); vid = _vendor(c)
    c.post("/api/v1/documents",
           json={"vendor_id": vid, "name": "SOC2.pdf", "doc_type": "independent_audit",
                 "next_validation": "2026-06-15"}, headers=H)
    exp = c.get("/api/v1/evidence/expiring", headers=H).json()
    assert any(d["name"] == "SOC2.pdf" for d in exp)


def test_fourth_party_concentration():
    c = _client()
    for i in range(3):
        vid = _vendor(c, name=f"V{i}")
        c.post("/api/v1/fourth-parties",
               json={"vendor_id": vid, "name": "BigCloud", "service": "hosting"}, headers=H)
    conc = c.get("/api/v1/fourth-parties/concentration", headers=H).json()
    assert any(f["name"] == "BigCloud" for f in conc)


def test_acceptance():
    c = _client(); vid = _vendor(c); eid = _engagement(c, vid)
    r = c.post("/api/v1/acceptances",
               json={"engagement_id": eid, "rationale": "compensating controls"}, headers=H)
    assert r.json()["accepted_by"] == "admin"


def test_contract_generation():
    c = _client(); vid = _vendor(c, tier="Tier 1"); eid = _engagement(c, vid)
    r = c.post(f"/api/v1/engagements/{eid}/contract", headers=H).json()
    assert r["tier"] == "Tier 1" and len(r["terms"]) > 0


def test_reassessment_schedule_and_complete():
    c = _client(); vid = _vendor(c); eid = _engagement(c, vid)
    rid = c.post("/api/v1/reassessments",
                 json={"engagement_id": eid, "mode": "periodic"}, headers=H).json()["reassessment_id"]
    done = c.post(f"/api/v1/reassessments/{rid}/complete", headers=H).json()
    assert done["completed"] is True


def test_cap_board():
    c = _client()
    c.post("/api/v1/findings", json={"title": "Patch gap", "severity": "high"}, headers=H)
    cap = c.get("/api/v1/cap", headers=H).json()
    assert cap["open_actions"] >= 1


def test_bia():
    c = _client(); vid = _vendor(c, tier="Tier 1")
    c.post(f"/api/v1/vendors/{vid}/critical", json={"reason": "core"}, headers=H)
    bia = c.get(f"/api/v1/vendors/{vid}/bia", headers=H).json()
    assert bia["impact"] == "HIGH"   # critical vendor


def test_dashboards():
    c = _client(); vid = _vendor(c); eid = _engagement(c, vid)
    c.post(f"/api/v1/engagements/{eid}/irq",
           json={"answers": {"Q1": "No", "Q2": "Mission-critical", "Q3": ["Payment Card"],
                             "Q5": "Yes", "Q4": ">1,000,000"}}, headers=H)
    assert c.get("/api/v1/dashboard/executive", headers=H).json()["engagements"] >= 1
    assert "by_stage" in c.get("/api/v1/dashboard/operational", headers=H).json()
    assert "by_residual" in c.get("/api/v1/dashboard/risk", headers=H).json()


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception:
            print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
