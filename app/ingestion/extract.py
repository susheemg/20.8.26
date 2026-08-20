"""
Phase 5a: document classification + extractor interface.

A document's TYPE determines the source_type (and therefore evidence precedence,
Q4). An independent audit PDF outranks a vendor questionnaire outranks a chat
transcript. Misclassifying a document corrupts precedence, so classification is
a first-class, auditable step — and a low-confidence classification is itself a
reason to route to a human rather than guess.

Extraction is pluggable: the TextExtractor here is fully runnable and tested;
PdfExtractor / OcrExtractor are seams to drop production libraries into without
touching the pipeline. The pipeline depends on the Extractor Protocol, not on
any specific parser.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol

from ..models.evidence import SourceType


class DocType(str, Enum):
    INDEPENDENT_AUDIT = "independent_audit"     # SOC 2, ISAE 3402, pen test, ISO
    QUESTIONNAIRE = "questionnaire"             # completed DDQ / vendor form
    VENDOR_FORM = "vendor_form"
    SOW = "scope_of_work"
    CHAT_TRANSCRIPT = "chat_transcript"
    UNKNOWN = "unknown"


# Map document type to the evidence precedence tier it produces.
DOCTYPE_TO_SOURCE: dict[DocType, SourceType] = {
    DocType.INDEPENDENT_AUDIT: SourceType.INDEPENDENT_AUDIT,
    DocType.QUESTIONNAIRE: SourceType.VENDOR_ATTESTATION,
    DocType.VENDOR_FORM: SourceType.VENDOR_ATTESTATION,
    DocType.SOW: SourceType.VENDOR_ATTESTATION,   # contractual, vendor-supplied
    DocType.CHAT_TRANSCRIPT: SourceType.VENDOR_CHAT_CLAIM,
}


@dataclass(frozen=True)
class ExtractedDocument:
    """Normalised output of any extractor: plain text + light structure."""
    text: str
    page_count: int
    tables: tuple[tuple[tuple[str, ...], ...], ...] = ()   # rows of cells
    meta: dict[str, str] = field(default_factory=dict)


class Extractor(Protocol):
    """Every concrete extractor (text, PDF, OCR) implements this."""
    def can_handle(self, filename: str, content_type: str) -> bool: ...
    def extract(self, filename: str, data: bytes) -> ExtractedDocument: ...


class TextExtractor:
    """Handles plain text / CSV-ish uploads. Fully runnable here."""
    def can_handle(self, filename: str, content_type: str) -> bool:
        return (content_type.startswith("text/")
                or filename.lower().endswith((".txt", ".md", ".csv")))

    def extract(self, filename: str, data: bytes) -> ExtractedDocument:
        text = data.decode("utf-8", errors="replace")
        return ExtractedDocument(text=text, page_count=1, meta={"filename": filename})


# --- Production seams: structure ready, parser bodies to drop in ---

class PdfExtractor:
    """Extracts text + tables from PDFs using pdfplumber. Never silently returns
    empty text on a readable PDF (which would understate risk); if a PDF yields
    no extractable text it flags scanned=True so the caller can route to OCR."""
    def can_handle(self, filename: str, content_type: str) -> bool:
        return content_type == "application/pdf" or filename.lower().endswith(".pdf")

    def extract(self, filename: str, data: bytes) -> ExtractedDocument:
        import io
        try:
            import pdfplumber
        except ImportError as e:
            raise NotImplementedError(
                "pdfplumber not installed; pip install pdfplumber") from e

        texts: list[str] = []
        tables: list[tuple[tuple[str, ...], ...]] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t:
                    texts.append(t)
                for tbl in (page.extract_tables() or []):
                    rows = tuple(
                        tuple((cell or "") for cell in row) for row in tbl
                    )
                    if rows:
                        tables.append(rows)
        full = "\n".join(texts)
        scanned = page_count > 0 and not full.strip()
        return ExtractedDocument(
            text=full, page_count=page_count, tables=tuple(tables),
            meta={"filename": filename, "scanned": str(scanned)},
        )


@dataclass(frozen=True)
class ClassificationResult:
    doc_type: DocType
    source_type: SourceType
    confidence: float
    signals: tuple[str, ...]

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < 0.6


# Keyword signals per type. In production this becomes an LLM classifier;
# the deterministic version is testable and a sane fallback.
_SIGNALS: dict[DocType, tuple[str, ...]] = {
    DocType.INDEPENDENT_AUDIT: (
        "soc 2", "soc2", "isae 3402", "service auditor", "independent auditor",
        "iso/iec 27001", "penetration test", "type ii",
    ),
    DocType.QUESTIONNAIRE: (
        "questionnaire", "ddq", "due diligence", "please describe", "vendor response",
    ),
    DocType.SOW: ("statement of work", "scope of work", "deliverables", "milestones"),
    DocType.VENDOR_FORM: ("vendor form", "supplier form", "self-assessment"),
    DocType.CHAT_TRANSCRIPT: ("vendor:", "assessor:", "transcript"),
}


def classify(doc: ExtractedDocument) -> ClassificationResult:
    """Score each type by signal hits; pick the best. Low score -> UNKNOWN and
    low confidence, which the pipeline treats as 'route to a human'."""
    hay = doc.text.lower()
    scores: dict[DocType, int] = {}
    hit_signals: dict[DocType, list[str]] = {}
    for dtype, sigs in _SIGNALS.items():
        hits = [s for s in sigs if s in hay]
        if hits:
            scores[dtype] = len(hits)
            hit_signals[dtype] = hits

    if not scores:
        return ClassificationResult(DocType.UNKNOWN, SourceType.VENDOR_CHAT_CLAIM,
                                    0.0, ())

    best = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = round(scores[best] / total, 3) if total else 0.0
    return ClassificationResult(
        doc_type=best,
        source_type=DOCTYPE_TO_SOURCE[best],
        confidence=confidence,
        signals=tuple(hit_signals[best]),
    )
