"""AI Control advanced: agent personas + assessment rubric are live wiring, not labels."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app  # noqa: E402
from app.features.assessment import prompts as P  # noqa: E402
from app.features.assessment import agents as A  # noqa: E402

H = {"x-user": "admin"}
DB = "sqlite:////tmp/aipa.db"


def _client():
    if os.path.exists("/tmp/aipa.db"):
        os.remove("/tmp/aipa.db")
    return TestClient(create_app(DB))


def test_personas_and_rubric_registered():
    d = P.defaults()
    assert "assessment_rubric" in d
    for aid in A.AGENTS:
        assert f"agent_persona_{aid}" in d
        assert d[f"agent_persona_{aid}"]["default"] == A.AGENT_BRIEFS.get(aid, "")
    assert "ProAssess agent personas" in P.GROUP_ORDER
    assert "ProAssess assessment" in P.GROUP_ORDER


def test_persona_override_reaches_system_prompt():
    c = _client()
    c.post("/api/v1/ai/prompts/agent_persona_scope", headers=H,
           json={"text": "OVERRIDDEN-SARA-PERSONA for testing."})
    from app.bro_app import make_engine, make_session_factory
    eng = make_engine(DB)
    s = make_session_factory(eng)()
    briefs = {aid: P.resolve(s, f"agent_persona_{aid}") for aid in A.AGENTS}
    sp = A.build_system_prompt("scope", 2, {}, [], "methodology", briefs)
    assert "OVERRIDDEN-SARA-PERSONA" in sp
    sp_default = A.build_system_prompt("scope", 2, {}, [], "methodology")
    assert "OVERRIDDEN-SARA-PERSONA" not in sp_default
    s.close()


def test_rubric_override_resolves():
    c = _client()
    c.post("/api/v1/ai/prompts/assessment_rubric", headers=H,
           json={"text": "CUSTOM RUBRIC: always return JSON."})
    from app.bro_app import make_engine, make_session_factory
    s = make_session_factory(make_engine(DB))()
    assert P.resolve(s, "assessment_rubric") == "CUSTOM RUBRIC: always return JSON."
    s.close()


def test_groups_render_in_listing():
    c = _client()
    d = c.get("/api/v1/ai/prompts", headers=H).json()
    groups = {p["group"] for p in d["prompts"]}
    assert "ProAssess agent personas" in groups and "Exit & Offboarding" in groups
    assert len(d["prompts"]) >= 30


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
