"""
Document upload + extraction service.

Closes the loop from "a vendor sends a SOC 2" to "evidence + an Isaac reading
filed against the engagement". Flow:

  upload bytes -> store to object dir -> pick extractor (text/PDF) -> extract
  -> classify (Phase 5) -> if assurance doc, run Isaac -> persist Document +
  IntelResult + Evidence rows -> audit.

Storage is a local directory by default (BRO_UPLOAD_DIR), which stands in for
S3/Blob in production — the service only needs put/get by key, so swapping to a
cloud object store is a small change behind store_bytes/read_bytes.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.ingestion.extract import (
    ClassificationResult, DocType, ExtractedDocument, PdfExtractor,
    TextExtractor, classify,
)
from app.ingestion.pipeline import ClaimCandidate, ingest_document
from app.features.intelligence import intel


_EXTRACTORS = [TextExtractor(), PdfExtractor()]
# documents whose validity we track for expiry chasing
_VALIDITY_DAYS = {
    DocType.INDEPENDENT_AUDIT: 365,
    DocType.QUESTIONNAIRE: 365,
}


def _upload_dir() -> str:
    d = os.environ.get("BRO_UPLOAD_DIR", "/tmp/bro_uploads")
    os.makedirs(d, exist_ok=True)
    return d


def store_bytes(data: bytes, filename: str) -> str:
    """Persist bytes; return an object key. Content-addressed to dedup."""
    digest = hashlib.sha256(data).hexdigest()[:32]
    safe = filename.replace("/", "_").replace("\\", "_")
    key = f"{digest}_{safe}"
    with open(os.path.join(_upload_dir(), key), "wb") as f:
        f.write(data)
    return key


def read_bytes(key: str) -> bytes:
    with open(os.path.join(_upload_dir(), key), "rb") as f:
        return f.read()


def _pick_extractor(filename: str, content_type: str):
    for ex in _EXTRACTORS:
        if ex.can_handle(filename, content_type):
            return ex
    return None


@dataclass(frozen=True)
class UploadResult:
    object_key: str
    doc_type: str
    source_type: int
    classification_confidence: float
    needs_human: bool
    page_count: int
    scanned: bool
    extracted_chars: int
    isaac: Optional[dict]          # Isaac reading if an assurance doc
    evidence_count: int
    next_validation: Optional[str]


def _simple_claims(extracted: ExtractedDocument, cls: ClassificationResult):
    """Deterministic claim extraction: one claim per recognised assurance
    standard / control keyword found. Production swaps in an LLM mapper."""
    text = extracted.text.lower()
    out = []
    if "soc 2" in text or "soc2" in text or "isae 3402" in text:
        out.append(ClaimCandidate("InformationSecurity",
                                  "Independent assurance report on file (SOC 2 / ISAE 3402)"))
    if "iso/iec 27001" in text or "iso 27001" in text:
        out.append(ClaimCandidate("InformationSecurity", "ISO 27001 certification referenced"))
    if "encryption" in text:
        out.append(ClaimCandidate("InformationSecurity", "Encryption controls described"))
    if "business continuity" in text or "disaster recovery" in text:
        out.append(ClaimCandidate("OperationalResilience", "BCP/DR controls described"))
    if not out:
        out.append(ClaimCandidate("Scope", "Document received; no specific control signals matched"))
    return out


def process_upload(
    *,
    data: bytes,
    filename: str,
    content_type: str,
    org_id: str = "org",
    engagement_id: str = "",
    vendor_id: Optional[int] = None,
) -> UploadResult:
    """Full pipeline: store -> extract -> classify -> (Isaac) -> evidence."""
    ex = _pick_extractor(filename, content_type)
    if ex is None:
        raise ValueError(f"no extractor for {filename} ({content_type})")

    key = store_bytes(data, filename)
    extracted = ex.extract(filename, data)
    cls = classify(extracted)
    scanned = extracted.meta.get("scanned") == "True"

    # Run Isaac on assurance documents (or anything with assurance signals).
    isaac_out = None
    if cls.doc_type is DocType.INDEPENDENT_AUDIT or "soc 2" in extracted.text.lower():
        io_ = intel.isaac_evidence(extracted.text)
        isaac_out = {"engine": io_.engine, "score": io_.score, "band": io_.band,
                     "narrative": io_.narrative, "signals": list(io_.signals)}

    # Run ingestion -> typed Evidence (skipped if classification too weak).
    pipeline = ingest_document(
        doc_id=key, org_id=org_id, engagement_id=engagement_id or "n/a",
        extracted=extracted, claim_extractor=_simple_claims,
        classification=cls,
    )

    vd = _VALIDITY_DAYS.get(cls.doc_type)
    next_validation = (
        (date.today() + timedelta(days=vd)).isoformat() if vd else None
    )

    return UploadResult(
        object_key=key,
        doc_type=cls.doc_type.value,
        source_type=int(cls.source_type),
        classification_confidence=cls.confidence,
        needs_human=pipeline.needs_human,
        page_count=extracted.page_count,
        scanned=scanned,
        extracted_chars=len(extracted.text),
        isaac=isaac_out,
        evidence_count=len(pipeline.evidence),
        next_validation=next_validation,
    )
