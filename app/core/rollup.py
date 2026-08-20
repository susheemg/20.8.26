"""
Phase 1b: the roll-up engine (Q2).

Two roll-ups, both PLUGGABLE and policy-driven (default = worst-of), because
roll-up appetite is per-tenant policy, not hardcoded business logic:

  domain  -> engagement : worst-of by default (any Tier 1 domain => Tier 1
                          engagement). Conservative GRC default; averaging
                          hides a single catastrophic domain.
  engagement -> vendor  : worst-of PLUS a concentration overlay — many
                          mid-tier engagements with one vendor can aggregate
                          UP a tier even when no single engagement is that bad.
                          This is the concentration risk pure roll-up math misses.

Tier 0 is NOT produced here. It is a human governance flag applied separately
(see apply_governance_flag). The roll-up only ever emits Tier 1..4.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..models.rating import (
    DomainRating,
    EngagementRating,
    GOVERNANCE_TIER_0,
    Tier,
    VendorRating,
)


def _worst_of(tiers: Sequence[Tier]) -> Tier:
    """Most critical tier = lowest numeric value."""
    return Tier(min(int(t) for t in tiers))


def roll_up_engagement(
    engagement_id: str,
    vendor_id: str,
    domain_ratings: Sequence[DomainRating],
    method: str = "worst_of",
) -> EngagementRating:
    if not domain_ratings:
        raise ValueError("cannot rate an engagement with no domain ratings")
    if method != "worst_of":
        raise NotImplementedError(f"roll-up method '{method}' not configured")

    tier = _worst_of([d.computed_tier for d in domain_ratings])
    return EngagementRating(
        engagement_id=engagement_id,
        vendor_id=vendor_id,
        computed_tier=tier,
        domain_ratings=tuple(domain_ratings),
        concentration_applied=False,
        roll_up_method=method,
    )


def roll_up_vendor(
    vendor_id: str,
    engagement_ratings: Sequence[EngagementRating],
    *,
    concentration_threshold: int = 3,
    concentration_tier_trigger: Tier = Tier.TIER_3,
    method: str = "worst_of_plus_concentration",
) -> VendorRating:
    """
    Worst-of across engagements, then a concentration overlay:
    if the vendor has >= `concentration_threshold` engagements at or worse than
    `concentration_tier_trigger`, escalate the vendor tier by one band
    (capped at Tier 1). Defaults are tenant-configurable policy.
    """
    if not engagement_ratings:
        raise ValueError("cannot rate a vendor with no engagements")

    base = _worst_of([e.computed_tier for e in engagement_ratings])

    # Concentration overlay.
    at_or_worse = sum(
        1 for e in engagement_ratings
        if int(e.computed_tier) <= int(concentration_tier_trigger)
    )
    concentration_applied = at_or_worse >= concentration_threshold
    final = base
    if concentration_applied and int(base) > int(Tier.TIER_1):
        final = Tier(int(base) - 1)  # escalate one band (lower number = worse)

    return VendorRating(
        vendor_id=vendor_id,
        computed_tier=final,
        governance_flag=None,
        governance_actor=None,
        governance_reason=None,
        engagement_ratings=tuple(engagement_ratings),
        concentration_applied=concentration_applied,
    )


def apply_governance_flag(
    rating: VendorRating,
    actor_role_is_human: bool,
    actor_id: str,
    reason_code: str,
) -> VendorRating:
    """
    Apply Tier 0 designation. ENFORCES human-only (Q5): rejects any non-human
    actor. Preserves computed_tier — the AI assessment is never overwritten.
    """
    if not actor_role_is_human:
        raise PermissionError(
            "Tier 0 (critical vendor) can be designated by a human only"
        )
    return VendorRating(
        vendor_id=rating.vendor_id,
        computed_tier=rating.computed_tier,
        governance_flag=GOVERNANCE_TIER_0,
        governance_actor=actor_id,
        governance_reason=reason_code,
        engagement_ratings=rating.engagement_ratings,
        concentration_applied=rating.concentration_applied,
    )
