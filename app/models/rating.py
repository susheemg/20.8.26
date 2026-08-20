"""
Phase 1b: the rating model (Q2 + Q5).

Two SEPARATE fields, deliberately never collapsed:
  - computed_tier : Tier 1..4, what the AI assessment produces (1 = most critical)
  - governance_flag : Tier 0, human-designated ONLY, sits outside the AI's output space

Keeping them separate means a human Tier 0 designation never destroys the AI's
underlying assessment. Governance can see "AI assessed Tier 2, human designated
Tier 0" — far more useful than one field overwriting the other.

Hierarchy (Q2): per (engagement x domain) -> engagement -> vendor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class Tier(IntEnum):
    """AI-assignable severity. LOWER number == MORE critical (Tier 1 worst)."""
    TIER_1 = 1   # most critical
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 4   # least critical


# Tier 0 is intentionally NOT a member of Tier. It is a governance flag, not a
# computed band, and the rating function can never emit it.
GOVERNANCE_TIER_0 = "TIER_0_CRITICAL_VENDOR"


@dataclass(frozen=True)
class DomainRating:
    engagement_id: str
    domain: str
    computed_tier: Tier
    confidence: float            # from the AI agent; drives escalation later
    rationale: str


@dataclass(frozen=True)
class EngagementRating:
    engagement_id: str
    vendor_id: str
    computed_tier: Tier          # rolled up from domain ratings
    domain_ratings: tuple[DomainRating, ...]
    concentration_applied: bool  # did a concentration overlay move the tier?
    roll_up_method: str


@dataclass(frozen=True)
class VendorRating:
    vendor_id: str
    computed_tier: Tier                  # rolled up from engagements
    governance_flag: Optional[str]       # GOVERNANCE_TIER_0 or None (human only)
    governance_actor: Optional[str]      # who designated Tier 0
    governance_reason: Optional[str]     # reason code for the designation
    engagement_ratings: tuple[EngagementRating, ...]
    concentration_applied: bool

    @property
    def effective_label(self) -> str:
        """What governance reads: Tier 0 surfaces, but computed tier is preserved."""
        if self.governance_flag == GOVERNANCE_TIER_0:
            return f"TIER_0 (computed {self.computed_tier.name})"
        return self.computed_tier.name

    @property
    def is_critical_vendor(self) -> bool:
        return self.governance_flag == GOVERNANCE_TIER_0
