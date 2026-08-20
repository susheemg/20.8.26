"""
Materialised policy snapshots.

When an assessment starts, we freeze the effective policy into an immutable,
content-hashed snapshot. If the baseline or overlay changes mid-assessment,
the in-flight assessment keeps its snapshot — no moving goalposts.

The snapshot's content_hash also lets you prove, later, that two assessments
ran against identical policy, or detect that policy drifted between them.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from ..models.policy import EffectiveControl


def _stable_serialise(effective: dict[str, EffectiveControl]) -> str:
    """Deterministic JSON for hashing: sorted keys, no whitespace drift."""
    payload = {
        cid: {
            "control_id": ec.control_id,
            "domain": ec.domain,
            "statement": ec.statement,
            "threshold": ec.threshold,
            "applicability": int(ec.applicability),
            "risk_weight": int(ec.risk_weight),
            "origin": ec.origin,
            "baseline_version": ec.baseline_version,
            "terminology": ec.terminology,
        }
        for cid, ec in sorted(effective.items())
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def content_hash(effective: dict[str, EffectiveControl]) -> str:
    return hashlib.sha256(_stable_serialise(effective).encode()).hexdigest()


@dataclass(frozen=True)
class PolicySnapshot:
    snapshot_id: str
    org_id: str
    created_at: datetime
    content_hash: str
    serialised: str  # the frozen effective policy as stable JSON

    @classmethod
    def create(
        cls,
        snapshot_id: str,
        org_id: str,
        effective: dict[str, EffectiveControl],
    ) -> "PolicySnapshot":
        return cls(
            snapshot_id=snapshot_id,
            org_id=org_id,
            created_at=datetime.now(timezone.utc),
            content_hash=content_hash(effective),
            serialised=_stable_serialise(effective),
        )
