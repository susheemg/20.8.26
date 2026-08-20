"""
Phase 1a: actors, evidence, and trust.

Q1 (both actors share engagements) and Q4 (evidence precedence) make trust a
FIRST-CLASS property of everything entering the system. Every message and
document carries the role of its author; every piece of evidence carries a
source type that determines its precedence.

Trust ladder (highest first):
    ASSESSOR input            - trusted directive, sits above all vendor sources
    -- vendor evidence ladder --
    INDEPENDENT_AUDIT         - SOC 2 Type II, ISAE 3402, pen test, ISO cert
    VENDOR_ATTESTATION        - signed questionnaire / DDQ / vendor form
    VENDOR_CHAT_CLAIM         - assertion made in the adaptive chat

Recency GATES the ladder (it does not override it): a stale top-tier source
keeps its rank but loses weight and is flagged, so a 3-year-old audit never
silently beats a current attestation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum
from typing import Optional


class ActorRole(IntEnum):
    """Who is speaking. Drives visibility boundaries and evidence trust."""
    VENDOR = 1        # supplier-side; claims are assertions to verify
    ASSESSOR = 2      # internal assessor / business lead; trusted input
    SYSTEM = 3        # the platform / AI itself


class Visibility(IntEnum):
    """Who may see an AI artifact. Vendors must never see internal reasoning."""
    INTERNAL_ONLY = 1      # AI reasoning, confidence, escalation decisions
    SHARED = 2             # visible to vendor too (e.g. a question being asked)


class SourceType(IntEnum):
    """Evidence source, ordered so HIGHER int == HIGHER precedence."""
    VENDOR_CHAT_CLAIM = 1
    VENDOR_ATTESTATION = 2
    INDEPENDENT_AUDIT = 3
    ASSESSOR_INPUT = 4     # above the entire vendor ladder


@dataclass(frozen=True)
class Evidence:
    """A single piece of evidence with everything needed to rank and trace it."""
    evidence_id: str
    org_id: str
    engagement_id: str
    source_type: SourceType
    author_role: ActorRole
    claim: str                       # what this evidence asserts
    domain: str                      # which risk domain it speaks to
    captured_on: date
    valid_until: Optional[date] = None   # e.g. audit report expiry; None = no expiry
    document_id: Optional[str] = None    # link to source doc if applicable

    def is_valid_on(self, as_of: date) -> bool:
        return self.valid_until is None or self.valid_until >= as_of


@dataclass(frozen=True)
class ConflictNote:
    """Records that a lower-precedence source contradicted a higher one.
    The contradiction is itself risk-relevant, not just noise to discard."""
    winning_evidence_id: str
    losing_evidence_id: str
    domain: str
    detail: str


@dataclass(frozen=True)
class ResolvedEvidence:
    """Outcome of precedence resolution for one domain/claim cluster."""
    domain: str
    winner: Evidence
    considered: tuple[str, ...]          # all evidence_ids weighed
    conflicts: tuple[ConflictNote, ...]  # contradictions found
    staleness_flag: bool                 # winner was valid but past a freshness hint
