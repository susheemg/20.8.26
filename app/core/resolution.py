"""
The resolution engine: baseline + overlay -> effective policy.

This is a PURE, deterministic function. Same inputs always produce the same
EffectiveControl set. No I/O, no clocks, no randomness. That property is what
makes every downstream AI decision auditable and reproducible.

Merge rules:
  - Override value wins where present; otherwise inherit baseline.
  - If an override was authored against an older baseline version than the
    current baseline, the effective control is flagged needs_review=True
    (it is NOT silently dropped, and NOT auto-adopted). This is how
    "best practice stays current without trampling customisation."
  - Custom controls are appended, origin="custom".
  - Terminology maps are carried through for downstream prompt rendering.
"""
from __future__ import annotations

from ..models.policy import (
    CanonicalControl,
    CustomControl,
    EffectiveControl,
    TenantOverlay,
)


def resolve_control(
    baseline: CanonicalControl,
    overlay: TenantOverlay,
) -> EffectiveControl:
    """Merge a single baseline control with the tenant overlay."""
    override = overlay.overrides.get(baseline.control_id)

    if override is None:
        return EffectiveControl(
            control_id=baseline.control_id,
            org_id=overlay.org_id,
            domain=baseline.domain,
            statement=baseline.statement,
            threshold=baseline.default_threshold,
            applicability=baseline.default_applicability,
            risk_weight=baseline.risk_weight,
            origin="baseline",
            baseline_version=baseline.version,
            needs_review=False,
            terminology={},
        )

    needs_review = override.base_version < baseline.version
    return EffectiveControl(
        control_id=baseline.control_id,
        org_id=overlay.org_id,
        domain=baseline.domain,
        statement=baseline.statement,
        threshold=override.threshold_override or baseline.default_threshold,
        applicability=(
            override.applicability_override
            if override.applicability_override is not None
            else baseline.default_applicability
        ),
        risk_weight=(
            override.risk_weight_override
            if override.risk_weight_override is not None
            else baseline.risk_weight
        ),
        origin="baseline+override",
        baseline_version=baseline.version,
        needs_review=needs_review,
        terminology=dict(override.terminology),
    )


def _custom_to_effective(c: CustomControl, org_id: str) -> EffectiveControl:
    return EffectiveControl(
        control_id=c.control_id,
        org_id=org_id,
        domain=c.domain,
        statement=c.statement,
        threshold=c.threshold,
        applicability=c.applicability,
        risk_weight=c.risk_weight,
        origin="custom",
        baseline_version=None,
        needs_review=False,
        terminology={},
    )


def resolve_policy(
    baseline_library: dict[str, CanonicalControl],
    overlay: TenantOverlay,
) -> dict[str, EffectiveControl]:
    """
    Resolve the full effective policy for a tenant.

    Returns a dict keyed by control_id, sorted for deterministic ordering.
    Override entries that reference a control_id not in the baseline are
    ignored here (they belong as custom controls); this keeps the engine
    total — it never raises on stale references, it just doesn't invent them.
    """
    effective: dict[str, EffectiveControl] = {}

    for control_id in sorted(baseline_library):
        effective[control_id] = resolve_control(
            baseline_library[control_id], overlay
        )

    for control_id in sorted(overlay.custom_controls):
        if control_id in effective:
            raise ValueError(
                f"custom control {control_id} collides with a baseline id"
            )
        effective[control_id] = _custom_to_effective(
            overlay.custom_controls[control_id], overlay.org_id
        )

    return effective


def controls_needing_review(
    effective: dict[str, EffectiveControl],
) -> list[str]:
    """Control ids whose overlay lags the current baseline version."""
    return sorted(cid for cid, ec in effective.items() if ec.needs_review)
