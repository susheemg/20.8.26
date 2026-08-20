"""Performance Management models — SLA register, SLA measurements, and the
Performance Issues register.

The Performance Issues register deliberately mirrors the risk register
(FindingRecord) data model — ID, title, description, category, severity,
source, status, owner, raised_by, due_date, suggested_remediation,
progress_notes, risk acceptance — applied to vendor performance rather than
control/cyber risk.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.features.domain.models_db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SLARecord(Base):
    """A single service-level agreement tracked against an engagement."""
    __tablename__ = "sla_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sla_id: Mapped[str] = mapped_column(String, unique=True)          # SLA-xxxxxx
    engagement_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    contract_id: Mapped[Optional[str]] = mapped_column(String, default=None)

    description: Mapped[str] = mapped_column(String)
    threshold_type: Mapped[str] = mapped_column(String, default="min")  # min | max
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[Optional[str]] = mapped_column(String, default="")
    baseline: Mapped[Optional[float]] = mapped_column(Float, default=None)
    window: Mapped[str] = mapped_column(String, default="monthly")      # monthly | quarterly
    source: Mapped[str] = mapped_column(String, default="manual")       # contract | upload | manual
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SLAMeasurement(Base):
    """An observed value for one SLA in one measurement period.

    period is a normalised key: 'YYYY-MM' for monthly, 'YYYY-Qn' for quarterly.
    One row per (sla_id, period) — upserted.
    """
    __tablename__ = "sla_measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sla_id: Mapped[str] = mapped_column(String, index=True)
    period: Mapped[str] = mapped_column(String)                         # 2026-05 | 2026-Q2
    value: Mapped[Optional[float]] = mapped_column(Float, default=None)
    recorded_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PerformanceIssue(Base):
    """A performance issue — mirrors the risk register (FindingRecord) shape."""
    __tablename__ = "performance_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pis_id: Mapped[str] = mapped_column(String, unique=True)            # PIS-xxxxxx
    engagement_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)

    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    category: Mapped[Optional[str]] = mapped_column(String, default=None)
    severity: Mapped[str] = mapped_column(String, default="Medium")     # Critical/High/Medium/Low
    source: Mapped[str] = mapped_column(String, default="Manual")       # SLA breach/Manual/AI/Incident
    status: Mapped[str] = mapped_column(String, default="Open")         # Open/In Progress/In Review/Risk Accepted/Closed
    owner: Mapped[Optional[str]] = mapped_column(String, default=None)
    raised_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    raised_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    due_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    closed_date: Mapped[Optional[str]] = mapped_column(String, default=None)

    linked_ref: Mapped[Optional[str]] = mapped_column(String, default=None)   # linked SLA / reference
    sla_id: Mapped[Optional[str]] = mapped_column(String, default=None)       # source SLA when raised from breach
    suggested_remediation: Mapped[Optional[str]] = mapped_column(Text, default=None)
    progress_notes: Mapped[str] = mapped_column(Text, default="[]")           # JSON list of {ts,user,note}

    risk_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    acceptance_rationale: Mapped[Optional[str]] = mapped_column(Text, default=None)
    accepted_by: Mapped[Optional[str]] = mapped_column(String, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
