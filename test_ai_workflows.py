import os, sys, json
os.environ["BRO_TRUST_HEADER"] = "1"
for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BRO_LLM_KEY", "BRO_LLM_PROVIDER"]:
    os.environ.pop(k, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from app.bro_app import create_app
import app.agents.llm_config as LLM

H = {"x-user": "admin"}


def ok(cond, name):
    print(("PASS" if cond else "FAIL") + " - " + name)


# ---- AI OFF: workflows hold, do not proceed ----
LLM.status = lambda: {"live_ready": False, "provider": None, "sdk_installed": False, "enabled": False}
c = TestClient(create_app("sqlite:///:memory:"))

sid = c.post("/api/v1/agent/sessions", headers=H, json={}).json()["session_id"]
r = c.post("/api/v1/agent/send", headers=H, json={"session_id": sid, "message": "Onboarding AWS."}).json()
ok(r.get("holding") is True and r.get("advanced") is False, "BRO Chat holds when AI off")
ok("not available" in r["produced"][0]["body"].lower(), "BRO Chat returns holding statement")

pr = c.post("/api/v2/proassess/run", headers=H, json={"vendor_id": "VEN-1"}).json()
ok(pr.get("holding") is True, "ProAssess run holds when AI off")
pa = c.post("/api/v2/proassess/autonomous", headers=H, json={"new_vendor_name": "X"}).json()
ok(pa.get("holding") is True, "ProAssess autonomous holds when AI off")
fd = c.post("/api/v2/research/fdd", headers=H, json={"company": "Acme"}).json()
rp = c.post("/api/v2/research/reputation", headers=H, json={"company": "Acme"}).json()
ok(fd.get("holding") is True and rp.get("holding") is True, "FDD + Reputation hold when AI off")

# ---- Methodology library (admin) ----
add = c.post("/api/v2/methodology/docs", headers=H,
             json={"title": "TPRM Methodology", "content_text": "Stage 1 classify. Stage 2 score."}).json()
ok(add.get("doc_id", "").startswith("MTH-"), "methodology doc created")
lst = c.get("/api/v2/methodology/docs", headers=H).json()
ok(lst["has_methodology"] is True and len(lst["docs"]) == 1, "methodology listed + active")
did = add["doc_id"]
c.post(f"/api/v2/methodology/docs/{did}/active", headers=H, json={"active": False})
lst2 = c.get("/api/v2/methodology/docs", headers=H).json()
ok(lst2["has_methodology"] is False, "deactivating clears active methodology")
ok(c.delete(f"/api/v2/methodology/docs/{did}", headers=H).json().get("deleted") is True, "methodology deleted")
# auth gate
ok(c.get("/api/v2/methodology/docs").status_code in (401, 403), "methodology endpoints are auth-gated")

# methodology_directive: best practice when none, doc text when present
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.features.assessment import methodology as M
e = create_engine("sqlite:///:memory:")
from app.features.domain.models_db import Base
Base.metadata.create_all(e)
s = Session(e)
ok("industry best practice" in M.methodology_directive(s).lower(), "best-practice directive when no doc")
M.add_doc(s, title="M", content_text="STRICT-RULES-XYZ"); s.flush()
ok("STRICT-RULES-XYZ" in M.methodology_directive(s), "methodology text injected when present")

# ---- AI ON (mocked): ProAssess is AI-managed; FDD files report ----
LLM.status = lambda: {"live_ready": True, "provider": "claude", "sdk_installed": True, "enabled": True}
AI = json.dumps({"irq": {"service": "hosting", "data": ["Payment Card"], "criticality": "Mission-critical"},
                 "inherent_band": "HIGH", "domains": {"infosec": 4, "privacy": 4},
                 "residual_band": "ELEVATED",
                 "risks": [{"domain": "infosec", "severity": "High", "note": "card data"}],
                 "gaps": [{"domain": "resilience", "issue": "no BCP", "resolution": "worst-case"}],
                 "recommendation": "ESCALATE", "decision": "ESCALATE", "rationale": "card + critical"})
LLM.complete = lambda system, user, domain="general", web_search=False, **kw: AI
c2 = TestClient(create_app("sqlite:///:memory:"))
ar = c2.post("/api/v2/proassess/autonomous", headers=H,
             json={"new_vendor_name": "Acme Cloud Ltd", "free_text": "host card data, mission critical",
                   "create_records": True}).json()
ok(ar.get("engine") == "ai", "ProAssess is AI-managed when AI on")
ok(ar.get("inherent_band") == "HIGH" and ar.get("residual_band") == "ELEVATED", "AI assessment bands carried through")
ok(ar.get("assessment_id"), "AI assessment filed as record")
ok(any("AI engine" in n for n in ar.get("notes", [])), "notes record AI-managed assessment")

REP = json.dumps({"matched": True, "available": True, "summary": "ok",
                  "financial_health_band": "Strong", "adverse_media": True})
LLM.complete = lambda system, user, domain="general", web_search=False, **kw: REP
v = c2.post("/api/v2/vendors", headers=H, json={"legal_name": "Acme Two"}).json()
vid = v.get("vendor_id") or v.get("id")
fd2 = c2.post("/api/v2/research/fdd", headers=H, json={"vendor_id": vid}).json()
ok(fd2.get("available") is True and fd2.get("filed_report"), "FDD files a report when AI on")
rp2 = c2.post("/api/v2/research/reputation", headers=H, json={"vendor_id": vid}).json()
ok(rp2.get("available") is True and "reputation_signal" in (rp2.get("indicators_updated") or []),
   "Reputation updates indicators when AI on")
