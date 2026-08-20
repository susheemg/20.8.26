"""
Phase 2b: the escalation engine — the centre of gravity of the whole product.

In an AI-first / human-validates-by-exception model, this is the ONLY thing
standing between a confident wrong answer and an enterprise customer. It decides:
auto-deliver vs. route-to-human.

Core gate: confidence x impact.
    impact = risk_weight(of the control/domain) x severity(of the finding)
Two axes, never confidence alone — a 0.95 finding on a critical domain still
gets human eyes.

MANDATORY-escalation modifiers (override the gate, force human review):
  - Tier 0 vendor            : critical vendors tighten/disable auto-deliver
  - roll-up band CHANGE      : concentration/worst-of moved a rating band
  - evidence CONFLICT present: contradicting sources need a human call
  - needs_review policy       : effective control lagged the baseline (Phase 0)

ACTION gate (Q3) is SEPARATE and lives in actions.py: findings may auto-deliver,
but any consequential ACTION always requires human agreement. Don't conflate.

Thresholds come from shadow-mode calibration data, never guesses. Until a
domain is calibrated, decision is ALWAYS ESCALATE (shadow mode).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    AUTO_DELIVER = "auto_deliver"
    ESCALATE = "escalate"


class CalibrationState(str, Enum):
    SHADOW = "shadow"          # everything escalates; gathering calibration data
    CALIBRATED = "calibrated"  # auto-deliver permitted within thresholds


@dataclass(frozen=True)
class DomainGate:
    """Per-(domain x provider) gate, set FROM calibration data."""
    domain: str
    provider: str
    state: CalibrationState
    confidence_floor: float    # min confidence to auto-deliver
    max_impact_auto: int       # impact at/above which we always escalate


@dataclass(frozen=True)
class EscalationInput:
    domain: str
    provider: str
    confidence: float
    risk_weight: int           # 1..5
    severity: int              # 1..5 (finding severity; e.g. worst=5)
    is_tier0_vendor: bool
    rollup_band_changed: bool
    evidence_conflict: bool
    policy_needs_review: bool


@dataclass(frozen=True)
class EscalationResult:
    decision: Decision
    reasons: tuple[str, ...]   # every reason recorded -> audit chain
    impact: int


def _impact(risk_weight: int, severity: int) -> int:
    return risk_weight * severity


def decide(inp: EscalationInput, gate: DomainGate) -> EscalationResult:
    reasons: list[str] = []
    impact = _impact(inp.risk_weight, inp.severity)

    # 1. Shadow mode: nothing auto-delivers, full stop.
    if gate.state is CalibrationState.SHADOW:
        return EscalationResult(Decision.ESCALATE, ("domain_in_shadow_mode",), impact)

    # 2. Mandatory-escalation modifiers (any one forces human review).
    if inp.is_tier0_vendor:
        reasons.append("tier0_critical_vendor")
    if inp.rollup_band_changed:
        reasons.append("rollup_band_changed")
    if inp.evidence_conflict:
        reasons.append("evidence_conflict_present")
    if inp.policy_needs_review:
        reasons.append("policy_lags_baseline")
    if reasons:
        return EscalationResult(Decision.ESCALATE, tuple(reasons), impact)

    # 3. The confidence x impact gate.
    if impact >= gate.max_impact_auto:
        reasons.append(f"impact_{impact}_at_or_above_max_{gate.max_impact_auto}")
    if inp.confidence < gate.confidence_floor:
        reasons.append(
            f"confidence_{inp.confidence:.2f}_below_floor_{gate.confidence_floor:.2f}"
        )
    if reasons:
        return EscalationResult(Decision.ESCALATE, tuple(reasons), impact)

    # 4. Cleared every check -> auto-deliver.
    return EscalationResult(Decision.AUTO_DELIVER, ("passed_all_gates",), impact)
