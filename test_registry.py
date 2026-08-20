"""
Tests for the exhaustive registry (v2) + Financial DD engine.
"""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")

from fastapi.testclient import TestClient
from app.bro_app import create_app
from app.features.intelligence import financial as FIN
from app.features.domain import master_data as MD

H = {"x-user": "admin"}


def _c():
    return TestClient(create_app("sqlite:///:memory:"))


def _vendor(c, name="Acme Payments Ltd", **kw):
    body = {"legal_name": name}; body.update(kw)
    return c.post("/api/v2/vendors", json=body, headers=H).json()


# ---- ID scheme ----
def test_id_format():
    assert MD.format_id("vendor", 123) == "VEN-000123"
    assert MD.format_id("group", 45) == "GRP-00045"
    assert MD.format_id("engagement", 7) == "ENG-000007"
    assert MD.format_id("fourth_party", 1) == "F4P-000001"


# ---- masters ----
def test_masters_seeded():
    c = _c()
    inds = c.get("/api/v2/industries", headers=H).json()
    assert len(inds) >= 30
    assert any(i["industry_id"] == "Business Services (incl. Software & IT)" for i in inds)
    mgs = c.get("/api/v2/material-groups", headers=H).json()
    assert len(mgs) >= 30
    assert all("material_group_id" in m for m in mgs)


# ---- vendor + group + auto IDs ----
def test_vendor_auto_id_and_group():
    c = _c()
    r = _vendor(c)
    assert r["vendor_id"].startswith("VEN-")
    assert r["group_id"].startswith("GRP-")

def test_same_group_shared_across_vendors():
    c = _c()
    # two vendors under same parent should share a group
    a = _vendor(c, name="Globex UK Ltd", parent_company="Globex")
    b = _vendor(c, name="Globex US Inc", parent_company="Globex")
    assert a["group_id"] == b["group_id"]  # AI-proposed shared group

def test_group_override():
    c = _c()
    a = _vendor(c, name="Initech Ltd")
    b = _vendor(c, name="Other Co")
    r = c.post(f"/api/v2/vendors/{a['vendor_id']}/group",
               json={"group_id": b["group_id"]}, headers=H)
    assert r.json()["group_id"] == b["group_id"]

def test_vendor_industries_tagged():
    c = _c()
    r = _vendor(c, industries=["Retail Trade", "Business Services (incl. Software & IT)"])
    detail = c.get(f"/api/v2/vendors/{r['vendor_id']}", headers=H).json()
    assert "Retail Trade" in detail["industries"]
    assert len(detail["industries"]) == 2

def test_multiple_contacts_primary_and_backup():
    c = _c()
    v = _vendor(c)["vendor_id"]
    c.post("/api/v2/contacts", json={"owner_type": "vendor", "owner_id": v,
            "name": "Alice AM", "is_primary": True, "email": "alice@x.com",
            "phone_country_code": "+44", "phone_number": "7700900000",
            "designation": "Account Manager", "country": "UK"}, headers=H)
    c.post("/api/v2/contacts", json={"owner_type": "vendor", "owner_id": v,
            "name": "Bob Backup", "is_primary": False, "email": "bob@x.com"}, headers=H)
    detail = c.get(f"/api/v2/vendors/{v}", headers=H).json()
    assert len(detail["contacts"]) == 2
    primaries = [k for k in detail["contacts"] if k["is_primary"]]
    assert len(primaries) == 1 and primaries[0]["name"] == "Alice AM"


# ---- engagement ----
def test_engagement_auto_id_and_list():
    c = _c()
    v = _vendor(c)["vendor_id"]
    e = c.post("/api/v2/engagements", json={"vendor_id": v, "title": "Card processing",
               "material_group_id": "Financial & Insurance Services"}, headers=H).json()
    assert e["engagement_id"].startswith("ENG-")
    lst = c.get(f"/api/v2/engagements?vendor_id={v}", headers=H).json()
    assert len(lst) == 1 and lst[0]["title"] == "Card processing"


# ---- assessment: assessor on HIGH, sign-off, approve-lock, recall ----
def test_high_inherent_assigns_assessor_and_locks_on_approve():
    c = _c()
    v = _vendor(c)["vendor_id"]
    e = c.post("/api/v2/engagements", json={"vendor_id": v, "title": "Critical svc"}, headers=H).json()["engagement_id"]
    a = c.post("/api/v2/assessments", json={"engagement_id": e, "vendor_id": v,
               "inherent_band": "HIGH"}, headers=H).json()
    assert a["assessor_user"] is not None         # auto-assigned
    aid = a["assessment_id"]
    # approve without sign-off must fail
    r = c.post(f"/api/v2/assessments/{aid}/approve", headers=H)
    assert r.status_code == 400
    # sign off, then approve -> locked
    c.post(f"/api/v2/assessments/{aid}/signoff", headers=H)
    r2 = c.post(f"/api/v2/assessments/{aid}/approve", headers=H)
    assert r2.json()["locked"] is True
    # recall now blocked (hard-locked)
    r3 = c.post(f"/api/v2/assessments/{aid}/recall", headers=H)
    assert r3.status_code == 400

def test_low_inherent_no_assessor_and_recall_ok():
    c = _c()
    v = _vendor(c)["vendor_id"]
    e = c.post("/api/v2/engagements", json={"vendor_id": v, "title": "Low svc"}, headers=H).json()["engagement_id"]
    a = c.post("/api/v2/assessments", json={"engagement_id": e, "inherent_band": "LOW"}, headers=H).json()
    assert a["assessor_user"] is None
    assert a["spoc_user"] == "admin"   # engagement owner = SPOC
    r = c.post(f"/api/v2/assessments/{a['assessment_id']}/recall", headers=H)
    assert r.json()["status"] == "Recalled"


