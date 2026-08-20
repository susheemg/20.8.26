"""R2: first-class contract entity with type-driven linking (MSA->vendor, Contract/PO->engagement)."""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"; os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H = {"x-user": "admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _v(c, n="Acme Ltd"): return c.post("/api/v2/vendors", json={"legal_name": n}, headers=H).json()["vendor_id"]
def _e(c, v): return c.post("/api/v2/engagements", json={"vendor_id": v, "title": "Svc"}, headers=H).json()["engagement_id"]

def test_msa_links_to_vendor():
    c = _c(); v = _v(c)
    r = c.post("/api/v2/contracts", json={"contract_type": "MSA", "vendor_id": v}, headers=H).json()
    assert r["primary_link"] == "vendor" and r["vendor_id"] == v
    assert r["engagement_id"] is None
    assert r["contract_id"].startswith("CON-")

def test_contract_links_to_engagement():
    c = _c(); v = _v(c); e = _e(c, v)
    r = c.post("/api/v2/contracts", json={"contract_type": "Contract", "engagement_id": e}, headers=H).json()
    assert r["primary_link"] == "engagement" and r["engagement_id"] == e
    # vendor resolved from engagement
    assert r["vendor_id"] == v

def test_po_links_to_engagement():
    c = _c(); v = _v(c); e = _e(c, v)
    r = c.post("/api/v2/contracts", json={"contract_type": "PO", "engagement_id": e}, headers=H).json()
    assert r["primary_link"] == "engagement"

def test_calloff_references_parent_msa():
    c = _c(); v = _v(c); e = _e(c, v)
    msa = c.post("/api/v2/contracts", json={"contract_type": "MSA", "vendor_id": v}, headers=H).json()
    co = c.post("/api/v2/contracts", json={"contract_type": "Contract", "engagement_id": e, "parent_msa": msa["contract_id"]}, headers=H).json()
    contracts = c.get(f"/api/v2/contracts?engagement_id={e}", headers=H).json()
    assert contracts[0]["parent_msa"] == msa["contract_id"]

def test_list_by_vendor_and_engagement():
    c = _c(); v = _v(c); e = _e(c, v)
    c.post("/api/v2/contracts", json={"contract_type": "MSA", "vendor_id": v}, headers=H)
    c.post("/api/v2/contracts", json={"contract_type": "Contract", "engagement_id": e}, headers=H)
    by_v = c.get(f"/api/v2/contracts?vendor_id={v}", headers=H).json()
    by_e = c.get(f"/api/v2/contracts?engagement_id={e}", headers=H).json()
    assert len(by_v) >= 1 and len(by_e) == 1

def test_contract_requires_a_link():
    c = _c()
    r = c.post("/api/v2/contracts", json={"contract_type": "Contract"}, headers=H)
    assert r.status_code == 400

def test_update_contract():
    c = _c(); v = _v(c)
    cid = c.post("/api/v2/contracts", json={"contract_type": "MSA", "vendor_id": v}, headers=H).json()["contract_id"]
    r = c.put(f"/api/v2/contracts/{cid}", json={"data": {"status": "active", "value": 500000}}, headers=H).json()
    assert r["status"] == "active"

def test_engagement_sync_creates_contract():
    c = _c(); v = _v(c); e = _e(c, v)
    c.put(f"/api/v2/engagement-register/{e}", json={"data": {"contract_reference": "MSA-2026-001", "agreement_type": "MSA"}}, headers=H)
    r = c.post(f"/api/v2/engagement-register/{e}/sync-contract", json={}, headers=H).json()
    assert r["synced"] is True and r["contract_id"].startswith("CON-")

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p == len(tests) else 1)
