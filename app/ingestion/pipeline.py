"""
Phase 5b: the ingestion pipeline.

Turns an uploaded document into typed Evidence objects ready for the precedence
resolver (Phase 1). Steps:

  1. extract  -> normalised text/tables (pluggable extractor)
  2. classify -> DocType + SourceType + confidence
  3. derive validity -> audit reports expire; capture validity window so the
     resolver's recency gating works (an expired SOC 2 won't beat a fresh form)
  4. emit Evidence per (domain, claim) the document supports
  5. dedup -> the same claim from the same source/doc isn't double-counted

Two safety rules:
  - A low-confidence classification routes the WHOLE document to a human before
    its evidence is trusted (PipelineResult.needs_human).
  - Author role is set from the source type, never guessed: audit/questionnaire
    are VENDOR-supplied evidence; the system never silently upgrades trust.

The claim-extraction step is where an LLM does domain mapping in production;
here it's a deterministic, injectable function so the pipeline is testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Iterable, Optional

from ..models.evidence import ActorRole, Evidence, SourceType
from .extract import (
    ClassificationResult, DocType, ExtractedDocument, classify,
)

# Default validity windows by source type (days from capture).
_VALIDITY_DAYS: dict[SourceType, Optional[int]] = {
    SourceType.INDEPENDENT_AUDIT: 365,     # annual reports
    SourceType.VENDOR_ATTESTATION: 365,
    SourceType.VENDOR_CHAT_CLAIM: None,    # no formal expiry
    SourceType.ASSESSOR_INPUT: None,
}


@dataclass(frozen=True)
class ClaimCandidate:
    """A (domain, claim) pair the document supports — produced by claim
    extraction. In production an LLM maps document content to control domains."""
    domain: str
    claim: str


# A claim extractor maps an extracted document to candidate claims.
ClaimExtractor = Callable[[ExtractedDocument, ClassificationResult],
                          list[ClaimCandidate]]


@dataclass(frozen=True)
class PipelineResult:
    evidence: tuple[Evidence, ...]
    classification: ClassificationResult
    needs_human: bool
    reason: Optional[str]


def _author_role_for(source: SourceType) -> ActorRole:
    # Audit/attestation/chat are all VENDOR-supplied evidence in this pipeline.
    # Assessor input never arrives via document ingestion.
    return ActorRole.VENDOR


def ingest_document(
    *,
    doc_id: str,
    org_id: str,
    engagement_id: str,
    extracted: ExtractedDocument,
    claim_extractor: ClaimExtractor,
    captured_on: Optional[date] = None,
    classification: Optional[ClassificationResult] = None,
    id_prefix: str = "ev",
) -> PipelineResult:
    captured_on = captured_on or date.today()
    cls = classification or classify(extracted)

    # Safety gate: low-confidence or unknown classification -> human first.
    if cls.doc_type is DocType.UNKNOWN or cls.is_low_confidence:
        return PipelineResult(
            evidence=(),
            classification=cls,
            needs_human=True,
            reason=f"classification_confidence_{cls.confidence}",
        )

    validity_days = _VALIDITY_DAYS.get(cls.source_type)
    valid_until = (captured_on + timedelta(days=validity_days)
                   if validity_days is not None else None)

    candidates = claim_extractor(extracted, cls)

    # Dedup identical (domain, claim) pairs from this document.
    seen: set[tuple[str, str]] = set()
    evidence: list[Evidence] = []
    for i, cand in enumerate(candidates):
        key = (cand.domain, cand.claim.strip())
        if key in seen:
            continue
        seen.add(key)
        evidence.append(Evidence(
            evidence_id=f"{id_prefix}-{doc_id}-{i}",
            org_id=org_id,
            engagement_id=engagement_id,
            source_type=cls.source_type,
            author_role=_author_role_for(cls.source_type),
            claim=cand.claim.strip(),
            domain=cand.domain,
            captured_on=captured_on,
            valid_until=valid_until,
            document_id=doc_id,
        ))

    return PipelineResult(
        evidence=tuple(evidence),
        classification=cls,
        needs_human=False,
        reason=None,
    )