# ---- findings + remediation + open-actions rollup ----
def test_findings_remediation_and_rollup():
    c = _c()
    v = _vendor(c)["vendor_id"]
    e = c.post("/api/v2/engagements", json={"vendor_id": v, "title": "Svc"}, headers=H).json()["engagement_id"]
    f = c.post("/api/v2/findings", json={"title": "No MFA", "severity": "Critical",
               "source": "AI", "engagement_id": e, "vendor_id": v}, headers=H).json()
    assert f["finding_id"].startswith("FND-")
    # open actions rolled up on the engagement
    eng = [x for x in c.get("/api/v2/engagements", headers=H).json() if x["engagement_id"] == e][0]
    assert eng["open_actions"] == 1
    r = c.post("/api/v2/remediations", json={"finding_id": f["finding_id"],
               "plan": "Enforce MFA on all external access"}, headers=H).json()
    assert r["remediation_id"].startswith("RMD-")


# ---- fourth party concentration + vendor cross-link ----
def test_fourth_party_concentration():
    c = _c()
    vids = [_vendor(c, name=f"V{i}")["vendor_id"] for i in range(3)]
    fp = c.post("/api/v2/fourth-parties", json={"legal_name": "AWS",
                "service_provided": "Cloud hosting", "vendor_ids": vids}, headers=H).json()
    assert fp["concentration_flag"] is True   # >=3 vendors
    lst = c.get("/api/v2/fourth-parties", headers=H).json()
    assert lst[0]["supports_vendors"] and len(lst[0]["supports_vendors"]) == 3


# ---- artefacts + revalidation + issues ----
def test_artefact_status_and_revalidation_issue():
    import datetime as dt
    c = _c()
    v = _vendor(c)["vendor_id"]
    # expired > 30 days ago
    old = (dt.date.today() - dt.timedelta(days=45)).isoformat()
    art = c.post("/api/v2/artefacts", json={"vendor_id": v, "name": "ISO 27001",
                 "expiry_date": old}, headers=H).json()
    assert art["status"] == "Expired"
    res = c.post("/api/v2/artefacts/revalidate", headers=H).json()
    assert len(res["new_issues"]) >= 1
    issues = c.get("/api/v2/issues", headers=H).json()
    assert any(i["vendor_id"] == v and i["status"] == "Open" for i in issues)

def test_artefact_refresh_supersedes_and_closes_issue():
    import datetime as dt
    c = _c()
    v = _vendor(c)["vendor_id"]
    old = (dt.date.today() - dt.timedelta(days=45)).isoformat()
    art = c.post("/api/v2/artefacts", json={"vendor_id": v, "name": "SOC 2",
                 "expiry_date": old}, headers=H).json()
    c.post("/api/v2/artefacts/revalidate", headers=H)   # raises issue
    future = (dt.date.today() + dt.timedelta(days=365)).isoformat()
    c.post("/api/v2/artefacts", json={"vendor_id": v, "name": "SOC 2",
           "expiry_date": future, "supersedes": art["artefact_id"], "received_via": "email"}, headers=H)
    issues = c.get("/api/v2/issues?status=Open", headers=H).json()
    assert not any(i["vendor_id"] == v for i in issues)   # auto-closed on refresh

def test_revalidation_7day_notice():
    import datetime as dt
    c = _c()
    v = _vendor(c)["vendor_id"]
    soon = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    c.post("/api/v2/artefacts", json={"vendor_id": v, "name": "Cert", "expiry_date": soon}, headers=H)
    res = c.post("/api/v2/artefacts/revalidate", headers=H).json()
    assert len(res["notify_7day"]) >= 1


# ---- financial DD engine ----
def test_financial_engine_strong_company():
    figs = {"revenue": 1000, "cogs": 400, "ebit": 250, "ebitda": 320, "netProfit": 180,
            "interest": 10, "currentAssets": 600, "currentLiabilities": 300, "inventory": 100,
            "cash": 200, "totalAssets": 1500, "totalDebt": 200, "equity": 1000,
            "receivables": 120, "payables": 80, "retainedEarnings": 600}
    out = FIN.assess_financials(figs, {})
    assert out["banding"] in ("Strong", "Adequate")
    assert out["altman"]["zone"] in ("safe", "grey")
    assert len(out["ratios"]) >= 17

def test_financial_engine_going_concern_caps_score():
    figs = {"revenue": 100, "cogs": 120, "ebit": -30, "ebitda": -10, "netProfit": -40,
            "interest": 20, "currentAssets": 50, "currentLiabilities": 200, "totalAssets": 300,
            "totalDebt": 250, "equity": -20, "retainedEarnings": -100}
    out = FIN.assess_financials(figs, {"goingConcern": True, "negativeEquity": True})
    assert out["overall"] is None or out["overall"] <= 44
    assert out["banding"] in ("Watch", "Distressed")

def test_financial_sara_checks_flag_inconsistency():
    figs = {"revenue": 100, "netProfit": 150, "totalAssets": 200, "equity": 50}  # NP>Rev
    out = FIN.assess_financials(figs, {})
    assert any("exceeds revenue" in chk["text"] for chk in out["sara_checks"])

def test_financial_dd_endpoint():
    c = _c()
    r = c.post("/api/v2/financial-dd", json={"figures": {"revenue": 1000, "cogs": 400,
               "ebit": 200, "ebitda": 260, "netProfit": 150, "totalAssets": 1200,
               "equity": 800, "currentAssets": 500, "currentLiabilities": 250,
               "retainedEarnings": 400}, "flags": {}}, headers=H)
    assert r.status_code == 200
    assert "banding" in r.json() and "pillars" in r.json()


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
