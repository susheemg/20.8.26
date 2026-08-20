"""
Phase 2 tests: the AI delivery + escalation layer.
Proves the failure mode that sinks AI-first GRC products is closed:
nothing auto-delivers unless it has earned it AND no modifier fires.
"""
import sys
sys.path.insert(0, "/home/claude/tprm")

from app.agents.provider import (
    Provider, ProviderRegistry, LLMRequest, LLMResponse,
)
from app.agents.escalation import (
    Decision, CalibrationState, DomainGate, EscalationInput, decide,
)
from app.agents.agent import (
    AgentVerdict, AssessedFinding, assess_and_gate,
)
from app.agents.actions import (
    ProposedAction, ActionState, NotificationTier,
    agree_action, reject_action, execute_action, may_auto_fire,
)
from app.models.policy import (
    EffectiveControl, DataClassification, RiskWeight,
)
from app.models.evidence import ResolvedEvidence, Evidence, SourceType, ActorRole, ConflictNote
from app.models.rating import Tier
from datetime import date


# ---- provider abstraction ----

class _FakeAdapter:
    def __init__(self, name): self.name = name
    def complete(self, request): return LLMResponse(self.name, "ok")

def test_domain_provider_pinning():
    reg = ProviderRegistry()
    reg.register(_FakeAdapter(Provider.CLAUDE))
    reg.register(_FakeAdapter(Provider.OPENAI))
    reg.pin_domain("InfoSec", Provider.CLAUDE)
    reg.pin_domain("Privacy", Provider.OPENAI)
    assert reg.provider_for("InfoSec") == Provider.CLAUDE
    assert reg.complete(LLMRequest("Privacy", "", "")).provider == Provider.OPENAI

def test_unpinned_domain_raises():
    reg = ProviderRegistry()
    reg.register(_FakeAdapter(Provider.CLAUDE))
    try:
        reg.provider_for("Resilience"); assert False
    except ValueError:
        pass


# ---- escalation engine: the core safety property ----

_CALIB = DomainGate("InfoSec", "claude", CalibrationState.CALIBRATED,
                    confidence_floor=0.85, max_impact_auto=15)

def _inp(**kw):
    base = dict(domain="InfoSec", provider="claude", confidence=0.95,
                risk_weight=2, severity=2, is_tier0_vendor=False,
                rollup_band_changed=False, evidence_conflict=False,
                policy_needs_review=False)
    base.update(kw)
    return EscalationInput(**base)

def test_shadow_mode_never_auto_delivers():
    shadow = DomainGate("InfoSec", "claude", CalibrationState.SHADOW, 0.0, 999)
    # even a perfect, low-impact finding escalates in shadow mode
    r = decide(_inp(confidence=1.0, risk_weight=1, severity=1), shadow)
    assert r.decision is Decision.ESCALATE
    assert "domain_in_shadow_mode" in r.reasons

def test_clean_high_confidence_low_impact_auto_delivers():
    r = decide(_inp(confidence=0.95, risk_weight=2, severity=2), _CALIB)
    assert r.decision is Decision.AUTO_DELIVER

def test_low_confidence_escalates():
    r = decide(_inp(confidence=0.50), _CALIB)
    assert r.decision is Decision.ESCALATE

def test_high_impact_escalates_even_at_high_confidence():
    r = decide(_inp(confidence=0.99, risk_weight=5, severity=5), _CALIB)  # impact 25
    assert r.decision is Decision.ESCALATE

def test_tier0_forces_escalation():
    r = decide(_inp(is_tier0_vendor=True), _CALIB)
    assert r.decision is Decision.ESCALATE
    assert "tier0_critical_vendor" in r.reasons

def test_rollup_band_change_forces_escalation():
    r = decide(_inp(rollup_band_changed=True), _CALIB)
    assert r.decision is Decision.ESCALATE
    assert "rollup_band_changed" in r.reasons

def test_evidence_conflict_forces_escalation():
    r = decide(_inp(evidence_conflict=True), _CALIB)
    assert r.decision is Decision.ESCALATE
    assert "evidence_conflict_present" in r.reasons

def test_policy_needs_review_forces_escalation():
    r = decide(_inp(policy_needs_review=True), _CALIB)
    assert r.decision is Decision.ESCALATE


# ---- agent orchestration wires signals correctly ----

class _FakeAgent:
    def assess(self, control, resolved, provider):
        return AgentVerdict(
            control_id=control.control_id, domain=control.domain,
            tier=Tier.TIER_3, confidence=0.95, severity=2,
            rationale="fake", provider=provider,
            winning_evidence_id=(resolved.winner.evidence_id if resolved else None),
            considered_evidence_ids=(resolved.considered if resolved else ()),
            conflict_present=bool(resolved and resolved.conflicts),
            effective_control_origin=control.origin,
            baseline_version=control.baseline_version,
        )

def _control():
    return EffectiveControl(
        control_id="CTL-1", org_id="org", domain="InfoSec",
        statement="encrypt", threshold="AES-256",
        applicability=DataClassification.CONFIDENTIAL,
        risk_weight=RiskWeight.LOW, origin="baseline",
        baseline_version=3, needs_review=False, terminology={},
    )

def test_orchestration_conflict_from_evidence_triggers_escalation():
    ev = Evidence("e1","org","eng",SourceType.INDEPENDENT_AUDIT,
                  ActorRole.VENDOR,"yes","InfoSec",date(2026,3,1))
    resolved = ResolvedEvidence(
        domain="InfoSec", winner=ev, considered=("e1","e2"),
        conflicts=(ConflictNote("e1","e2","InfoSec","contradiction"),),
        staleness_flag=False,
    )
    finding = assess_and_gate(_control(), resolved, _FakeAgent(), _CALIB,
                              is_tier0_vendor=False, rollup_band_changed=False)
    assert finding.goes_to_human is True
    assert "evidence_conflict_present" in finding.escalation.reasons

def test_orchestration_clean_path_auto_delivers():
    finding = assess_and_gate(_control(), None, _FakeAgent(), _CALIB,
                              is_tier0_vendor=False, rollup_band_changed=False)
    assert finding.goes_to_human is False


# ---- action gate (Q3): second, always-human gate ----

def _action():
    return ProposedAction("a1","org","eng","send remediation notice",
                          "agent-x", target_touches_vendor=True)

def test_action_requires_human_agreement():
    try:
        agree_action(_action(), "agent-x", actor_is_human=False, reason_code="X")
        assert False
    except PermissionError:
        pass

def test_cannot_execute_without_agreement():
    rec = reject_action(_action(), "user-1", "NOT_NEEDED")
    try:
        execute_action(rec); assert False
    except PermissionError:
        pass

def test_agreed_action_executes():
    rec = agree_action(_action(), "user-analyst", actor_is_human=True,
                       reason_code="REMEDIATION_REQUIRED")
    assert rec.state is ActionState.AGREED
    done = execute_action(rec)
    assert done.state is ActionState.EXECUTED

def test_notification_tiers():
    assert may_auto_fire(NotificationTier.INFORMATIONAL) is True
    assert may_auto_fire(NotificationTier.CONSEQUENTIAL) is False


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
