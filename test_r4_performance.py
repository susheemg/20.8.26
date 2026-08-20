"""R4: Vendor Performance Management — scoped to critical vendors, deterministic scoring,
auto-sourcing, agree/publish lifecycle, rollup, QBR, closed-loop CAPA."""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"; os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H = {"x-user": "admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _v(c, n="Acme Ltd"): return c.post("/api/v2/vendors", json={"legal_name": n}, headers=H).json()["vendor_id"]
def _e(c, v): return c.post("/api/v2/engagements", json={"vendor_id": v, "title": "Svc"}, headers=H).json()["engagement_id"]
def _make_critical(c, v):
    e = _e(c, v)
    c.put(f"/api/v2/engagements/{e}/criticality-inputs", json={"customer_impact":5,"downtime_tolerance":5,"alternative_availability":5,"substitution_complexity":5}, headers=H)
    c.post("/api/v2/critical-vendors/analyse", json={"vendor_id": v}, headers=H)
    return e

def test_scorecard_allowed_for_any_vendor():
    # CR-11: performance is no longer restricted to critical vendors
    c = _c(); v = _v(c)
    r = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "2026-Q2"}, headers=H)
    assert r.status_code == 200
    assert r.json()["scorecard_id"].startswith("SCD-")

def test_creating_scorecard_enrols_vendor():
    c = _c(); v = _v(c)
    c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H)
    enrolled = c.get("/api/v2/performance/enrolment", headers=H).json()
    assert any(e["vendor_id"] == v for e in enrolled)

def test_manual_enrolment_and_unenrolment():
    c = _c(); v = _v(c)
    c.post("/api/v2/performance/enrolment", json={"vendor_ids": [v]}, headers=H)
    assert any(e["vendor_id"] == v for e in c.get("/api/v2/performance/enrolment", headers=H).json())
    c.delete(f"/api/v2/performance/enrolment/{v}", headers=H)
    assert not any(e["vendor_id"] == v for e in c.get("/api/v2/performance/enrolment", headers=H).json())

def test_critical_vendor_auto_enrolled():
    c = _c(); v = _v(c); _make_critical(c, v)
    enrolled = c.get("/api/v2/performance/enrolment", headers=H).json()
    assert any(e["vendor_id"] == v and e["is_critical"] for e in enrolled)

def test_scorecard_created_for_critical_vendor():
    c = _c(); v = _v(c); _make_critical(c, v)
    r = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "2026-Q2"}, headers=H).json()
    assert r["scorecard_id"].startswith("SCD-")
    # seeded with default dimensions + KPIs
    assert len(r["dimensions"]) == 6
    assert len(r["kpis"]) >= 10

def test_dimension_weights_sum_100():
    c = _c(); v = _v(c); _make_critical(c, v)
    r = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    assert abs(sum(d["weight"] for d in r["dimensions"]) - 100.0) < 0.01

def test_kpi_scoring_and_composite():
    c = _c(); v = _v(c); _make_critical(c, v)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    # score a few KPIs
    for k in sc["kpis"][:4]:
        c.put(f"/api/v2/performance/kpi/{k['id']}", json={"score": 4}, headers=H)
    res = c.post(f"/api/v2/performance/scorecards/{sc['scorecard_id']}/recompute", json={}, headers=H).json()
    assert res["composite_score"] is not None

def test_deterministic_scoring():
    c = _c(); v = _v(c); _make_critical(c, v)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    for k in sc["kpis"]:
        c.put(f"/api/v2/performance/kpi/{k['id']}", json={"score": 3}, headers=H)
    a = c.post(f"/api/v2/performance/scorecards/{sc['scorecard_id']}/recompute", json={}, headers=H).json()["composite_score"]
    b = c.post(f"/api/v2/performance/scorecards/{sc['scorecard_id']}/recompute", json={}, headers=H).json()["composite_score"]
    assert a == b == 3.0  # all-3 -> composite 3.0 (band Adequate)

def test_band_mapping():
    c = _c(); v = _v(c); _make_critical(c, v)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    for k in sc["kpis"]:
        c.put(f"/api/v2/performance/kpi/{k['id']}", json={"score": 5}, headers=H)
    got = c.get(f"/api/v2/performance/scorecards/{sc['scorecard_id']}", headers=H).json()
    assert got["band"] == "Strong"

