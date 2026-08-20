"""
Phase 0 domain models: the policy spine.

Three layers:
  1. CanonicalControl  - the industry best-practice baseline (you maintain)
  2. TenantOverlay      - per-org deltas against the baseline
  3. EffectiveControl   - deterministic merge of baseline + overlay (computed)

Design rules baked in:
  - Overlays reference baseline by ID + version (never copy).
  - Custom controls (no baseline parent) are first-class and tagged.
  - The merge is a PURE function: same inputs -> same output, always.
  - org_id is present everywhere even though v1 is single-tenant.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import Optional


class RiskWeight(IntEnum):
    NEGLIGIBLE = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5


class DataClassification(IntEnum):
    """Ordered so applicability thresholds can be compared with >=."""
    PUBLIC = 1
    INTERNAL = 2
    CONFIDENTIAL = 3
    RESTRICTED = 4


@dataclass(frozen=True)
class CanonicalControl:
    """Best-practice baseline control. Immutable; new versions are new objects."""
    control_id: str
    domain: str
    statement: str
    best_practice_refs: tuple[str, ...]
    default_threshold: str
    default_applicability: DataClassification
    risk_weight: RiskWeight
    version: int

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if not self.control_id:
            raise ValueError("control_id is required")


@dataclass(frozen=True)
class ControlOverride:
    """A tenant's delta against one baseline control. None == inherit baseline."""
    control_id: str
    base_version: int  # the baseline version this override was authored against
    threshold_override: Optional[str] = None
    applicability_override: Optional[DataClassification] = None
    risk_weight_override: Optional[RiskWeight] = None
    terminology: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CustomControl:
    """A tenant-only control with no baseline parent. Tagged tenant-origin."""
    control_id: str
    domain: str
    statement: str
    threshold: str
    applicability: DataClassification
    risk_weight: RiskWeight
    version: int = 1


@dataclass(frozen=True)
class TenantOverlay:
    org_id: str
    overrides: dict[str, ControlOverride] = field(default_factory=dict)
    custom_controls: dict[str, CustomControl] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectiveControl:
    """Computed result of merging baseline + overlay. What the AI actually sees."""
    control_id: str
    org_id: str
    domain: str
    statement: str
    threshold: str
    applicability: DataClassification
    risk_weight: RiskWeight
    origin: str               # "baseline" | "baseline+override" | "custom"
    baseline_version: Optional[int]   # None for custom controls
    needs_review: bool        # True when overlay was authored against an older baseline
    terminology: dict[str, str] = field(default_factory=dict)
