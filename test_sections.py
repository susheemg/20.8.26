"""Tests for FDD peers/research, Financial Monitoring, entity resolution, section entity-linking."""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
from app.features.intelligence import financial as FIN
H = {"x-user": "admin"}

def _c():
    return TestClient(create_app("sqlite:///:memory:"))

def _vendor(c, name="Acme Ltd"):
    return c.post("/api/v2/vendors", json={"legal_name": name}, headers=H).json()["vendor_id"]

FIGS = {"revenue":1000,"cogs":400,"ebit":200,"ebitda":260,"netProfit":150,"totalAssets":1200,
        "equity":800,"currentAssets":500,"currentLiabilities":250,"inventory":100,"cash":150,
        "totalDebt":200,"receivables":120,"payables":80,"retainedEarnings":400,"interest":10}

def test_sectors_list():
    c = _c()
    secs = c.get("/api/v2/sectors", headers=H).json()
    assert any(s["id"] == "tech" for s in secs) and len(secs) == 7

def test_peer_benchmark_engine():
    rows = FIN.peer_benchmark(FIN.assess_financials(FIGS)["ratios"], "tech")
    assert len(rows) == 7
    assert all("verdict" in r for r in rows)

def test_peer_benchmark_endpoint():
    c = _c()
    r = c.post("/api/v2/financial-dd/peers", json={"figures": FIGS, "sector": "tech"}, headers=H).json()
    assert r["sector"] == "tech" and len(r["peers"]) == 7

def test_research_without_key_returns_manual():
    c = _c()
    r = c.post("/api/v2/financial-dd/research", json={"company": "Acme Corp", "jurisdiction": "UK"}, headers=H).json()
    assert r["matched"] is False
    assert "manual" in r["limitations"].lower() or "ai key" in r["limitations"].lower()

def test_finmon_empanel_registered_vendor():
    c = _c(); v = _vendor(c, "Globex Ltd")
    r = c.post("/api/v2/fin-monitor", json={"vendor_id": v}, headers=H).json()
    assert r["vendor_id"] == v and r["entity_name"] == "Globex Ltd"

def test_finmon_empanel_other_freetext():
    c = _c()
    r = c.post("/api/v2/fin-monitor", json={"other_name": "Unregistered PLC"}, headers=H).json()
    assert r["vendor_id"] is None and r["entity_name"] == "Unregistered PLC"

def test_finmon_other_matches_existing_by_name():
    c = _c(); v = _vendor(c, "Initech Ltd")
    # typing a name that matches a registered vendor should link to it
    r = c.post("/api/v2/fin-monitor", json={"other_name": "Initech Ltd"}, headers=H).json()
    assert r["vendor_id"] == v

def test_finmon_sweep_offline():
    c = _c(); _vendor(c, "Acme Ltd")
    c.post("/api/v2/fin-monitor", json={"other_name": "Acme Ltd"}, headers=H)
    r = c.post("/api/v2/fin-monitor/sweep", json={}, headers=H).json()
    assert r["swept"] == 1 and r["ai_enabled"] is False
    lst = c.get("/api/v2/fin-monitor", headers=H).json()
    assert lst[0]["last_signal"] == "ok" and lst[0]["last_swept"]

def test_finmon_remove():
    c = _c()
    mid = c.post("/api/v2/fin-monitor", json={"other_name": "Temp"}, headers=H).json()["id"]
    assert c.delete(f"/api/v2/fin-monitor/{mid}", headers=H).json()["deleted"] is True
    assert len(c.get("/api/v2/fin-monitor", headers=H).json()) == 0

def test_reputation_links_to_vendor():
    c = _c(); v = _vendor(c, "Brandco Ltd")
    r = c.post("/api/v2/reputation", json={"vendor_id": v, "events": []}, headers=H).json()
    assert r["entity"]["vendor_id"] == v and r["entity"]["registered"] is True

def test_reputation_other_entity():
    c = _c()
    r = c.post("/api/v2/reputation", json={"other_name": "Unknown Co", "events": []}, headers=H).json()
    assert r["entity"]["registered"] is False and r["entity"]["vendor_name"] == "Unknown Co"

def test_contract_terms_links_to_vendor():
    c = _c(); v = _vendor(c, "Legalco Ltd")
    r = c.post("/api/v2/contracts/terms", json={"inherent_band": "HIGH", "vendor_id": v}, headers=H).json()
    assert r["entity"]["vendor_id"] == v and r["count"] > 5

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
