"""
Phase 2c: the assessment agent contract.

The agent takes an effective control + the resolved evidence for a domain and
produces a STRUCTURED verdict: tier, confidence, and full provenance. It never
free-texts a decision the system can't trace. Provenance is what lets the audit
chain answer "why did the AI believe this, and what did it disbelieve."

This module defines the verdict contract and the orchestration that ties
resolution -> agent -> escalation together. The actual LLM call goes through
ProviderRegistry; parsing the model's JSON into AgentVerdict is the adapter's
job (kept thin and deterministic). The fake here lets us test orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..models.evidence import ResolvedEvidence
from ..models.policy import EffectiveControl
from ..models.rating import Tier
from .escalation import (
    Decision, DomainGate, EscalationInput, EscalationResult, decide,
)
from .provider import Provider


@dataclass(frozen=True)
class AgentVerdict:
    """Structured output of the assessment agent for one control/domain."""
    control_id: str
    domain: str
    tier: Tier
    confidence: float
    severity: int                  # 1..5, feeds escalation impact
    rationale: str
    provider: Provider
    # Provenance: exactly what the verdict rests on.
    winning_evidence_id: Optional[str]
    considered_evidence_ids: tuple[str, ...]
    conflict_present: bool
    effective_control_origin: str  # baseline | baseline+override | custom
    baseline_version: Optional[int]


class AssessmentAgent(Protocol):
    def assess(
        self,
        control: EffectiveControl,
        resolved: Optional[ResolvedEvidence],
        provider: Provider,
    ) -> AgentVerdict: ...


@dataclass(frozen=True)
class AssessedFinding:
    """Verdict + escalation outcome, ready to deliver or route to a human."""
    verdict: AgentVerdict
    escalation: EscalationResult

    @property
    def goes_to_human(self) -> bool:
        return self.escalation.decision is Decision.ESCALATE


def assess_and_gate(
    control: EffectiveControl,
    resolved: Optional[ResolvedEvidence],
    agent: AssessmentAgent,
    gate: DomainGate,
    *,
    is_tier0_vendor: bool,
    rollup_band_changed: bool,
) -> AssessedFinding:
    """
    Orchestrate one control: agent assesses, escalation engine gates.
    Pulls conflict + needs_review signals straight from the resolved evidence
    and effective control so the human-validation triggers are wired correctly.
    """
    verdict = agent.assess(control, resolved, gate_provider(gate))

    conflict = bool(resolved and resolved.conflicts)
    inp = EscalationInput(
        domain=control.domain,
        provider=verdict.provider.value,
        confidence=verdict.confidence,
        risk_weight=int(control.risk_weight),
        severity=verdict.severity,
        is_tier0_vendor=is_tier0_vendor,
        rollup_band_changed=rollup_band_changed,
        evidence_conflict=conflict,
        policy_needs_review=control.needs_review,
    )
    return AssessedFinding(verdict=verdict, escalation=decide(inp, gate))


def gate_provider(gate: DomainGate) -> Provider:
    return Provider(gate.provider)


@dataclass(frozen=True)
class SafeAssessment:
    """Result of a fail-safe assessment. If the model output could not be
    parsed, finding is None and forced_escalation carries the reason — the
    caller routes it to a human. We NEVER auto-deliver an unreadable verdict."""
    finding: Optional[AssessedFinding]
    parse_failed: bool
    failure_reason: Optional[str]

    @property
    def goes_to_human(self) -> bool:
        return self.parse_failed or (
            self.finding is not None and self.finding.goes_to_human
        )


def safe_assess_and_gate(
    control: EffectiveControl,
    resolved: Optional[ResolvedEvidence],
    agent: AssessmentAgent,
    gate: DomainGate,
    *,
    is_tier0_vendor: bool,
    rollup_band_changed: bool,
) -> SafeAssessment:
    """Wraps assess_and_gate so a verdict that cannot be parsed/validated fails
    SAFE: it becomes a mandatory human escalation rather than crashing or, worse,
    slipping through. Imported lazily to avoid a hard dependency cycle."""
    from .verdict_parser import VerdictParseError
    try:
        finding = assess_and_gate(
            control, resolved, agent, gate,
            is_tier0_vendor=is_tier0_vendor,
            rollup_band_changed=rollup_band_changed,
        )
        return SafeAssessment(finding=finding, parse_failed=False,
                              failure_reason=None)
    except VerdictParseError as e:
        return SafeAssessment(finding=None, parse_failed=True,
                              failure_reason=str(e))
