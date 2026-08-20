"""Viny — AI exit-plan drafting (deterministic core + endpoint contract)."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "MANUS_API_KEY",
          "NVIDIA_API_KEY", "BRO_LLM_PROVIDER"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app  # noqa: E402
from app.features.lifecycle.exit_planning import deterministic_draft  # noqa: E402

H = {"x-user": "admin"}
DB = "sqlite:////tmp/exd.db"


def _client():
    if os.path.exists("/tmp/exd.db"):
        os.remove("/tmp/exd.db")
    return TestClient(create_app(DB))


def test_deterministic_draft_critical_vendor():
    d = deterministic_draft({"vendor_name": "PayCo", "is_critical": True,
                             "services": ["Card processing"], "residual_band": "HIGH",
                             "dependencies": [{"service": "Payments", "tolerance": "2h",
                                               "max_downtime": "4h", "criticality": "critical"}],
                             "existing_alternatives": [], "contract_exit_clause": False,
                             "tier": "Tier 1", "hq_country": "GB", "vendor_id": "V1",
                             "engagement_count": 1})
    assert d["strategy_type"] == "multi_source"
    assert "stressed" in d["target_window"]
    assert "exit/assistance clause" in d["rationale"]      # missing clause flagged
    assert len(d["steps"]) == 6 and d["alternatives"]      # suggests alternatives when none exist
    assert "Payments" in d["impact_summary"]


def test_ai_draft_endpoint_returns_rules_engine_offline():
    c = _client()
    vid = c.post("/api/v2/vendors", headers=H,
                 json={"legal_name": "Drafty Ltd", "tier": "Tier 2"}).json()["vendor_id"]
    r = c.post(f"/api/v2/exit/plan/{vid}/ai-draft", headers=H)
    assert r.status_code == 200
    j = r.json()
    assert j["by"] == "Viny" and j["engine"] == "rules"     # no live key in sandbox
    assert j["draft"]["strategy_type"] and j["draft"]["steps"]
    assert j["context_used"]["vendor_name"] == "Drafty Ltd"


def test_draft_respects_existing_alternatives():
    c = _client()
    vid = c.post("/api/v2/vendors", headers=H,
                 json={"legal_name": "AltCo", "tier": "Tier 2"}).json()["vendor_id"]
    c.post(f"/api/v2/exit/plan/{vid}/child", headers=H,
           json={"kind": "alternative", "name": "BackupCo", "prequalified": True,
                 "lead_time_days": 30, "viability": 4})
    j = c.post(f"/api/v2/exit/plan/{vid}/ai-draft", headers=H).json()
    assert j["draft"]["strategy_type"] == "alternative_provider"
    assert j["context_used"]["existing_alternatives"] == ["BackupCo"]


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
