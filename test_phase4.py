"""
Phase 4 tests: the parsing/validation layer and fail-safe orchestration.
This is where real-world reliability lives, so the parser is hammered with the
messy outputs models actually produce. No live API calls.
"""
import sys
sys.path.insert(0, "/home/claude/tprm")

from app.agents.verdict_parser import parse_verdict, VerdictParseError
from app.agents.prompt import build_prompt
from app.agents.provider import Provider, LLMRequest, LLMResponse
from app.agents.agent import safe_assess_and_gate
from app.agents.escalation import DomainGate, CalibrationState
from app.models.policy import EffectiveControl, DataClassification, RiskWeight
from app.models.evidence import (
    ResolvedEvidence, Evidence, SourceType, ActorRole, ConflictNote,
)
from app.models.rating import Tier
from datetime import date

PROV_KW = dict(
    control_id="CTL-1", domain="InfoSec", provider=Provider.CLAUDE,
    winning_evidence_id="e1", considered_evidence_ids=("e1", "e2"),
    conflict_present=False, effective_control_origin="baseline",
    baseline_version=3,
)


def _parse(text):
    return parse_verdict(text, **PROV_KW)


# ---- clean and messy happy paths ----

def test_clean_json():
    v = _parse('{"tier": 2, "confidence": 0.88, "severity": 3, "rationale": "ok"}')
    assert v.tier is Tier.TIER_2 and v.confidence == 0.88 and v.severity == 3

def test_markdown_fenced_json():
    v = _parse('```json\n{"tier": 1, "confidence": 0.9, "severity": 5}\n```')
    assert v.tier is Tier.TIER_1

def test_preamble_and_trailing_prose():
    text = ('Here is my assessment of the control:\n'
            '{"tier": 3, "confidence": 0.7, "severity": 2, "rationale": "fine"}\n'
            'Let me know if you need more detail.')
    v = _parse(text)
    assert v.tier is Tier.TIER_3

def test_tier_as_string_form():
    v = _parse('{"tier": "TIER_2", "confidence": 0.8, "severity": 2}')
    assert v.tier is Tier.TIER_2

def test_confidence_as_string_number():
    v = _parse('{"tier": 2, "confidence": "0.75", "severity": 2}')
    assert v.confidence == 0.75

def test_nested_braces_in_rationale():
    v = _parse('{"tier": 2, "confidence": 0.8, "severity": 2, '
               '"rationale": "uses {placeholder} syntax"}')
    assert "placeholder" in v.rationale


# ---- failure paths: must raise, never silently pass ----

def test_empty_output_raises():
    try: _parse("   "); assert False
    except VerdictParseError: pass

def test_no_json_raises():
    try: _parse("I cannot assess this without more info."); assert False
    except VerdictParseError: pass

def test_malformed_json_raises():
    try: _parse('{"tier": 2, "confidence": 0.8, severity: }'); assert False
    except VerdictParseError: pass

def test_missing_required_field_raises():
    try: _parse('{"tier": 2, "confidence": 0.8}'); assert False  # no severity
    except VerdictParseError: pass

def test_tier_out_of_range_raises():
    try: _parse('{"tier": 7, "confidence": 0.8, "severity": 2}'); assert False
    except VerdictParseError: pass

def test_confidence_out_of_range_raises():
    try: _parse('{"tier": 2, "confidence": 1.5, "severity": 2}'); assert False
    except VerdictParseError: pass

def test_severity_out_of_range_raises():
    try: _parse('{"tier": 2, "confidence": 0.8, "severity": 9}'); assert False
    except VerdictParseError: pass

def test_boolean_tier_rejected():
    try: _parse('{"tier": true, "confidence": 0.8, "severity": 2}'); assert False
    except VerdictParseError: pass

def test_provenance_comes_from_system_not_model():
    # model tries to claim different evidence; system-supplied provenance wins
    v = _parse('{"tier": 2, "confidence": 0.8, "severity": 2, '
               '"winning_evidence_id": "FAKE", "considered_evidence_ids": ["x"]}')
    assert v.winning_evidence_id == "e1"          # from PROV_KW, not the model
    assert v.considered_evidence_ids == ("e1", "e2")


# ---- prompt building ----

def _control():
    return EffectiveControl(
        control_id="CTL-1", org_id="org", domain="InfoSec",
        statement="Supplier must encrypt data classification at rest",
        threshold="AES-256", applicability=DataClassification.CONFIDENTIAL,
        risk_weight=RiskWeight.HIGH, origin="baseline+override",
        baseline_version=3, needs_review=False,
        terminology={"data classification": "data sensitivity tier"},
    )

def test_prompt_applies_terminology():
    system, user = build_prompt(_control(), None)
    assert "data sensitivity tier" in user
    assert "data classification" not in user      # replaced
    assert "JSON" in system

def test_prompt_flags_conflict_and_staleness():
    ev = Evidence("e1","org","eng",SourceType.INDEPENDENT_AUDIT,
                  ActorRole.VENDOR,"AES-256 verified","InfoSec",date(2024,1,1))
    resolved = ResolvedEvidence(
        domain="InfoSec", winner=ev, considered=("e1","e2"),
        conflicts=(ConflictNote("e1","e2","InfoSec","x"),), staleness_flag=True,
    )
    _, user = build_prompt(_control(), resolved)
    assert "freshness" in user and "contradict" in user


# ---- fail-safe orchestration ----

class _BadAgent:
    """Returns an agent that raises on parse — simulated via a stub that the
    real LLMBackedAgent would produce on unreadable output."""
    def assess(self, control, resolved, provider):
        raise VerdictParseError("model returned prose, no JSON")

_GATE = DomainGate("InfoSec", "claude", CalibrationState.CALIBRATED, 0.85, 15)

def test_unparseable_verdict_fails_safe_to_escalation():
    result = safe_assess_and_gate(
        _control(), None, _BadAgent(), _GATE,
        is_tier0_vendor=False, rollup_band_changed=False,
    )
    assert result.parse_failed is True
    assert result.finding is None
    assert result.goes_to_human is True           # the whole point
    assert "no JSON" in result.failure_reason


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
