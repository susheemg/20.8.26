"""
Phase 3b: calibration analysis and the graduation gate.

Two questions decide whether a (domain x provider) may leave shadow mode:

  1. Is confidence CALIBRATED? When the AI says 0.9, is it right ~90% of the
     time? An overconfident model silently auto-delivers wrong answers. We
     measure this with a reliability curve (binned confidence vs. observed
     accuracy) and an Expected Calibration Error (ECE).

  2. Is escalation RECALL high enough? Of the cases that truly needed a human,
     what fraction would the gate actually have escalated? In by-exception
     validation, MISSED escalations are the failure that bites invisibly, so
     recall on "should escalate" matters more than raw tier accuracy.

graduation_decision() refuses to pass a domain unless BOTH clear configured
bars AND there is enough data. It also computes a recommended confidence_floor
from the data rather than letting anyone hand-set it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .observation import Observation


@dataclass(frozen=True)
class ReliabilityBin:
    lo: float
    hi: float
    count: int
    mean_confidence: float
    observed_accuracy: float


@dataclass(frozen=True)
class CalibrationReport:
    domain: str
    provider: str
    n: int
    tier_accuracy: float
    ece: float                       # expected calibration error (lower better)
    escalation_recall: float         # of should-escalate, fraction caught
    escalation_precision: float      # of escalated, fraction that needed it
    silent_miss_rate: float          # auto-delivered AND wrong AND needed human
    bins: tuple[ReliabilityBin, ...]
    recommended_confidence_floor: float


def _reliability_bins(obs: Sequence[Observation], n_bins: int = 5
                      ) -> list[ReliabilityBin]:
    bins: list[ReliabilityBin] = []
    width = 1.0 / n_bins
    for i in range(n_bins):
        lo, hi = i * width, (i + 1) * width
        in_bin = [o for o in obs
                  if (o.ai_confidence >= lo and
                      (o.ai_confidence < hi or (i == n_bins - 1 and o.ai_confidence <= hi)))]
        if not in_bin:
            continue
        mean_conf = sum(o.ai_confidence for o in in_bin) / len(in_bin)
        acc = sum(1 for o in in_bin if o.tier_correct) / len(in_bin)
        bins.append(ReliabilityBin(lo, hi, len(in_bin), mean_conf, acc))
    return bins


def _ece(bins: Sequence[ReliabilityBin], n_total: int) -> float:
    if n_total == 0:
        return 1.0
    return sum(b.count / n_total * abs(b.mean_confidence - b.observed_accuracy)
               for b in bins)


def _recommended_floor(obs: Sequence[Observation]) -> float:
    """Lowest confidence at which observed accuracy stays >= 0.9, scanning
    high→low. If no band qualifies, return 1.0 (i.e. never auto-deliver yet)."""
    by_conf = sorted(obs, key=lambda o: o.ai_confidence, reverse=True)
    floor = 1.0
    running_correct = 0
    for i, o in enumerate(by_conf, start=1):
        running_correct += 1 if o.tier_correct else 0
        if running_correct / i >= 0.9:
            floor = o.ai_confidence
        else:
            break
    return round(floor, 3)


def analyse(obs: Sequence[Observation], domain: str, provider: str
           ) -> CalibrationReport:
    n = len(obs)
    if n == 0:
        return CalibrationReport(domain, provider, 0, 0.0, 1.0, 0.0, 0.0, 0.0,
                                 (), 1.0)

    tier_acc = sum(1 for o in obs if o.tier_correct) / n

    should = [o for o in obs if o.human_judged_should_escalate]
    would = [o for o in obs if o.ai_would_have_escalated]
    caught = [o for o in should if o.ai_would_have_escalated]
    recall = (len(caught) / len(should)) if should else 1.0
    precision = (sum(1 for o in would if o.human_judged_should_escalate)
                 / len(would)) if would else 1.0
    silent = sum(1 for o in obs if o.is_silent_miss) / n

    bins = _reliability_bins(obs)
    return CalibrationReport(
        domain=domain, provider=provider, n=n,
        tier_accuracy=round(tier_acc, 3),
        ece=round(_ece(bins, n), 3),
        escalation_recall=round(recall, 3),
        escalation_precision=round(precision, 3),
        silent_miss_rate=round(silent, 3),
        bins=tuple(bins),
        recommended_confidence_floor=_recommended_floor(obs),
    )


@dataclass(frozen=True)
class GraduationCriteria:
    min_observations: int = 200
    max_ece: float = 0.05
    min_escalation_recall: float = 0.95
    max_silent_miss_rate: float = 0.01


@dataclass(frozen=True)
class GraduationDecision:
    may_graduate: bool
    reasons: tuple[str, ...]
    report: CalibrationReport


def graduation_decision(
    report: CalibrationReport,
    criteria: GraduationCriteria = GraduationCriteria(),
) -> GraduationDecision:
    """Refuse to graduate unless EVERY bar clears. Conservative by design:
    a domain stays in shadow mode until it has genuinely earned auto-delivery."""
    reasons: list[str] = []
    if report.n < criteria.min_observations:
        reasons.append(f"insufficient_data_{report.n}<{criteria.min_observations}")
    if report.ece > criteria.max_ece:
        reasons.append(f"poorly_calibrated_ece_{report.ece}>{criteria.max_ece}")
    if report.escalation_recall < criteria.min_escalation_recall:
        reasons.append(
            f"low_recall_{report.escalation_recall}<{criteria.min_escalation_recall}")
    if report.silent_miss_rate > criteria.max_silent_miss_rate:
        reasons.append(
            f"silent_misses_{report.silent_miss_rate}>{criteria.max_silent_miss_rate}")

    if reasons:
        return GraduationDecision(False, tuple(reasons), report)
    return GraduationDecision(True, ("all_criteria_met",), report)
