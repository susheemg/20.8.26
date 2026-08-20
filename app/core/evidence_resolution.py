"""
Evidence precedence resolution (Q4).

Rule, in order:
  1. Among CURRENTLY-VALID sources, highest SourceType wins.
  2. A higher-precedence source past a freshness hint keeps its rank but is
     flagged stale (staleness_flag=True) so humans see the gap.
  3. If ALL top-tier sources are invalid/expired, resolution falls to the next
     valid tier down — an expired audit does not beat a current attestation.
  4. Any lower-precedence source that contradicts the winner is recorded as a
     ConflictNote. Resolution picks a winner; it never erases the disagreement.

Precedence order is configurable per tenant later; this is the default ladder.
Pure function — no I/O — so it is fully testable and reproducible.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Optional

from ..models.evidence import (
    ConflictNote,
    Evidence,
    ResolvedEvidence,
    SourceType,
)

# Freshness hints by source type. Past this age a still-"valid" source is
# flagged stale (not discarded). Independent audits are typically annual.
_FRESHNESS_DAYS: dict[SourceType, int] = {
    SourceType.INDEPENDENT_AUDIT: 400,     # ~13 months grace on an annual report
    SourceType.VENDOR_ATTESTATION: 365,
    SourceType.VENDOR_CHAT_CLAIM: 180,
    SourceType.ASSESSOR_INPUT: 365,
}


def _contradicts(a: Evidence, b: Evidence) -> bool:
    """Heuristic placeholder: same domain, opposing claims. In production the
    AI agent supplies the semantic judgement; here we expose the hook and keep
    the structural logic deterministic for testing."""
    return a.domain == b.domain and a.claim.strip() != b.claim.strip()


def resolve_evidence(
    domain: str,
    evidence: Iterable[Evidence],
    as_of: Optional[date] = None,
) -> Optional[ResolvedEvidence]:
    """Resolve a cluster of evidence for one domain into a single winner."""
    as_of = as_of or date.today()
    items = [e for e in evidence if e.domain == domain]
    if not items:
        return None

    valid = [e for e in items if e.is_valid_on(as_of)]
    pool = valid if valid else items  # if nothing valid, fall back to all

    # Highest precedence among the pool; ties broken by most recent capture.
    winner = max(pool, key=lambda e: (int(e.source_type), e.captured_on))

    # Staleness: winner is valid but older than its freshness hint.
    hint = _FRESHNESS_DAYS.get(winner.source_type)
    staleness_flag = bool(
        hint is not None
        and (as_of - winner.captured_on) > timedelta(days=hint)
    )

    # Conflicts: any other item that contradicts the winner.
    conflicts = tuple(
        ConflictNote(
            winning_evidence_id=winner.evidence_id,
            losing_evidence_id=e.evidence_id,
            domain=domain,
            detail=f"{e.source_type.name} contradicts {winner.source_type.name}",
        )
        for e in items
        if e.evidence_id != winner.evidence_id and _contradicts(e, winner)
    )

    return ResolvedEvidence(
        domain=domain,
        winner=winner,
        considered=tuple(e.evidence_id for e in items),
        conflicts=conflicts,
        staleness_flag=staleness_flag,
    )
