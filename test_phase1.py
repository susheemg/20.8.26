"""
Phase 1 tests: evidence precedence, roll-up, and Tier 0 governance.
Proves the five locked decisions behave as specified.
"""
import sys
from datetime import date, timedelta
sys.path.insert(0, "/home/claude/tprm")

from app.models.evidence import (
    Evidence, SourceType, ActorRole,
)
from app.core.evidence_resolution import resolve_evidence
from app.models.rating import (
    DomainRating, Tier, GOVERNANCE_TIER_0,
)
from app.core.rollup import (
    roll_up_engagement, roll_up_vendor, apply_governance_flag,
)

ORG, ENG, VEN = "org-acme", "eng-1", "ven-1"
TODAY = date(2026, 5, 30)


def _ev(eid, stype, claim, captured, valid_until=None, domain="InfoSec"):
    return Evidence(
        evidence_id=eid, org_id=ORG, engagement_id=ENG, source_type=stype,
        author_role=ActorRole.VENDOR, claim=claim, domain=domain,
        captured_on=captured, valid_until=valid_until,
    )


# ---- Q4: evidence precedence ----

def test_audit_beats_attestation_beats_chat():
    ev = [
        _ev("e1", SourceType.VENDOR_CHAT_CLAIM, "working on encryption", date(2026, 5, 1)),
        _ev("e2", SourceType.VENDOR_ATTESTATION, "AES-256 in place", date(2026, 4, 1)),
        _ev("e3", SourceType.INDEPENDENT_AUDIT, "AES-256 verified", date(2026, 3, 1),
            valid_until=date(2027, 3, 1)),
    ]
    r = resolve_evidence("InfoSec", ev, as_of=TODAY)
    assert r.winner.evidence_id == "e3"
    assert len(r.considered) == 3


def test_expired_audit_does_not_beat_valid_attestation():
    ev = [
        _ev("e1", SourceType.INDEPENDENT_AUDIT, "verified", date(2022, 1, 1),
            valid_until=date(2023, 1, 1)),                      # expired
        _ev("e2", SourceType.VENDOR_ATTESTATION, "in place", date(2026, 4, 1),
            valid_until=date(2027, 4, 1)),                      # valid
    ]
    r = resolve_evidence("InfoSec", ev, as_of=TODAY)
    assert r.winner.evidence_id == "e2"  # valid attestation wins over expired audit


def test_conflict_is_recorded_not_erased():
    ev = [
        _ev("e1", SourceType.INDEPENDENT_AUDIT, "AES-256 verified", date(2026, 3, 1),
            valid_until=date(2027, 3, 1)),
        _ev("e2", SourceType.VENDOR_CHAT_CLAIM, "still working on it", date(2026, 5, 1)),
    ]
    r = resolve_evidence("InfoSec", ev, as_of=TODAY)
    assert r.winner.evidence_id == "e1"
    assert len(r.conflicts) == 1
    assert r.conflicts[0].losing_evidence_id == "e2"


def test_stale_but_valid_winner_is_flagged():
    ev = [
        _ev("e1", SourceType.INDEPENDENT_AUDIT, "verified", date(2024, 1, 1),
            valid_until=date(2030, 1, 1)),  # valid but >400 days old
    ]
    r = resolve_evidence("InfoSec", ev, as_of=TODAY)
    assert r.staleness_flag is True


# ---- Q2: roll-up ----

def test_engagement_worst_of():
    drs = [
        DomainRating(ENG, "InfoSec", Tier.TIER_3, 0.9, "ok-ish"),
        DomainRating(ENG, "Concentration", Tier.TIER_1, 0.8, "single source"),
        DomainRating(ENG, "Privacy", Tier.TIER_4, 0.95, "fine"),
    ]
    er = roll_up_engagement(ENG, VEN, drs)
    assert er.computed_tier == Tier.TIER_1  # worst domain drives it


def test_vendor_concentration_escalates_tier():
    # 3 engagements all Tier 3 -> worst-of is Tier 3, but concentration
    # (>=3 at/worse than Tier 3) escalates vendor to Tier 2.
    ers = [
        roll_up_engagement(f"e{i}", VEN,
                           [DomainRating(f"e{i}", "InfoSec", Tier.TIER_3, 0.9, "x")])
        for i in range(3)
    ]
    vr = roll_up_vendor(VEN, ers)
    assert vr.concentration_applied is True
    assert vr.computed_tier == Tier.TIER_2  # escalated one band from Tier 3


def test_vendor_no_concentration_keeps_worst_of():
    ers = [
        roll_up_engagement("e1", VEN,
                           [DomainRating("e1", "InfoSec", Tier.TIER_3, 0.9, "x")]),
        roll_up_engagement("e2", VEN,
                           [DomainRating("e2", "InfoSec", Tier.TIER_4, 0.9, "x")]),
    ]
    vr = roll_up_vendor(VEN, ers)
    assert vr.concentration_applied is False
    assert vr.computed_tier == Tier.TIER_3


# ---- Q5: Tier 0 governance ----

def test_tier0_human_only_rejects_ai():
    ers = [roll_up_engagement("e1", VEN,
           [DomainRating("e1", "InfoSec", Tier.TIER_3, 0.9, "x")])]
    vr = roll_up_vendor(VEN, ers)
    try:
        apply_governance_flag(vr, actor_role_is_human=False,
                              actor_id="agent-x", reason_code="X")
        assert False, "AI should not be able to set Tier 0"
    except PermissionError:
        pass


def test_tier0_preserves_computed_tier():
    ers = [roll_up_engagement("e1", VEN,
           [DomainRating("e1", "InfoSec", Tier.TIER_3, 0.9, "x")])]
    vr = roll_up_vendor(VEN, ers)
    flagged = apply_governance_flag(vr, actor_role_is_human=True,
                                    actor_id="user-analyst",
                                    reason_code="SYSTEMIC_PAYMENTS")
    assert flagged.governance_flag == GOVERNANCE_TIER_0
    assert flagged.computed_tier == Tier.TIER_3      # NOT overwritten
    assert flagged.is_critical_vendor is True
    assert "computed TIER_3" in flagged.effective_label


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
