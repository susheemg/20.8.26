"""
Phase 6 tests: BRO scoring rules, lifecycle, and the API end-to-end.
Uses FastAPI's TestClient — no running server, no database, no API key.
"""
import sys
sys.path.insert(0, "/home/claude/tprm")

from fastapi.testclient import TestClient
from app.api import create_app, Store
from app.core.scoring import (
    Band, ControlOutcome, ControlResult, RoutingDecision, TriageInput,
    band_for_score, residual_band, route,
)
from app.core.lifecycle import Engagement, Stage, IllegalTransition


# ---- scoring rules ----

def test_banding_thresholds():
    assert band_for_score(85) is Band.HIGH
    assert band_for_score(60) is Band.ELEVATED
    assert band_for_score(35) is Band.MODERATE
    assert band_for_score(10) is Band.LOW

def test_critical_control_marginal_forces_high():
    controls = [
        ControlResult("C1", "InfoSec", ControlOutcome.SATISFIED, False),
        ControlResult("C2", "InfoSec", ControlOutcome.MARGINAL, True),  # critical
    ]
    r = residual_band(10.0, controls)   # low score...
    assert r.band is Band.HIGH          # ...but forced HIGH
    assert r.critical_override_applied is True

def test_no_critical_failure_keeps_score_band():
    controls = [ControlResult("C1", "InfoSec", ControlOutcome.MARGINAL, False)]
    r = residual_band(35.0, controls)
    assert r.band is Band.MODERATE
    assert r.critical_override_applied is False

def test_routing_auto_approve_only_when_clean():
    clean = TriageInput(3, False, False, False, False, Band.LOW)
    assert route(clean) is RoutingDecision.AUTO_APPROVE
    # any blocker removes auto-approve
    ai = TriageInput(3, False, False, False, True, Band.LOW)
    assert route(ai) is RoutingDecision.FAST_TRACK
    high = TriageInput(1, False, False, False, False, Band.HIGH)
    assert route(high) is RoutingDecision.FULL_DILIGENCE


# ---- lifecycle ----

def test_legal_transition_chain():
    e = Engagement("e1", "v1", "org")
    e.transition(Stage.TRIAGE, "x")
    e.transition(Stage.INHERENT, "x")
    e.transition(Stage.DILIGENCE, "x")
    e.transition(Stage.DECISION, "x")
    assert e.stage is Stage.DECISION
    assert len(e.notifications) == 4

def test_illegal_transition_blocked():
    e = Engagement("e1", "v1", "org")
    try:
        e.transition(Stage.DECISION, "skip")   # can't skip to decision from sourcing
        assert False
    except IllegalTransition:
        pass

def test_monitoring_can_reopen_reassessment():
    e = Engagement("e1", "v1", "org")
    for s in (Stage.TRIAGE, Stage.INHERENT, Stage.DILIGENCE, Stage.DECISION,
              Stage.CONTRACT, Stage.ONBOARD, Stage.MONITOR):
        e.transition(s, "x")
    e.transition(Stage.REASSESS, "monitoring_triggered")
    assert e.stage is Stage.REASSESS


# ---- API end-to-end ----

def _client():
    return TestClient(create_app(Store()))

def test_api_health():
    r = _client().get("/api/v1/health")
    assert r.status_code == 200 and r.json()["version"] == "3.1"

def test_api_full_flow_to_decision():
    c = _client()
    v = c.post("/api/v1/vendors", json={"org_id": "org", "name": "Acme Payments"})
    vid = v.json()["vendor_id"]
    e = c.post("/api/v1/engagements",
               json={"org_id": "org", "vendor_id": vid})
    eid = e.json()["engagement_id"]
    assert e.json()["stage"] == "sourcing"

    c.post(f"/api/v1/engagements/{eid}/triage",
           json={"tier": 1, "cross_border": True})
    inh = c.post(f"/api/v1/engagements/{eid}/inherent",
                 json={"irq": {"exposure_score": 75},
                       "t": {"tier": 1, "cross_border": True}})
    assert inh.json()["inherent_band"] == "HIGH"
    assert inh.json()["routing"] == "FULL_DILIGENCE"

    dec = c.post(f"/api/v1/engagements/{eid}/decision",
                 json={"exposure_score": 20, "actor_id": "user-vrm",
                       "actor_is_human": True,
                       "controls": [{"control_id": "C2", "domain": "InfoSec",
                                     "outcome": "marginal", "is_critical": True}]})
    body = dec.json()
    assert body["critical_override_applied"] is True
    assert body["final_band"] == "HIGH"      # low score overridden by critical control

def test_api_override_requires_justification_and_second_approver():
    c = _client()
    vid = c.post("/api/v1/vendors", json={"org_id": "org", "name": "X"}).json()["vendor_id"]
    eid = c.post("/api/v1/engagements", json={"org_id": "org", "vendor_id": vid}).json()["engagement_id"]
    c.post(f"/api/v1/engagements/{eid}/triage", json={"tier": 2})
    c.post(f"/api/v1/engagements/{eid}/inherent",
           json={"irq": {"exposure_score": 75}, "t": {"tier": 2}})
    # override without second approver -> rejected
    bad = c.post(f"/api/v1/engagements/{eid}/decision",
                 json={"exposure_score": 75, "actor_id": "u", "actor_is_human": True,
                       "override_band": "LOW", "override_reason": "accepted risk"})
    assert bad.status_code == 400

def test_api_audit_trail_intact_after_flow():
    c = _client()
    vid = c.post("/api/v1/vendors", json={"org_id": "org", "name": "X"}).json()["vendor_id"]
    c.post("/api/v1/engagements", json={"org_id": "org", "vendor_id": vid})
    v = c.get("/api/v1/audit/verify").json()
    assert v["intact"] is True and v["entries"] >= 2


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
