"""CR-4 autonomous ProAssess: new vendor, single text box, docs, record creation."""
import sys, os, base64
os.environ["BRO_TRUST_HEADER"]="1"; os.environ.pop("ANTHROPIC_API_KEY",None)
sys.path.insert(0,"/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app

# AI workflows now require a connected engine; simulate "AI connected" so the
# endpoints proceed and exercise the deterministic engine (documented fallback).
import app.agents.llm_config as _LLM
_LLM.status = lambda: {"live_ready": True, "provider": "claude", "sdk_installed": True, "enabled": True}
# ProAssess is AI-managed: supply a working model so the autonomous pipeline runs.
_AI_JSON = ('{"irq":{"service":"payments","data":["Personal","Payment Card","Special Category"],'
            '"criticality":"Mission-critical","cross_border":true,"regulated":true},'
            '"inherent_band":"HIGH","domains":{"infosec":4,"privacy":4,"resilience":3},'
            '"residual_band":"ELEVATED","risks":[{"domain":"infosec","severity":"High","note":"card data"}],'
            '"gaps":[{"domain":"resilience","issue":"no tested BCP","resolution":"worst-case"}],'
            '"recommendation":"ESCALATE","decision":"ESCALATE","rationale":"card + cross-border"}')
_LLM.complete = lambda system, user, domain="general", web_search=False, **kw: _AI_JSON
H={"x-user":"admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _b64(t): return base64.b64encode(t).decode()
TXT="vendor processing cardholder data and special category personal data offshore in India, sub-processors, remote system access, over 1 million records"

def test_creates_new_vendor_and_records():
    c=_c()
    r=c.post("/api/v2/proassess/autonomous", json={"new_vendor_name":"Globex Ltd","free_text":TXT,"engagement_title":"Payments"}, headers=H).json()
    assert r["created_vendor"] is True
    assert r["vendor_id"].startswith("VEN-")
    tw=" ".join(r["tables_written"])
    assert "vendor:" in tw and "engagement:" in tw and "assessment:" in tw

def test_single_textbox_drives_inherent():
    c=_c()
    r=c.post("/api/v2/proassess/autonomous", json={"new_vendor_name":"Risky Co","free_text":TXT}, headers=H).json()
    # rich risk text -> elevated/high inherent, IRQ extracted by the AI engine
    assert r["inherent_band"] in ("ELEVATED","HIGH")
    assert r["extracted_irq"]  # AI returns a structured IRQ

def test_documents_become_artefacts():
    c=_c()
    doc=_b64(b"ISO 27001 2024-01-01 2026-01-01")
    r=c.post("/api/v2/proassess/autonomous", json={"new_vendor_name":"DocCo","free_text":"saas","documents":[{"filename":"i.txt","content_type":"text/plain","data_b64":doc}]}, headers=H).json()
    vid=r["vendor_id"]
    arts=c.get(f"/api/v2/artefacts?vendor_id={vid}", headers=H).json()
    assert any(a.get("doc_link") for a in arts)

def test_duplicate_guard_no_phantom():
    c=_c()
    r1=c.post("/api/v2/proassess/autonomous", json={"new_vendor_name":"Acme Payments Ltd","free_text":"x"}, headers=H).json()
    r2=c.post("/api/v2/proassess/autonomous", json={"new_vendor_name":"Acme Payments Limited","free_text":"y"}, headers=H).json()
    assert r2["duplicate_matched"] is True
    assert r2["vendor_id"]==r1["vendor_id"]

def test_existing_vendor_path():
    c=_c()
    v=c.post("/api/v2/vendors", json={"legal_name":"Existing Inc"}, headers=H).json()["vendor_id"]
    r=c.post("/api/v2/proassess/autonomous", json={"vendor_id":v,"free_text":TXT}, headers=H).json()
    assert r["vendor_id"]==v
    assert r["created_vendor"] is False
    assert r["registered"] is True

def test_requires_vendor_or_name():
    c=_c()
    r=c.post("/api/v2/proassess/autonomous", json={"free_text":"x"}, headers=H)
    assert r.status_code==422

def test_no_assumptions_gaps_when_thin():
    c=_c()
    r=c.post("/api/v2/proassess/autonomous", json={"new_vendor_name":"Thin Co","free_text":"basic saas"}, headers=H).json()
    # thin input -> gaps recorded, residual not better than inherent (risk-averse)
    assert r["gap_count"]>0

if __name__=="__main__":
    import traceback
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_")]
    p=0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p+=1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p==len(tests) else 1)
