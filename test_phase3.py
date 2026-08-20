"""
Phase 3 tests: the calibration harness.
Proves a domain cannot leave shadow mode until it has earned it, and that
drift after cutover pulls it back.
"""
import sys
sys.path.insert(0, "/home/claude/tprm")

from app.calibration.observation import ObservationLog, HumanOutcome
from app.calibration.analysis import (
    analyse, graduation_decision, GraduationCriteria,
)
from app.calibration.sampling import should_sample, check_drift

DOM, PROV, ORG = "InfoSec", "claude", "org"


def _log_well_calibrated(n=300):
    """Build observations where confidence tracks accuracy and the gate
    catches everything that needs escalating."""
    log = ObservationLog()
    for i in range(n):
        # high-confidence band: ~97% correct at mean conf 0.97
        # low-confidence band:  ~55% correct at mean conf 0.55
        # Both bands well-calibrated (confidence ~= observed accuracy).
        high = i % 10 != 0          # 90% of cases sit in the high band
        if high:
            conf = 0.97
            correct = (i % 33 != 0)         # ~97% correct
        else:
            conf = 0.55
            correct = (i % 2 == 0)          # ~50-55% correct
        ai_tier = 2
        human_tier = 2 if correct else 3
        # gate escalates the low-confidence band; those are the should-escalate.
        would_esc = not high
        should_esc = not high
        log.record(f"o{i}", ORG, DOM, PROV, ai_tier, conf, human_tier,
                   would_esc, should_esc)
    return log


def test_observation_flags_silent_miss():
    log = ObservationLog()
    o = log.record("o1", ORG, DOM, PROV,
                   ai_tier=2, ai_confidence=0.97, human_tier=1,
                   ai_would_have_escalated=False,       # AI thought it was safe
                   human_judged_should_escalate=True)   # but it needed a human
    assert o.outcome is HumanOutcome.CORRECTED
    assert o.is_silent_miss is True


def test_well_calibrated_domain_graduates():
    log = _log_well_calibrated()
    report = analyse(log.for_domain_provider(DOM, PROV), DOM, PROV)
    decision = graduation_decision(report)
    assert report.escalation_recall == 1.0       # caught all should-escalate
    assert report.silent_miss_rate == 0.0
    assert decision.may_graduate is True


def test_insufficient_data_blocks_graduation():
    log = _log_well_calibrated(n=50)              # below min_observations 200
    report = analyse(log.for_domain_provider(DOM, PROV), DOM, PROV)
    decision = graduation_decision(report)
    assert decision.may_graduate is False
    assert any("insufficient_data" in r for r in decision.reasons)


def test_low_recall_blocks_graduation():
    """A domain that misses escalations must not graduate even with lots of data."""
    log = ObservationLog()
    for i in range(300):
        needs_human = i % 5 == 0       # 20% truly need escalation
        # the gate only catches half of those -> poor recall
        caught = needs_human and (i % 10 == 0)
        log.record(f"o{i}", ORG, DOM, PROV,
                   ai_tier=2, ai_confidence=0.9,
                   human_tier=3 if needs_human else 2,
                   ai_would_have_escalated=caught,
                   human_judged_should_escalate=needs_human)
    report = analyse(log.for_domain_provider(DOM, PROV), DOM, PROV)
    decision = graduation_decision(report)
    assert report.escalation_recall < 0.95
    assert decision.may_graduate is False
    assert any("low_recall" in r for r in decision.reasons)


def test_overconfident_domain_has_high_ece():
    """Confidence 0.95 but accuracy 0.6 -> large calibration error."""
    log = ObservationLog()
    for i in range(300):
        correct = i % 10 < 6           # 60% accurate
        log.record(f"o{i}", ORG, DOM, PROV,
                   ai_tier=2, ai_confidence=0.95,
                   human_tier=2 if correct else 3,
                   ai_would_have_escalated=False,
                   human_judged_should_escalate=False)
    report = analyse(log.for_domain_provider(DOM, PROV), DOM, PROV)
    assert report.ece > 0.05
    assert graduation_decision(report).may_graduate is False


def test_sampling_is_deterministic_and_reproducible():
    ids = [f"f{i}" for i in range(1000)]
    first = {fid for fid in ids if should_sample(fid, 0.1)}
    second = {fid for fid in ids if should_sample(fid, 0.1)}
    assert first == second                         # reproducible
    # roughly 10% sampled (allow wide tolerance on 1000 draws)
    assert 50 <= len(first) <= 150


def test_zero_sample_rate_samples_nothing():
    assert should_sample("f1", 0.0) is False


def test_drift_demotes_when_silent_misses_breach():
    """Sampled auto-delivered outputs show silent misses above tolerance."""
    log = ObservationLog()
    for i in range(100):
        miss = i % 10 == 0             # 10% silent miss in samples -> way over 1%
        log.record(f"s{i}", ORG, DOM, PROV,
                   ai_tier=2, ai_confidence=0.96,
                   human_tier=1 if miss else 2,
                   ai_would_have_escalated=False,
                   human_judged_should_escalate=miss)
    report = analyse(log.for_domain_provider(DOM, PROV), DOM, PROV)
    drift = check_drift(report)
    assert drift.recommend_demote is True
    assert drift.within_tolerance is False


def test_drift_holds_when_clean():
    log = ObservationLog()
    for i in range(100):
        log.record(f"s{i}", ORG, DOM, PROV,
                   ai_tier=2, ai_confidence=0.96, human_tier=2,
                   ai_would_have_escalated=False,
                   human_judged_should_escalate=False)
    report = analyse(log.for_domain_provider(DOM, PROV), DOM, PROV)
    drift = check_drift(report)
    assert drift.recommend_demote is False
    assert drift.within_tolerance is True


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