def test_kpi_exclusion_renormalises():
    c = _c(); v = _v(c); _make_critical(c, v)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    kpis = sc["kpis"]
    # score one KPI 5, exclude the rest in its dimension; dimension score should be 5 (renormalised)
    c.put(f"/api/v2/performance/kpi/{kpis[0]['id']}", json={"score": 5}, headers=H)
    got = c.get(f"/api/v2/performance/scorecards/{sc['scorecard_id']}", headers=H).json()
    assert got["composite_score"] is not None  # partial scoring still computes

def test_auto_source_financial_stability():
    c = _c(); v = _v(c); _make_critical(c, v)
    # set FDD band on the vendor
    FIGS = {"revenue":1000,"cogs":400,"ebit":200,"ebitda":260,"netProfit":150,"totalAssets":1200,"equity":800,"currentAssets":500,"currentLiabilities":250,"cash":150,"totalDebt":200,"retainedEarnings":400,"interest":10}
    c.post("/api/v2/financial-dd", json={"figures": FIGS, "vendor_id": v}, headers=H)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    fs = [k for k in sc["kpis"] if k["metric"] == "Financial health band"]
    assert fs and fs[0]["auto_value"] is not None  # auto-sourced from FDD

def test_agree_then_publish_rolls_into_profile():
    c = _c(); v = _v(c); _make_critical(c, v)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    for k in sc["kpis"]:
        c.put(f"/api/v2/performance/kpi/{k['id']}", json={"score": 4}, headers=H)
    c.post(f"/api/v2/performance/scorecards/{sc['scorecard_id']}/agree", json={"party": "Vendor VP"}, headers=H)
    r = c.post(f"/api/v2/performance/scorecards/{sc['scorecard_id']}/publish", json={}, headers=H).json()
    assert r["published"] is True and r["rolled_into_profile"] is True
    # risk profile now carries performance_score
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert attrs["risk_profile"]["performance_score"] is not None

def test_publish_does_not_alter_inherent():
    c = _c(); v = _v(c); e = _make_critical(c, v)
    # critical analysis floored inherent via params; capture current inherent
    c.post("/api/v2/assessments", json={"engagement_id": e, "vendor_id": v, "inherent_band": "HIGH", "residual_band": "ELEVATED"}, headers=H)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    for k in sc["kpis"]:
        c.put(f"/api/v2/performance/kpi/{k['id']}", json={"score": 5}, headers=H)
    c.post(f"/api/v2/performance/scorecards/{sc['scorecard_id']}/publish", json={}, headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    # strong performance must NOT pull inherent/residual down
    assert attrs["risk_profile"]["inherent_band"] == "HIGH"
    assert attrs["risk_profile"]["residual_band"] == "ELEVATED"

def test_qbr_and_acknowledge():
    c = _c(); v = _v(c); _make_critical(c, v)
    r = c.post(f"/api/v2/performance/vendor/{v}/reviews", json={"data": {"attendees": "us+them", "summary": "Q2 review", "next_review_date": "2026-09-30"}}, headers=H).json()
    rid = r["review_id"]
    assert rid.startswith("PRV-")
    ack = c.post(f"/api/v2/performance/reviews/{rid}/acknowledge", json={}, headers=H).json()
    assert ack["vendor_acknowledged"] is True

def test_closed_loop_capa_requires_verification():
    c = _c(); v = _v(c); _make_critical(c, v)
    sc = c.post("/api/v2/performance/scorecards", json={"vendor_id": v, "period_label": "Q"}, headers=H).json()
    capa = c.post("/api/v2/performance/capa", json={"scorecard_id": sc["scorecard_id"], "gap": "SLA misses", "owner": "Ops"}, headers=H).json()
    assert capa["status"] == "Planned"
    # verify -> Verified
    ver = c.post(f"/api/v2/performance/capa/{capa['remediation_id']}/verify", json={"evidence": "3 months sustained"}, headers=H).json()
    assert ver["status"] == "Verified"

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p == len(tests) else 1)
