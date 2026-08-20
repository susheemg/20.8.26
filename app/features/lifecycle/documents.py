"""
Document store + AI-extraction service — the shared spine for:
  CR-5  Certificates (multi-doc upload, AI-read, record per doc)
  CR-12 Contract gap review (upload contract, extract terms)
  CR-4  ProAssess (upload supporting docs for autonomous assessment)

Storage is portable: file bytes are held base64-encoded in a Text column, which
works identically on SQLite (offline/demo) and Postgres (production), and does NOT
depend on local disk (which is ephemeral on Render). Retrieval streams the bytes back.

Extraction is two-layer, mirroring the rest of the platform: a deterministic
text-based extractor that always works offline, with an optional LLM pass layered on
top when an API key is present. Anything the extractor cannot establish is returned
as a gap rather than guessed.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.features.domain.models_db import Base

MAX_BYTES = 15 * 1024 * 1024  # 15 MB per document — untrusted-input guard
ALLOWED_TYPES = {
    "application/pdf", "text/plain", "text/csv",
    "image/png", "image/jpeg", "image/webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StoredDocument(Base):
    """A stored file. Bytes held base64 in `data_b64` (portable, no disk dependency)."""
    __tablename__ = "stored_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String, unique=True)   # DOC-xxxxxx
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    data_b64: Mapped[str] = mapped_column(Text)                # base64 payload
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    engagement_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    purpose: Mapped[Optional[str]] = mapped_column(String, default=None)  # certificate/contract/proassess
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def _next_doc_id(s: Session) -> str:
    from app.features.domain.registry_service import next_id
    try:
        return next_id(s, "document")
    except Exception:
        # fall back if prefix not registered
        n = s.scalar(select(StoredDocument.id).order_by(StoredDocument.id.desc())) or 0
        return f"DOC-{n+1:06d}"


def store_document(s: Session, *, filename: str, content_type: str, data_b64: str,
                   vendor_id: Optional[str] = None, engagement_id: Optional[str] = None,
                   uploaded_by: Optional[str] = None, purpose: Optional[str] = None) -> StoredDocument:
    """Persist an uploaded document. Validates size and type (untrusted input)."""
    try:
        raw = base64.b64decode(data_b64 or "", validate=False)
    except Exception:
        raise ValueError("document payload is not valid base64")
    if len(raw) == 0:
        raise ValueError("empty document")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"document exceeds {MAX_BYTES // (1024*1024)}MB limit")
    ct = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if ct not in ALLOWED_TYPES:
        # permissive fallback: allow but tag generic, never execute
        ct = "application/octet-stream"
    row = StoredDocument(
        doc_id=_next_doc_id(s), filename=filename or "document",
        content_type=ct, size_bytes=len(raw), data_b64=data_b64,
        vendor_id=vendor_id, engagement_id=engagement_id,
        uploaded_by=uploaded_by, purpose=purpose)
    s.add(row); s.flush()
    return row


def get_document(s: Session, doc_id: str) -> Optional[StoredDocument]:
    return s.scalars(select(StoredDocument).where(
        StoredDocument.doc_id == doc_id)).first()


def _decode_text(doc: StoredDocument) -> str:
    """Best-effort text extraction for the deterministic layer. Handles text/csv
    directly; for PDF/docx, attempts a light text pull, else returns empty (a gap)."""
    try:
        raw = base64.b64decode(doc.data_b64 or "")
    except Exception:
        return ""
    ct = doc.content_type or ""
    if ct.startswith("text/") or ct in ("application/csv",):
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    if ct == "application/pdf":
        try:
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                return "\n".join((p.extract_text() or "") for p in pdf.pages[:20])
        except Exception:
            return ""
    # docx: unzip document.xml text
    if "wordprocessingml" in ct:
        try:
            import io, zipfile
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
            return re.sub(r"<[^>]+>", " ", xml)
        except Exception:
            return ""
    return ""


# ---- deterministic extractors (always work offline) ----
_CERT_PATTERNS = {
    "ISO 27001": r"ISO[\s/-]*27001",
    "ISO 9001": r"ISO[\s/-]*9001",
    "ISO 22301": r"ISO[\s/-]*22301",
    "ISO 14001": r"ISO[\s/-]*14001",
    "SOC 2": r"SOC\s*2|SOC\s*II",
    "SOC 1": r"SOC\s*1|SOC\s*I\b",
    "PCI DSS": r"PCI[\s-]*DSS",
    "Cyber Essentials": r"Cyber\s*Essentials",
    "HIPAA": r"HIPAA",
    "GDPR": r"GDPR",
}
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b|\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")


def extract_certificate(s: Session, doc: StoredDocument) -> dict:
    """Extract certificate fields from a document (deterministic, offline)."""
    text = _decode_text(doc)
    gaps = []
    cert_type = None
    for label, pat in _CERT_PATTERNS.items():
        if re.search(pat, text, re.I):
            cert_type = label
            break
    if not cert_type:
        # fall back to filename hints
        fn = (doc.filename or "").lower()
        for label, pat in _CERT_PATTERNS.items():
            if re.search(pat, fn, re.I):
                cert_type = label
                break
    if not cert_type:
        gaps.append("certificate type not detected")
    dates = [d[0] or d[1] for d in _DATE_RE.findall(text)]
    issue_date = dates[0] if dates else None
    expiry_date = dates[1] if len(dates) > 1 else None
    if not expiry_date:
        gaps.append("expiry date not detected")
    issuer = None
    m = re.search(r"(issued by|certification body|auditor)[:\s]+([A-Z][A-Za-z0-9 &.,'-]{2,60})", text, re.I)
    if m:
        issuer = m.group(2).strip()
    return {"artefact_type": cert_type or "certificate", "name": cert_type or (doc.filename or "Certificate"),
            "issue_date": issue_date, "expiry_date": expiry_date, "issuer": issuer,
            "gaps": gaps, "text_len": len(text)}


# contract term checklist (what a well-formed contract should contain)
_CONTRACT_TERMS = {
    "termination_rights": r"terminat",
    "liability_cap": r"limitation of liability|liability cap|aggregate liability",
    "data_protection": r"data protection|GDPR|personal data|DPA\b",
    "audit_rights": r"audit right|right to audit",
    "confidentiality": r"confidential",
    "sla": r"service level|SLA\b|availability",
    "indemnity": r"indemnif",
    "subcontracting": r"sub-?contract|sub-?processor",
    "exit_assistance": r"exit|transition assistance|step-in",
    "insurance": r"insuranc",
    "governing_law": r"governing law|jurisdiction",
    "ip_rights": r"intellectual property|IP rights",
}


def extract_contract_terms(s: Session, doc: StoredDocument) -> dict:
    """Detect which standard contract terms are present vs absent (deterministic)."""
    text = _decode_text(doc)
    present, absent = [], []
    for term, pat in _CONTRACT_TERMS.items():
        (present if re.search(pat, text, re.I) else absent).append(term)
    return {"present": present, "absent": absent, "text_len": len(text),
            "readable": len(text) > 50}


def extract_proassess_signals(s: Session, doc_texts: list) -> dict:
    """Aggregate IRQ-relevant signals from free text + document texts (deterministic).
    Feeds ProAssess's inherent computation; unestablished facts remain gaps."""
    blob = "\n".join(doc_texts).lower()
    signals = {}
    # data classification hints
    cls = []
    if re.search(r"payment card|cardholder|pci|pan\b", blob): cls.append("Payment Card")
    if re.search(r"special category|health data|biometric|racial|religi", blob): cls.append("Special Category Personal")
    if re.search(r"personal data|pii|gdpr|data subject", blob): cls.append("Personal")
    if cls: signals["Q3"] = list(dict.fromkeys(cls))
    # volume
    if re.search(r"million records|>?\s*1[,.]?000[,.]?000|large volume", blob): signals["Q4"] = ">1,000,000"
    # offshore / sub-processors / system access
    if re.search(r"offshore|india|philippines|outside (the )?(eu|uk|us)", blob): signals["Q6"] = "Yes"
    if re.search(r"sub-?processor|sub-?contract|fourth part", blob): signals["Q7"] = "Yes"
    if re.search(r"system access|remote access|privileged access|api integration", blob): signals["Q5"] = "Yes"
    return signals
