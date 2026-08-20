"""R1: FDD / Reputation / Monitoring persist against registered vendor and feed risk profile."""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"; os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H = {"x-user": "admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _v(c, n="Acme Ltd"): return c.post("/api/v2/vendors", json={"legal_name": n}, headers=H).json()["vendor_id"]
FIGS = {"revenue":1000,"cogs":400,"ebit":200,"ebitda":260,"netProfit":150,"totalAssets":1200,"equity":800,"currentAssets":500,"currentLiabilities":250,"cash":150,"totalDebt":200,"retainedEarnings":400,"interest":10}

def test_fdd_persists_for_registered_vendor():
    c = _c(); v = _v(c)
    r = c.post("/api/v2/financial-dd", json={"figures": FIGS, "vendor_id": v}, headers=H).json()
    assert r["persisted"] is True
    m = c.get(f"/api/v2/vendor-master/{v}", headers=H).json()
    assert m["financial_health_band"] == r["banding"]

def test_fdd_not_persisted_for_other():
    c = _c()
    r = c.post("/api/v2/financial-dd", json={"figures": FIGS, "other_name": "Unregistered Co"}, headers=H).json()
    assert r["persisted"] is False

def test_reputation_persists_and_feeds_profile():
    c = _c(); v = _v(c)
    r = c.post("/api/v2/reputation", json={"vendor_id": v, "events": []}, headers=H).json()
    assert r["persisted"] is True
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert attrs["risk_profile"]["reputation_summary"] is not None

def test_monitoring_signal_feeds_risk_profile():
    c = _c(); v = _v(c)
    c.post("/api/v2/fin-monitor", json={"vendor_id": v}, headers=H)
    c.post("/api/v2/fin-monitor/sweep", json={}, headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert attrs["risk_profile"]["monitoring_signal"] in ("ok", "watch", "distress")

def test_inherent_residual_remain_authoritative():
    c = _c(); v = _v(c)
    e = c.post("/api/v2/engagements", json={"vendor_id": v, "title": "X"}, headers=H).json()["engagement_id"]
    c.post("/api/v2/assessments", json={"engagement_id": e, "vendor_id": v, "inherent_band": "HIGH"}, headers=H)
    # persist FDD; it must not overwrite engagement-derived inherent
    c.post("/api/v2/financial-dd", json={"figures": FIGS, "vendor_id": v}, headers=H)
    c.post(f"/api/v2/vendor-attributes/{v}/refresh-rollups", headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert attrs["risk_profile"]["inherent_band"] == "HIGH"  # from engagement, not FDD

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p == len(tests) else 1)
