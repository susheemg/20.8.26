"""Platform Learnings — a durable log of what the system has learned from
previous assessments, to guide future actions.

This is the cross-assessment memory layer described in the self-improvement
model: each completed/captured assessment can deposit one or more structured
learnings (category + insight + provenance), which then inform later work.
Learnings can be captured automatically (deterministic extraction from an
assessment's shape) or added by a human, and each carries an ``applied_count``
so the system can show which lessons are actually being reused.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.features.domain.models_db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


CATEGORIES = [
    "Risk pattern", "Control gap", "Evidence quality", "Sector insight",
    "Process improvement", "Concentration", "Methodology calibration",
]


class PlatformLearning(Base):
    __tablename__ = "platform_learnings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String, default="Risk pattern")
    insight: Mapped[str] = mapped_column(Text)
    source_engagement: Mapped[Optional[str]] = mapped_column(String, default=None)
    source_vendor: Mapped[Optional[str]] = mapped_column(String, default=None)
    source_assessment: Mapped[Optional[str]] = mapped_column(String, default=None)
    origin: Mapped[str] = mapped_column(String, default="auto")   # auto | human
    confidence: Mapped[str] = mapped_column(String, default="Medium")  # High/Medium/Low
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def row(l: PlatformLearning) -> dict:
    return {
        "id": l.id, "category": l.category, "insight": l.insight,
        "source_engagement": l.source_engagement, "source_vendor": l.source_vendor,
        "source_assessment": l.source_assessment, "origin": l.origin,
        "confidence": l.confidence, "applied_count": l.applied_count,
        "created_by": l.created_by,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }


def create(s: Session, *, category: str, insight: str, origin: str = "human",
           confidence: str = "Medium", source_engagement: Optional[str] = None,
           source_vendor: Optional[str] = None, source_assessment: Optional[str] = None,
           created_by: Optional[str] = None) -> PlatformLearning:
    l = PlatformLearning(
        category=category if category in CATEGORIES else "Risk pattern",
        insight=insight.strip(), origin=origin,
        confidence=confidence if confidence in ("High", "Medium", "Low") else "Medium",
        source_engagement=source_engagement, source_vendor=source_vendor,
        source_assessment=source_assessment, created_by=created_by)
    s.add(l)
    s.flush()
    return l


def list_learnings(s: Session, category: Optional[str] = None,
                   vendor_id: Optional[str] = None) -> List[PlatformLearning]:
    stmt = select(PlatformLearning)
    if category:
        stmt = stmt.where(PlatformLearning.category == category)
    if vendor_id:
        stmt = stmt.where(PlatformLearning.source_vendor == vendor_id)
    return s.scalars(stmt.order_by(PlatformLearning.id.desc())).all()


def mark_applied(s: Session, lid: int) -> Optional[PlatformLearning]:
    l = s.get(PlatformLearning, lid)
    if not l:
        return None
    l.applied_count = (l.applied_count or 0) + 1
    s.flush()
    return l


def summary(s: Session) -> dict:
    rows = s.scalars(select(PlatformLearning)).all()
    by_cat: dict = {}
    for l in rows:
        by_cat[l.category] = by_cat.get(l.category, 0) + 1
    applied = sum(1 for l in rows if (l.applied_count or 0) > 0)
    reuse = sum((l.applied_count or 0) for l in rows)
    return {
        "total": len(rows), "by_category": by_cat,
        "auto": sum(1 for l in rows if l.origin == "auto"),
        "human": sum(1 for l in rows if l.origin == "human"),
        "applied_unique": applied, "total_reuse": reuse,
        "top_categories": sorted(by_cat.items(), key=lambda kv: -kv[1])[:3],
    }


# ---------------------------------------------------------------------------
# deterministic capture from a completed/captured assessment
# ---------------------------------------------------------------------------
def capture_from_assessment(s: Session, assessment, findings: Optional[list] = None,
                            actor: str = "system") -> List[PlatformLearning]:
    """Derive 1-3 durable learnings from an assessment's shape.

    Deterministic and idempotent per (assessment, category): re-running does not
    duplicate. With an LLM key the gateway can enrich the phrasing; the
    deterministic capture is always the floor.
    """
    out: List[PlatformLearning] = []
    aid = getattr(assessment, "assessment_id", None)
    eng = getattr(assessment, "engagement_id", None)
    ven = getattr(assessment, "vendor_id", None)
    inherent = getattr(assessment, "inherent_band", None)
    residual = getattr(assessment, "residual_band", None)
    outcome = getattr(assessment, "outcome", None)

    existing = {(l.source_assessment, l.category)
                for l in s.scalars(select(PlatformLearning)
                                   .where(PlatformLearning.source_assessment == aid)).all()}

    def _add(cat, text, conf="Medium"):
        if (aid, cat) in existing:
            return
        out.append(create(s, category=cat, insight=text, origin="auto", confidence=conf,
                          source_engagement=eng, source_vendor=ven,
                          source_assessment=aid, created_by=actor))

    # 1) inherent→residual movement = control-effectiveness signal
    bands = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
    if inherent and residual and inherent in bands and residual in bands:
        drop = bands[inherent] - bands[residual]
        if drop >= 2:
            _add("Control gap", f"Strong control uplift observed on {ven or 'this vendor'}: "
                 f"inherent {inherent} reduced to residual {residual}. Controls of this type "
                 "are effective and can be weighted up in similar engagements.", "High")
        elif drop <= 0 and bands[residual] >= 3:
            _add("Risk pattern", f"Residual risk stayed {residual} on {ven or 'this vendor'} "
                 "despite assessment — controls did not materially reduce exposure; flag for "
                 "enhanced monitoring on comparable suppliers.", "High")

    # 2) findings volume = evidence/quality signal
    nf = len(findings or [])
    if nf >= 5:
        _add("Evidence quality", f"{nf} findings raised in a single engagement — a high-finding "
             "profile; comparable vendors warrant earlier evidence requests and tighter scoping.")
    elif nf == 0 and outcome:
        _add("Process improvement", "Clean assessment with zero findings — the question set and "
             "evidence path used here are a good template for low-risk engagements of this type.")

    # 3) outcome captures a precedent
    if outcome:
        _add("Methodology calibration", f"Outcome '{outcome}' recorded for {ven or 'vendor'} "
             f"(inherent {inherent or '—'} / residual {residual or '—'}). Use as a precedent when "
             "calibrating decisions on similar risk profiles.")
    return out
