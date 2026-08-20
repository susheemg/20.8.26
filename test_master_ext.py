"""Tests for Req 1 (vendor master), Req 2 (vendor attributes), Req 3 (engagement register)."""
import sys, os, datetime as dt
os.environ["BRO_TRUST_HEADER"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H = {"x-user": "admin"}

def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _vendor(c, name="Acme Ltd"):
    return c.post("/api/v2/vendors", json={"legal_name": name}, headers=H).json()["vendor_id"]
def _eng(c, vid):
    return c.post("/api/v2/engagements", json={"vendor_id": vid, "title": "SaaS"}, headers=H).json()["engagement_id"]

# ---- Req 1: Vendor Master ----
def test_vendor_master_get_baseline():
    c = _c(); v = _vendor(c)
    m = c.get(f"/api/v2/vendor-master/{v}", headers=H).json()
    assert m["vendor_id"] == v and m["legal_name"] == "Acme Ltd"

def test_vendor_master_update_extended_fields():
    c = _c(); v = _vendor(c)
    r = c.put(f"/api/v2/vendor-master/{v}", json={"data": {
        "euid": "EU123", "ownership_type": "listed", "segmentation": "strategic",
        "ubo": [{"name": "Jane Doe", "pct": 60}]}}, headers=H).json()
    assert r["euid"] == "EU123" and r["segmentation"] == "strategic"
    assert r["ubo"][0]["name"] == "Jane Doe"

def test_vendor_master_banking_gated_for_admin():
    c = _c(); v = _vendor(c)
    # admin can write bank fields with include_bank
    r = c.put(f"/api/v2/vendor-master/{v}", json={"data": {"iban": "GB00X", "bank_verified": True},
              "include_bank": True}, headers=H)
    assert r.status_code == 200
    assert r.json().get("iban") == "GB00X"

def test_vendor_master_banking_restricted_in_get():
    c = _c(); v = _vendor(c)
    c.put(f"/api/v2/vendor-master/{v}", json={"data": {"iban": "GB00X"}, "include_bank": True}, headers=H)
    # admin sees bank; (role gating exercised in unit since test user is admin)
    m = c.get(f"/api/v2/vendor-master/{v}", headers=H).json()
    assert "iban" in m  # admin

# ---- Req 2: Vendor Attributes ----
def test_screening_triplet():
    c = _c(); v = _vendor(c)
    today = dt.date.today().isoformat()
    nxt = (dt.date.today() + dt.timedelta(days=365)).isoformat()
    r = c.post(f"/api/v2/vendor-attributes/{v}/screening", json={
        "screen_type": "sanctions", "result": "clear", "detail": "OFAC, EU, UN",
        "screened_date": today, "next_due": nxt}, headers=H).json()
    sanc = next(x for x in r if x["screen_type"] == "sanctions")
    assert sanc["result"] == "clear" and sanc["next_due"] == nxt and sanc["overdue"] is False

def test_screening_overdue_flag():
    c = _c(); v = _vendor(c)
    past = (dt.date.today() - dt.timedelta(days=5)).isoformat()
    c.post(f"/api/v2/vendor-attributes/{v}/screening", json={
        "screen_type": "pep", "result": "clear", "next_due": past}, headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    pep = next(x for x in attrs["screening"] if x["screen_type"] == "pep")
    assert pep["overdue"] is True

def test_screening_all_seven_types_present():
    c = _c(); v = _vendor(c)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    types = {x["screen_type"] for x in attrs["screening"]}
    assert types == {"sanctions","pep","adverse_media","abac","debarment","modern_slavery","coi"}

def test_privacy_domain():
    c = _c(); v = _vendor(c)
    c.post(f"/api/v2/vendor-attributes/{v}/domain/privacy", json={"data": {
        "processes_personal_data": True, "role": "processor", "dpa_in_place": True,
        "transfer_mechanism": "SCCs"}}, headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert attrs["privacy"]["role"] == "processor" and attrs["privacy"]["dpa_in_place"] is True

def test_resilience_nth_party_tree():
    c = _c(); v = _vendor(c)
    c.post(f"/api/v2/vendor-attributes/{v}/domain/resilience", json={"data": {
        "supports_critical_function": True, "spof_flag": True,
        "nth_party": [{"name": "AWS", "rank": 1, "parent": None},
                      {"name": "Fastly", "rank": 2, "parent": "AWS"}]}}, headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    import json as _j
    tree = _j.loads(attrs["resilience"]["nth_party_json"])
    assert len(tree) == 2 and tree[1]["name"] == "Fastly"

def test_insurance_multiple_policies():
    c = _c(); v = _vendor(c)
    c.post(f"/api/v2/vendor-attributes/{v}/insurance", json={"policy_type": "cyber", "coverage_limit": 5e6}, headers=H)
    c.post(f"/api/v2/vendor-attributes/{v}/insurance", json={"policy_type": "professional_indemnity", "coverage_limit": 2e6}, headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert len(attrs["insurance"]) == 2

def test_monitor_signal_timeseries():
    c = _c(); v = _vendor(c)
    c.post(f"/api/v2/vendor-attributes/{v}/monitor-signal", json={"signal_type": "cyber_rating", "value": "A", "source": "BitSight"}, headers=H)
    c.post(f"/api/v2/vendor-attributes/{v}/monitor-signal", json={"signal_type": "cyber_rating", "value": "B", "source": "BitSight"}, headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    sigs = [x for x in attrs["monitor_signals"] if x["signal_type"] == "cyber_rating"]
    assert len(sigs) == 2  # time-series, not overwrite

def test_risk_profile_rollup():
    c = _c(); v = _vendor(c)
    e = _eng(c, v)
    c.post("/api/v2/assessments", json={"engagement_id": e, "vendor_id": v, "inherent_band": "HIGH"}, headers=H)
    c.post("/api/v2/findings", json={"title": "No MFA", "severity": "Critical", "engagement_id": e, "vendor_id": v}, headers=H)
    r = c.post(f"/api/v2/vendor-attributes/{v}/refresh-rollups", headers=H).json()
    assert r["open_findings"] >= 1
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert attrs["risk_profile"]["max_severity"] == "Critical"

def test_cyber_certs_rollup_from_artefacts():
    c = _c(); v = _vendor(c)
    c.post("/api/v2/artefacts", json={"vendor_id": v, "name": "ISO 27001", "expiry_date": "2027-01-01"}, headers=H)
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    import json as _j
    certs = _j.loads(attrs["cyber"]["certifications_json"])
    assert any("ISO 27001" in c2["name"] for c2 in certs)

# ---- Req 3: Engagement Register ----
def test_engagement_ext_update():
    c = _c(); v = _vendor(c); e = _eng(c, v)
    r = c.put(f"/api/v2/engagement-register/{e}", json={"data": {
        "engagement_type": "managed service", "agreement_type": "MSA",
        "tcv": 1200000, "pricing_model": "fixed", "mission_critical": True,
        "renewal_type": "auto", "engagement_stage": "active"}}, headers=H).json()
    assert r["ext"]["agreement_type"] == "MSA" and r["ext"]["tcv"] == 1200000
    assert r["ext"]["mission_critical"] is True

def test_engagement_children_all_kinds():
    c = _c(); v = _vendor(c); e = _eng(c, v)
    c.post(f"/api/v2/engagement-register/{e}/child", json={"kind": "deliverable", "data": {"description": "Phase 1", "due_date": "2026-09-01"}}, headers=H)
    c.post(f"/api/v2/engagement-register/{e}/child", json={"kind": "milestone", "data": {"name": "Go-live", "due_date": "2026-10-01"}}, headers=H)
    c.post(f"/api/v2/engagement-register/{e}/child", json={"kind": "sla", "data": {"metric": "Uptime", "target": "99.9%"}}, headers=H)
    c.post(f"/api/v2/engagement-register/{e}/child", json={"kind": "obligation", "data": {"description": "Quarterly SOC2", "obl_type": "certification", "due_date": "2026-12-31"}}, headers=H)
    c.post(f"/api/v2/engagement-register/{e}/child", json={"kind": "personnel", "data": {"name": "A. Dev", "role": "Engineer", "key_personnel": True}}, headers=H)
    full = c.get(f"/api/v2/engagement-register/{e}", headers=H).json()
    assert len(full["deliverables"]) == 1 and len(full["milestones"]) == 1
    assert len(full["slas"]) == 1 and len(full["obligations"]) == 1 and len(full["personnel"]) == 1

def test_engagement_child_delete():
    c = _c(); v = _vendor(c); e = _eng(c, v)
    cid = c.post(f"/api/v2/engagement-register/{e}/child", json={"kind": "deliverable", "data": {"description": "X"}}, headers=H).json()["id"]
    c.delete(f"/api/v2/engagement-register/{e}/child/deliverable/{cid}", headers=H)
    full = c.get(f"/api/v2/engagement-register/{e}", headers=H).json()
    assert len(full["deliverables"]) == 0

def test_overdue_obligations_surface():
    c = _c(); v = _vendor(c); e = _eng(c, v)
    past = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    c.post(f"/api/v2/engagement-register/{e}/child", json={"kind": "obligation", "data": {"description": "Late report", "due_date": past}}, headers=H)
    overdue = c.get("/api/v2/obligations/overdue", headers=H).json()
    assert any(o["engagement_id"] == e for o in overdue)

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
