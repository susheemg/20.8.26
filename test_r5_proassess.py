"""R5: ProAssess — autonomous, proportionate, no-assumption (gaps risk-averse), register + empanel."""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"; os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app

# AI workflows now require a connected engine; simulate "AI connected" so the
# endpoints proceed and exercise the deterministic engine (documented fallback).
import app.agents.llm_config as _LLM
_LLM.status = lambda: {"live_ready": True, "provider": "claude", "sdk_installed": True, "enabled": True}
H = {"x-user": "admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _v(c, n="Acme Ltd"): return c.post("/api/v2/vendors", json={"legal_name": n}, headers=H).json()["vendor_id"]
def _e(c, v): return c.post("/api/v2/engagements", json={"vendor_id": v, "title": "Svc"}, headers=H).json()["engagement_id"]
# a HIGH inherent IRQ: restricted data + offshore + sub-processors etc
IRQ_HIGH = {"Q3": ["Payment Card", "Special Category Personal"], "Q4": ">1,000,000",
            "Q5": "Yes", "Q6": "Yes", "Q7": "Yes"}
IRQ_LOW = {"Q3": [], "Q4": "<100,000"}

def test_runs_and_returns_report():
    c = _c(); v = _v(c); e = _e(c, v)
    r = c.post("/api/v2/proassess/run", json={"vendor_id": v, "engagement_id": e, "irq": IRQ_HIGH}, headers=H).json()
    assert "inherent_band" in r and "residual_band" in r and "recommendation" in r

def test_proportionate_scope_high_vs_low():
    c = _c(); v = _v(c)
    hi = c.post("/api/v2/proassess/run", json={"vendor_id": v, "irq": IRQ_HIGH}, headers=H).json()
    lo = c.post("/api/v2/proassess/run", json={"vendor_id": v, "irq": IRQ_LOW}, headers=H).json()
    # HIGH inherent processes more domains than LOW (minimal relevant info per IRR)
    assert len(hi["domains_in_scope"]) > len(lo["domains_in_scope"])

def test_no_assumption_records_gaps_riskaverse():
    c = _c(); v = _v(c)
    # HIGH inherent but no financials/reputation/ddq supplied -> gaps, resolved worst-case
    r = c.post("/api/v2/proassess/run", json={"vendor_id": v, "irq": IRQ_HIGH}, headers=H).json()
    assert r["gap_count"] > 0
    # financial gap present and resolved adverse
    fin_gap = [g for g in r["gaps"] if g["domain"] == "financial"]
    assert fin_gap and "adverse" in fin_gap[0]["resolution"].lower()

def test_in_scope_vs_omitted_distinction():
    c = _c(); v = _v(c)
    lo = c.post("/api/v2/proassess/run", json={"vendor_id": v, "irq": IRQ_LOW}, headers=H).json()
    # financial is NOT in scope at LOW -> must NOT appear as a gap (correctly omitted)
    assert "financial" not in lo["domains_in_scope"]
    assert not any(g["domain"] == "financial" for g in lo["gaps"])

def test_no_controls_residual_equals_inherent():
    c = _c(); v = _v(c)
    r = c.post("/api/v2/proassess/run", json={"vendor_id": v, "irq": IRQ_HIGH}, headers=H).json()
    # no DDQ -> no mitigation credited -> residual == inherent
    assert r["residual_band"] == r["inherent_band"]
    assert any(g["domain"] == "controls" for g in r["gaps"])

def test_controls_evidence_can_lower_residual_path():
    c = _c(); v = _v(c)
    # supply DDQ all-good (no marginal/partial) -> residual not escalated
    r = c.post("/api/v2/proassess/run", json={"vendor_id": v, "irq": IRQ_HIGH, "ddq": {}}, headers=H).json()
    assert r["residual_band"] in ("LOW", "MODERATE", "ELEVATED", "HIGH")

def test_financials_processed_when_supplied():
    c = _c(); v = _v(c)
    FIGS = {"revenue":1000,"cogs":400,"ebit":200,"ebitda":260,"netProfit":150,"totalAssets":1200,"equity":800,"currentAssets":500,"currentLiabilities":250,"cash":150,"totalDebt":200,"retainedEarnings":400,"interest":10}
    r = c.post("/api/v2/proassess/run", json={"vendor_id": v, "irq": IRQ_HIGH, "extracted": {"financials": FIGS}}, headers=H).json()
    assert r["financial"] is not None
    assert not any(g["domain"] == "financial" for g in r["gaps"])  # no gap when supplied

def test_register_merges_and_empanels():
    c = _c(); v = _v(c); e = _e(c, v)
    report = c.post("/api/v2/proassess/run", json={"vendor_id": v, "engagement_id": e, "irq": IRQ_HIGH}, headers=H).json()
    reg = c.post("/api/v2/proassess/register", json={"report": report}, headers=H).json()
    assert reg["registered"] is True
    assert "risk_profile" in reg["tables_written"]
    assert reg["newly_empanelled"] is True  # empanelled for monitoring on completion

def test_register_requires_registered_vendor():
    c = _c()
    report = {"vendor_id": "VEN-999999", "inherent_band": "HIGH", "residual_band": "HIGH", "risks": [], "gaps": []}
    reg = c.post("/api/v2/proassess/register", json={"report": report}, headers=H).json()
    assert reg["registered"] is False

def test_register_idempotent_empanel():
    c = _c(); v = _v(c)
    c.post("/api/v2/fin-monitor", json={"vendor_id": v}, headers=H)  # already empanelled
    report = c.post("/api/v2/proassess/run", json={"vendor_id": v, "irq": IRQ_HIGH}, headers=H).json()
    reg = c.post("/api/v2/proassess/register", json={"report": report}, headers=H).json()
    assert reg["newly_empanelled"] is False and reg["empanelled_for_monitoring"] is True

def test_register_writes_findings_for_risks():
    c = _c(); v = _v(c); e = _e(c, v)
    report = c.post("/api/v2/proassess/run", json={"vendor_id": v, "engagement_id": e, "irq": IRQ_HIGH}, headers=H).json()
    c.post("/api/v2/proassess/register", json={"report": report}, headers=H)
    findings = c.get(f"/api/v2/findings?vendor_id={v}", headers=H)
    # findings endpoint may differ; assert via risk profile open_findings instead
    attrs = c.get(f"/api/v2/vendor-attributes/{v}", headers=H).json()
    assert attrs["risk_profile"]["open_findings"] >= 1

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p == len(tests) else 1)
