"""
Phase 3a: shadow-mode observation logging.

During shadow mode the AI assesses everything and humans validate everything.
Each pairing of (AI verdict, human decision) is an Observation. These are the
ONLY honest basis for setting auto-deliver thresholds — guessing thresholds in
a risk product means guessing where to trust the machine, which is unacceptable.

An Observation captures, per (domain x provider):
  - what the AI said (tier, confidence)
  - what the human decided (the ground-truth tier)
  - whether the AI's escalation DECISION was itself correct (did it escalate
    the things that needed escalating?) — tracked separately from tier accuracy,
    because in by-exception validation a wrong escalation decision is the real risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class HumanOutcome(str, Enum):
    CONFIRMED = "confirmed"   # human agreed with the AI tier
    CORRECTED = "corrected"   # human changed the AI tier


@dataclass(frozen=True)
class Observation:
    obs_id: str
    org_id: str
    domain: str
    provider: str
    ai_tier: int                 # 1..4 the AI assigned
    ai_confidence: float         # 0..1
    human_tier: int              # 1..4 ground truth from validation
    outcome: HumanOutcome
    ai_would_have_escalated: bool  # what the gate WOULD have decided (shadow)
    human_judged_should_escalate: bool  # did this case truly need a human?
    recorded_at: str

    @property
    def tier_correct(self) -> bool:
        return self.ai_tier == self.human_tier

    @property
    def escalation_correct(self) -> bool:
        """Did the gate's would-be decision match what the case truly needed?"""
        return self.ai_would_have_escalated == self.human_judged_should_escalate

    @property
    def is_silent_miss(self) -> bool:
        """The dangerous case: AI would have auto-delivered, but the case
        actually needed a human (and the AI was wrong on tier)."""
        return (not self.ai_would_have_escalated
                and self.human_judged_should_escalate
                and not self.tier_correct)


class ObservationLog:
    """In-memory store; persistence layer writes these append-only."""

    def __init__(self) -> None:
        self._obs: list[Observation] = []

    def record(
        self,
        obs_id: str,
        org_id: str,
        domain: str,
        provider: str,
        ai_tier: int,
        ai_confidence: float,
        human_tier: int,
        ai_would_have_escalated: bool,
        human_judged_should_escalate: bool,
        recorded_at: Optional[datetime] = None,
    ) -> Observation:
        outcome = (HumanOutcome.CONFIRMED if ai_tier == human_tier
                   else HumanOutcome.CORRECTED)
        obs = Observation(
            obs_id=obs_id, org_id=org_id, domain=domain, provider=provider,
            ai_tier=ai_tier, ai_confidence=ai_confidence, human_tier=human_tier,
            outcome=outcome,
            ai_would_have_escalated=ai_would_have_escalated,
            human_judged_should_escalate=human_judged_should_escalate,
            recorded_at=(recorded_at or datetime.now(timezone.utc)).isoformat(),
        )
        self._obs.append(obs)
        return obs

    def for_domain_provider(self, domain: str, provider: str) -> list[Observation]:
        return [o for o in self._obs
                if o.domain == domain and o.provider == provider]

    def all(self) -> list[Observation]:
        return list(self._obs)
