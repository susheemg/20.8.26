"""Quality-check hardening regressions: bounded snapshot growth + phantom-entity 404s."""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"; os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
from app.features.domain.models_db import make_engine
from app.features.domain import master_ext as MX
from sqlalchemy import select, func
from sqlalchemy.orm import Session
H = {"x-user": "admin"}

def test_risk_profile_history_is_bounded():
    db = "sqlite:////tmp/qc_bound.db"
    if os.path.exists("/tmp/qc_bound.db"): os.remove("/tmp/qc_bound.db")
    c = TestClient(create_app(db))
    v = c.post("/api/v2/vendors", json={"legal_name": "B"}, headers=H).json()["vendor_id"]
    c.post("/api/v2/engagements", json={"vendor_id": v, "title": "X", "annual_value": 1}, headers=H)
    for _ in range(35): c.get(f"/api/v2/vendor360/{v}", headers=H)
    with Session(make_engine(db)) as s:
        n = s.scalar(select(func.count()).select_from(MX.VendorRiskProfile).where(MX.VendorRiskProfile.vendor_id == v))
    os.remove("/tmp/qc_bound.db")
    assert n <= 20, f"snapshot history unbounded: {n} rows"

def test_phantom_engagement_criticality_404():
    c = TestClient(create_app("sqlite:///:memory:"))
    assert c.get("/api/v2/engagements/ENG-PHANTOM/criticality", headers=H).status_code == 404

def test_phantom_engagement_inputs_404():
    c = TestClient(create_app("sqlite:///:memory:"))
    r = c.put("/api/v2/engagements/ENG-PHANTOM/criticality-inputs",
              json={"customer_impact": 5}, headers=H)
    assert r.status_code == 404

def test_carry_forward_performance_survives_refresh():
    # publishing a scorecard then a later refresh must not blank the performance rollup
    c = TestClient(create_app("sqlite:///:memory:"))
    v = c.post("/api/v2/vendors", json={"legal_name": "P"}, headers=H).json()["vendor_id"]
    e = c.post("/api/v2/engagements", json={"vendor_id": v, "title": "X"}, headers=H).json()["engagement_id"]
    c.put(f"/api/v2/engagements/{e}/criticality-inputs", json={"customer_impact":5,"downtime_tolerance":5,"alternative_availability":5,"substitution_complexity":5}, headers=H)
    c.post("/api/v2/critical-vendors/analyse", json={"vendor_id": v}, headers=H)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    for k in sc["kpis"]: c.put(f"/api/v2/performance/kpi/{k['id']}", json={"score": 4}, headers=H)
    c.post(f"/api/v2/performance/scorecards/{sc['scorecard_id']}/publish", json={}, headers=H)
    # force several refreshes via 360 views
    for _ in range(3): c.get(f"/api/v2/vendor360/{v}", headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert attrs["risk_profile"]["performance_score"] is not None, "perf rollup blanked by later refresh"

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p == len(tests) else 1)
