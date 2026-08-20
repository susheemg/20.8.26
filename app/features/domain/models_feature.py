"""
Group B-G: the full feature data layer.

Extends models_db.py with every remaining domain table the uploaded app needs,
so the new app covers ALL features. Kept in one module for clarity; in a larger
codebase these would split by domain. All inherit the same Base, so a single
create_all builds the whole schema on SQLite or Postgres.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.features.domain.models_db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("engagements.id"), default=None)
    title: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="medium")  # critical/high/medium/low
    status: Mapped[str] = mapped_column(String, default="open")
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Acceptance(Base):
    __tablename__ = "acceptances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("engagements.id"), default=None)
    rationale: Mapped[str] = mapped_column(Text, default="")
    accepted_by: Mapped[str] = mapped_column(String, default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Certification(Base):
    __tablename__ = "certifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    name: Mapped[str] = mapped_column(String)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    artefact_id: Mapped[Optional[str]] = mapped_column(String, default=None)  # mirrored canonical artefact
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"), default=None)
    engagement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("engagements.id"), default=None)
    name: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String, default="other")
    object_uri: Mapped[Optional[str]] = mapped_column(String, default=None)
    next_validation: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FourthParty(Base):
    __tablename__ = "fourth_parties"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    name: Mapped[str] = mapped_column(String)
    service: Mapped[Optional[str]] = mapped_column(String, default=None)
    concentration_flag: Mapped[bool] = mapped_column(Boolean, default=False)


class Monitoring(Base):
    __tablename__ = "monitoring"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    sweep_type: Mapped[str] = mapped_column(String, default="financial")
    status: Mapped[str] = mapped_column(String, default="OK")  # OK/ALERT/CRITICAL
    detail: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Reassessment(Base):
    __tablename__ = "reassessments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[int] = mapped_column(ForeignKey("engagements.id"))
    mode: Mapped[str] = mapped_column(String, default="periodic")  # periodic/triggered/delta
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[int] = mapped_column(ForeignKey("engagements.id"))
    tier: Mapped[str] = mapped_column(String, default="Tier 3")
    terms_json: Mapped[str] = mapped_column(Text, default="{}")
    gap_review: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class IntelResult(Base):
    __tablename__ = "intel_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    engine: Mapped[str] = mapped_column(String)  # financial/reputation/contract/evidence
    score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    band: Mapped[Optional[str]] = mapped_column(String, default=None)
    narrative: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    title: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="medium")
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Offboarding(Base):
    __tablename__ = "offboarding"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[int] = mapped_column(ForeignKey("engagements.id"))
    step_key: Mapped[str] = mapped_column(String)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audience: Mapped[str] = mapped_column(String, default="all")  # vrm/business/all
    event: Mapped[str] = mapped_column(String)
    body: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    to_addr: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[Optional[str]] = mapped_column(Text, default=None)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)  # False = simulation outbox
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String, index=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, default=None)
    # DB-03: subject references promoted out of the JSON payload so the trail can be
    # queried per vendor/engagement without scanning and parsing every row. Populated
    # automatically by audit(); nullable because platform-level events have no subject.
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    engagement_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    prev_hash: Mapped[str] = mapped_column(String)
    entry_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class MethodologyVersion(Base):
    __tablename__ = "methodology_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String)
    note: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("engagements.id"), default=None)
    actor_role: Mapped[str] = mapped_column(String, default="assessor")  # assessor/vendor
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    stage: Mapped[int] = mapped_column(Integer, default=0)          # 0..7 agent stage
    active_agent: Mapped[str] = mapped_column(String, default="bro")
    dossier_json: Mapped[str] = mapped_column(Text, default="{}")   # accumulated verified facts
    # --- session provenance & resumability (v4.25.8) -------------------------------
    # Sessions previously carried no owner, subject or status, so a user could not find
    # their own unfinished conversations and the list could not be access-scoped.
    created_by: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    business_unit: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    subject_label: Mapped[Optional[str]] = mapped_column(String, default=None)  # display name
    status: Mapped[str] = mapped_column(String, default="active", index=True)   # active/completed/abandoned
    # Reassignment: an in-progress conversation can be handed to another user by a
    # controller, assessor or administrator — people leave, go on holiday, or hand
    # over a supplier. created_by is never overwritten, because who started a piece
    # of work is part of the record; assigned_to is who owns it now.
    assigned_to: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    assigned_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("conversation_sessions.id"))
    role: Mapped[str] = mapped_column(String)  # user/agent/system
    agent: Mapped[Optional[str]] = mapped_column(String, default=None)  # agent id when role=agent
    stage: Mapped[int] = mapped_column(Integer, default=0)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AgentLearning(Base):
    """Operator feedback synthesised into a calibrated learning that persists
    and feeds future engagements (self-improving methodology)."""
    __tablename__ = "agent_learnings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rating: Mapped[int] = mapped_column(Integer, default=3)
    agent: Mapped[Optional[str]] = mapped_column(String, default=None)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    issue: Mapped[Optional[str]] = mapped_column(String, default=None)
    note: Mapped[Optional[str]] = mapped_column(Text, default=None)
    text: Mapped[str] = mapped_column(Text)  # synthesised directive
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BackgroundInsight(Base):
    """Background consistency-check finding (Sara) tied to a session."""
    __tablename__ = "background_insights"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("conversation_sessions.id"))
    kind: Mapped[str] = mapped_column(String)  # contradiction/practicality
    severity: Mapped[str] = mapped_column(String, default="medium")
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String)
    event: Mapped[str] = mapped_column(String, default="*")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
