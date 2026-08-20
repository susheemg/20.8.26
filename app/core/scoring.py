"""
Phase 6a: BRO scoring rules (from the compendium).

Two rules the compendium specifies that complement the tier engine:

  1. Exposure-additive banding across the six domains:
        HIGH >= 70 · ELEVATED 50-69 · MODERATE 30-49 · LOW < 30
     This is the INHERENT/RESIDUAL band (BRO's headline number), distinct from
     the 1-4 Tier (which we keep for the rating hierarchy). Both coexist: the
     band is the exposure score; the Tier is the governance classification.

  2. Critical-control override: "Any critical-control MARGINAL forces residual
     HIGH." A single failing critical control cannot be averaged away — it
     dominates. This mirrors worst-of logic at the control level.

Pure functions, fully testable, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class Band(str, Enum):
    HIGH = "HIGH"
    ELEVATED = "ELEVATED"
    MODERATE = "MODERATE"
    LOW = "LOW"


class ControlOutcome(str, Enum):
    SATISFIED = "satisfied"
    MARGINAL = "marginal"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


SIX_DOMAINS = (
    "InformationSecurity",
    "OperationalResilience",
    "Privacy",
    "Compliance",
    "Financial",
    "Reputational",
)


def band_for_score(score: float) -> Band:
    """Exposure-additive banding per the compendium thresholds."""
    if score >= 70:
        return Band.HIGH
    if score >= 50:
        return Band.ELEVATED
    if score >= 30:
        return Band.MODERATE
    return Band.LOW


@dataclass(frozen=True)
class ControlResult:
    control_id: str
    domain: str
    outcome: ControlOutcome
    is_critical: bool


@dataclass(frozen=True)
class ResidualResult:
    raw_score: float
    band: Band
    critical_override_applied: bool
    rationale: str


def residual_band(
    exposure_score: float,
    control_results: Sequence[ControlResult],
) -> ResidualResult:
    """
    Compute the residual band from the exposure score, then apply the
    critical-control override: any critical control that is MARGINAL or FAILED
    forces the residual band to HIGH regardless of the numeric score.
    """
    base = band_for_score(exposure_score)

    failing_critical = [
        c for c in control_results
        if c.is_critical and c.outcome in (ControlOutcome.MARGINAL,
                                           ControlOutcome.FAILED)
    ]
    if failing_critical:
        ids = ", ".join(c.control_id for c in failing_critical)
        return ResidualResult(
            raw_score=exposure_score,
            band=Band.HIGH,
            critical_override_applied=True,
            rationale=f"critical control(s) {ids} marginal/failed -> forced HIGH",
        )
    return ResidualResult(
        raw_score=exposure_score,
        band=base,
        critical_override_applied=False,
        rationale=f"score {exposure_score} -> {base.value}",
    )


class RoutingDecision(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    FAST_TRACK = "FAST_TRACK"
    FULL_DILIGENCE = "FULL_DILIGENCE"


@dataclass(frozen=True)
class TriageInput:
    tier: int                 # 1..4 (Tier 3 = lower criticality in BRO's sense)
    special_data: bool        # special category / sensitive data
    sanctions_exposure: bool
    cross_border: bool
    uses_ai: bool
    inherent_band: Band


def route(triage: TriageInput) -> RoutingDecision:
    """
    Straight-through routing per compendium:
      AUTO-APPROVE only when LOW · Tier-3(or 4) · no special data / sanctions /
      cross-border / AI. Otherwise FAST-TRACK (moderate) or FULL DILIGENCE.
    """
    blockers = (triage.special_data or triage.sanctions_exposure
                or triage.cross_border or triage.uses_ai)
    if (triage.inherent_band is Band.LOW and triage.tier >= 3 and not blockers):
        return RoutingDecision.AUTO_APPROVE
    if triage.inherent_band in (Band.HIGH, Band.ELEVATED) or triage.tier == 1:
        return RoutingDecision.FULL_DILIGENCE
    return RoutingDecision.FAST_TRACK
