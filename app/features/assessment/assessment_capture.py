"""
Assessment capture — turns a conversational agent session into a structured,
queryable AssessmentRecord mapped to an engagement.

The AI Assessment chat is free-flowing; this distils it into structured fields
(per-stage capture, dossier facts, message/agent counts, detected bands, the
final verdict) plus retains a transcript reference, so the Assessments Data
screen and reporting can query it. Mapped to an engagement; engagement owner
becomes the SPOC; HIGH inherent auto-assigns a load-balanced assessor.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.assessment import agents as A
from app.features.domain import registry_service as RS
from app.features.domain.models_feature import (AgentLearning, BackgroundInsight,
                             ConversationMessage, ConversationSession)
from app.features.domain.registry_models import AssessmentRecord, EngagementRecord


_BANDS = ("HIGH", "ELEVATED", "MODERATE", "LOW")


def _detect_band(text: str) -> Optional[str]:
    up = (text or "").upper()
    for b in _BANDS:  # first/highest mention wins (HIGH checked first)
        if b in up:
            return b
    return None


def build_structured(s: Session, session_id: int) -> dict:
    """Distil a session into a COMPLETE structured capture: the full untruncated
    transcript, every dossier fact, per-stage turns with full bodies, agent turn
    counts, detected bands, the full verdict, plus the background insights raised
    during the session and the calibrated learnings in force. Nothing is dropped —
    the captured record is a self-contained snapshot of the entire conversation."""
    sess = s.get(ConversationSession, session_id)
    msgs = s.scalars(select(ConversationMessage)
                     .where(ConversationMessage.session_id == session_id)
                     .order_by(ConversationMessage.id)).all()
    dossier = json.loads(sess.dossier_json or "{}") if sess else {}
    state = json.loads(sess.state_json or "{}") if sess else {}

    # per-stage capture: collect statements grouped by stage (full bodies, not excerpts)
    stages: dict[int, dict] = {}
    agent_turns: dict[str, int] = {}
    inherent = dossier.get("inherent_band")
    residual = dossier.get("residual_band")
    verdict = None
    for m in msgs:
        if m.role == "agent":
            agent_turns[m.agent] = agent_turns.get(m.agent, 0) + 1
        st = stages.setdefault(m.stage, {"stage": m.stage,
                                         "name": A.STAGES[m.stage].name if 0 <= m.stage < len(A.STAGES) else str(m.stage),
                                         "turns": []})
        st["turns"].append({"role": m.role, "agent": m.agent, "body": m.body or ""})
        if m.role == "agent":
            if not inherent and m.stage in (2, 3):
                inherent = _detect_band(m.body)
            if m.stage == 7:  # decision stage carries the verdict (full text)
                verdict = m.body or ""

    # full transcript — every message, untruncated
    transcript = [{"id": m.id, "role": m.role, "agent": m.agent,
                   "stage": m.stage, "body": m.body or ""} for m in msgs]

    # background insights raised during THIS session
    insights = s.scalars(select(BackgroundInsight)
                         .where(BackgroundInsight.session_id == session_id)
                         .order_by(BackgroundInsight.id)).all()
    # calibrated learnings in force at capture time (methodology snapshot)
    learnings = s.scalars(select(AgentLearning).order_by(AgentLearning.id)).all()

    return {
        "session_id": session_id,
        "final_stage": sess.stage if sess else 0,
        "active_agent": sess.active_agent if sess else None,
        "stages_completed": sorted(stages.keys()),
        "per_stage": list(stages.values()),
        "agent_turns": agent_turns,
        "dossier": dossier,
        "state": state,
        "inherent_band": inherent,
        "residual_band": residual,
        "verdict": verdict,
        "transcript": transcript,
        "message_count": len(msgs),
        "insights": [{"kind": i.kind, "severity": i.severity, "detail": i.detail}
                     for i in insights],
        "learnings": [{"id": l.id, "stage": l.stage, "agent": l.agent,
                       "rating": l.rating, "text": l.text} for l in learnings],
        "insight_count": len(insights),
    }


def capture_session(s: Session, *, session_id: int, engagement_id: str,
                    vendor_id: Optional[str], engagement_owner: Optional[str],
                    assessor_pool: Optional[list[str]] = None) -> AssessmentRecord:
    """Create a NEW AssessmentRecord for an engagement from a chat session, storing
    the complete structured capture. Every capture mints a fresh, immutable record —
    a point-in-time snapshot of the conversation — rather than updating any prior one.
    This preserves a full audit history: re-capturing the same session produces a new
    assessment alongside the earlier one(s), never overwriting them."""
    structured = build_structured(s, session_id)
    inherent = structured.get("inherent_band")

    rec = RS.create_assessment(
        s, engagement_id=engagement_id, vendor_id=vendor_id,
        engagement_owner=engagement_owner, session_id=session_id,
        inherent_band=inherent, residual_band=structured.get("residual_band"),
        assessor_pool=assessor_pool or [])
    rec.structured_json = json.dumps(structured)
    rec.status = "Completed" if structured["final_stage"] >= 7 else "In-Progress"

    # reflect the latest bands onto the engagement record
    eng = s.scalars(select(EngagementRecord).where(
        EngagementRecord.engagement_id == engagement_id)).first()
    if eng:
        if inherent:
            eng.inherent_band = inherent
        if structured.get("residual_band"):
            eng.residual_band = structured["residual_band"]
    s.flush()
    return rec
