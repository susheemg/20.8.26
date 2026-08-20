"""AI Control — central prompt registry with admin overrides used by all AI features."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app, make_session_factory, make_engine  # noqa: E402
from app.features.assessment import prompts as P  # noqa: E402

H = {"x-user": "admin"}
DB = "sqlite:////tmp/aip.db"


def _client():
    if os.path.exists("/tmp/aip.db"):
        os.remove("/tmp/aip.db")
    return TestClient(create_app(DB))


def test_listing_returns_all_defaults():
    c = _client()
    d = c.get("/api/v1/ai/prompts", headers=H).json()
    assert len(d["prompts"]) == len(P.defaults())
    assert all(not p["overridden"] for p in d["prompts"])
    assert d["groups"] == P.GROUP_ORDER


def test_resolve_default_then_override():
    c = _client()
    s = make_session_factory(make_engine(DB))()
    assert P.resolve(s, "board_intelligence").startswith("You are a BCG-grade board adviser")
    c.post("/api/v1/ai/prompts/board_intelligence", headers=H, json={"text": "CUSTOM."})
    s.expire_all()
    assert P.resolve(s, "board_intelligence") == "CUSTOM."  # the feature now uses this


def test_listing_marks_overridden():
    c = _client()
    c.post("/api/v1/ai/prompts/management_chat", headers=H, json={"text": "X prompt."})
    d = c.get("/api/v1/ai/prompts", headers=H).json()
    mc = [p for p in d["prompts"] if p["key"] == "management_chat"][0]
    assert mc["overridden"] and mc["current"] == "X prompt."


def test_reset_restores_default():
    c = _client()
    s = make_session_factory(make_engine(DB))()
    c.post("/api/v1/ai/prompts/exposure_brief", headers=H, json={"text": "Y."})
    c.post("/api/v1/ai/prompts/exposure_brief/reset", headers=H, json={})
    s.expire_all()
    assert P.resolve(s, "exposure_brief") == P.defaults()["exposure_brief"]["default"]


def test_unknown_key_404_and_empty_400():
    c = _client()
    assert c.post("/api/v1/ai/prompts/nope", headers=H, json={"text": "x"}).status_code == 404
    assert c.post("/api/v1/ai/prompts/exposure_brief", headers=H, json={"text": " "}).status_code == 400


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
