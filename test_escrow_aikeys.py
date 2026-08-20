"""Engagement escrow fields (round-trip through the register) and multi-provider
AI key management (Anthropic / OpenAI / Grok / Manus)."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app, make_session_factory, make_engine  # noqa: E402
from app.features.domain.registry_models import VendorRecord, EngagementRecord  # noqa: E402

H = {"x-user": "admin"}
DB = "sqlite:////tmp/escrow_ai_test.db"


def _app():
    p = "/tmp/escrow_ai_test.db"
    if os.path.exists(p):
        os.remove(p)
    app = create_app(DB)
    s = make_session_factory(make_engine(DB))()
    s.add(VendorRecord(vendor_id="VEN-E1", legal_name="Critical Software Co", hq_country="GB"))
    s.add(EngagementRecord(engagement_id="ENG-E1", vendor_id="VEN-E1", title="Core platform"))
    s.commit()
    return TestClient(app), s


# ---- escrow ----
def test_escrow_round_trips_through_register():
    c, s = _app()
    payload = {"data": {"escrow_required": True, "escrow_type": "Source code",
                        "escrow_agent": "NCC Group", "escrow_agreement_ref": "ESC-2026-01",
                        "escrow_status": "Active", "escrow_amount": "USD 50,000",
                        "escrow_release_conditions": "Insolvency or 30-day support failure"}}
    c.put("/api/v2/engagement-register/ENG-E1", headers=H, json=payload)
    ext = c.get("/api/v2/engagement-register/ENG-E1", headers=H).json()["ext"]
    assert ext["escrow_required"] is True
    assert ext["escrow_agent"] == "NCC Group"
    assert ext["escrow_type"] == "Source code"
    assert ext["escrow_release_conditions"].startswith("Insolvency")


def test_escrow_fields_in_allowlist():
    from app.features.domain.master_service import ENG_EXT_FIELDS
    for f in ("escrow_required", "escrow_agent", "escrow_release_conditions", "escrow_notes"):
        assert f in ENG_EXT_FIELDS


# ---- AI provider keys ----
def test_ai_keys_bulk_set_persists_and_status():
    for ev in ("XAI_API_KEY", "MANUS_API_KEY"):
        os.environ.pop(ev, None)
    c, s = _app()
    st = c.post("/api/v1/ai/keys", headers=H,
                json={"grok": "xai-test-123", "manus": "manus-test-456"}).json()
    assert st["grok_key_present"] is True and st["manus_key_present"] is True
    # persisted in config store
    from app.features.domain import config_store as CFG
    s2 = make_session_factory(make_engine(DB))()
    stored = CFG.get_json(s2, "ai_provider_keys", {})
    from app.features.admin import security as _SEC
    assert _SEC.decrypt_value(stored.get("grok")) == "xai-test-123"
    assert _SEC.decrypt_value(stored.get("manus")) == "manus-test-456"
    assert stored.get("grok") != "xai-test-123"  # never raw at rest (plain:/enc: envelope)
    for ev in ("XAI_API_KEY", "MANUS_API_KEY"):
        os.environ.pop(ev, None)


def test_ai_key_single_rejects_unknown_provider():
    c, s = _app()
    r = c.post("/api/v1/ai/key", headers=H, json={"provider": "bogus", "api_key": "x"})
    assert r.status_code == 400


def test_ai_status_reports_four_providers():
    c, s = _app()
    st = c.get("/api/v1/ai/status", headers=H).json()
    for k in ("claude_key_present", "openai_key_present", "grok_key_present", "manus_key_present"):
        assert k in st


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
