"""
Methodology library (admin-only).

Holds the AI-driven TPRM risk-assessment lifecycle methodology document(s).
BRO Chat and ProAssess inject this text into the AI system prompt and follow it
strictly. If no methodology document is present, a directive instructs the model
to follow recognised industry best practice (PRA SS2/21, EBA, DORA, NIST, FSB)
scrupulously. These workflows are AI-only: with no live AI engine they return a
holding statement and do not proceed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Integer, Boolean, Text, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.features.domain.models_db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


BEST_PRACTICE_DIRECTIVE = (
    "NO METHODOLOGY DOCUMENT HAS BEEN LOADED. In its absence, follow recognised "
    "third-party-risk industry best practice scrupulously: PRA SS2/21, the EBA "
    "Outsourcing Guidelines, EU DORA, the FSB third-party toolkit and NIST SP 800-161. "
    "Run a defensible inherent-then-residual assessment: classify the engagement, score "
    "inherent exposure across the control domains, scope due diligence to that exposure, "
    "assess control effectiveness against evidence, derive residual risk, and issue a "
    "decision with rationale. Do not invent facts; ask for what you need."
)


class MethodologyDoc(Base):
    __tablename__ = "methodology_doc"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, default="Methodology")
    content_text: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_by: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def _next_id(s: Session) -> str:
    n = s.scalar(select(MethodologyDoc.id).order_by(MethodologyDoc.id.desc())) or 0
    return f"MTH-{n + 1:04d}"


def list_docs(s: Session) -> list[dict]:
    rows = s.scalars(select(MethodologyDoc).order_by(MethodologyDoc.id.desc())).all()
    return [{"doc_id": r.doc_id, "title": r.title, "filename": r.filename,
             "active": r.active, "chars": len(r.content_text or ""),
             "uploaded_by": r.uploaded_by,
             "created_at": r.created_at.isoformat() if r.created_at else None,
             "preview": (r.content_text or "")[:280]} for r in rows]


def add_doc(s: Session, *, title: str, content_text: str, filename: str = "",
            uploaded_by: str = "") -> MethodologyDoc:
    row = MethodologyDoc(doc_id=_next_id(s), title=title or "Methodology",
                         content_text=content_text or "", filename=filename or "",
                         uploaded_by=uploaded_by or "", active=True)
    s.add(row); s.flush()
    return row


def get_doc(s: Session, doc_id: str) -> Optional[MethodologyDoc]:
    return s.scalars(select(MethodologyDoc).where(MethodologyDoc.doc_id == doc_id)).first()


def set_active(s: Session, doc_id: str, active: bool) -> Optional[MethodologyDoc]:
    d = get_doc(s, doc_id)
    if d:
        d.active = bool(active); d.updated_at = _now()
    return d


def delete_doc(s: Session, doc_id: str) -> bool:
    d = get_doc(s, doc_id)
    if not d:
        return False
    s.delete(d); s.flush()
    return True


def methodology_text(s: Session, cap: int = 12000) -> str:
    """Concatenated active methodology text for prompt injection, capped."""
    rows = s.scalars(select(MethodologyDoc).where(MethodologyDoc.active == True)  # noqa: E712
                     .order_by(MethodologyDoc.id)).all()
    parts = [f"# {r.title}\n{r.content_text}" for r in rows if (r.content_text or "").strip()]
    if not parts:
        return ""
    text = "\n\n".join(parts)
    return text[:cap]


def methodology_directive(s: Session) -> str:
    """The block to inject into every assessment system prompt."""
    txt = methodology_text(s)
    if txt:
        return ("AUTHORITATIVE METHODOLOGY DOCUMENT — you MUST comply with this strictly; "
                "it overrides general defaults where they differ:\n\n" + txt)
    return BEST_PRACTICE_DIRECTIVE
