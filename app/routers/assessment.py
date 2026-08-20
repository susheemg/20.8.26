"""Auto-extracted assessment routes (RouterDeps pattern). See app/routers/deps.py.

Behaviour is byte-identical to the pre-split monolith; per-instance deps are bound
as locals (multi-app isolation), invariant models/imports come from bro_app globals.
"""
from __future__ import annotations

from fastapi import APIRouter
import app.features.admin.rbac as _RBAC
from sqlalchemy import or_ as _or_, func as _func_
from fastapi.responses import (PlainTextResponse, StreamingResponse,
    HTMLResponse, JSONResponse, FileResponse, RedirectResponse)

from .deps import RouterDeps
from ._shared import bind_shared


def build_assessment_router(deps: RouterDeps) -> APIRouter:
    import app.bro_app as _M
    globals().update({k: v for k, v in vars(_M).items() if not k.startswith("__")})
    r = APIRouter()
    app = r
    # Canonical v2 finding lifecycle (matches FindingRecord.status default 'Draft'
    # and the domain.py registry routes). Captured by the handler closures below,
    # fixing a NameError in GET/PUT /api/v2/findings/{fid}. The v1 legacy endpoints
    # deliberately use eng.FINDING_STATUSES for the separate legacy Finding model.
    from app.features.domain.vocab import FINDING_STATUSES  # DB-05: single vocabulary
    db = deps.db
    actor = deps.actor
    require = deps.require
    audit = deps.audit
    notify = deps.notify
    _fb_guidance = deps.fb_guidance
    _ai_live = deps.ai_live
    AI_HOLDING = deps.ai_holding
    engine = deps.engine
    _platform_version = deps.platform_version
    SessionFactory = deps.session_factory
    _sh = bind_shared(deps)
    _monitor_interval = _sh["_monitor_interval"]
    _rmd_row = _sh["_rmd_row"]
    _file_monitoring_report = _sh["_file_monitoring_report"]
    _ai_research = _sh["_ai_research"]
    # --- build-level imports replicated from the pre-split factory ---
    from app.features.admin import identity as IDP
    from app.features.domain.models_db import hash_password as _hash_pw
    import secrets as _secrets
    from app.features.intelligence import sanctions as SANC
    from app.features.domain.registry_models import SanctionsScreening, WatchlistEntry, VendorPerson
    from app.features.lifecycle import monitoring as MON
    from fastapi.responses import PlainTextResponse
    import csv as _csv, io as _io
    from datetime import datetime as _dt2
    from app.features.assessment import agents as _A
    from app.features.assessment import agent_engine as _AE
    from app.features.domain.models_feature import AgentLearning, BackgroundInsight
    from app.features.domain import registry_service as RS
    from app.features.intelligence import financial as FIN
    from app.features.domain.registry_models import (
        IndustryMaster, MaterialGroupMaster, VendorGroup, VendorRecord,
        VendorIndustry, ContactRecord, EngagementRecord, AssessmentRecord,
        FindingRecord, RemediationRecord, FourthPartyRecord, FourthPartyVendor,
        ArtefactRecord, IssueRecord,
    )
    import json as _json2, os as _os2
    from app.features.lifecycle import performance_service as PERF
    from app.features.platform import platform_docs as PDOCS
    from app.features.assessment import learnings as LEARN
    from app.features.admin import integrations as INTEG
    from app.features.admin import content as CONTENT
    from app.features.admin import layout as LAYOUT


    @app.post("/api/v1/findings")
    def create_finding(f: FindingIn, s: Session = Depends(db),
                       u: User = Depends(require("finding.manage"))):
        row = Finding(engagement_id=f.engagement_id, title=f.title, severity=f.severity)
        s.add(row); s.flush()
        audit(s, "finding.raised", u.username, {"finding_id": row.id})
        notify(s, f"Finding raised: {f.title}", "all")
        s.commit()
        return {"finding_id": row.id, "status": row.status,
                "sla_days": eng.SEVERITY_SLA.get(f.severity)}

    @app.post("/api/v1/findings/{fid}/advance")
    def advance_finding(fid: int, s: Session = Depends(db),
                        u: User = Depends(require("finding.manage"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        f = s.get(Finding, fid)
        if not f:
            raise HTTPException(404, "finding not found")
        order = eng.FINDING_STATUSES
        i = min(order.index(f.status) + 1, len(order) - 1)
        f.status = order[i]
        audit(s, "finding.advanced", u.username, {"finding_id": fid, "status": f.status})
        s.commit()
        return {"finding_id": fid, "status": f.status}

    # ===== intelligence engines =====
    @app.post("/api/v1/methodology/version")
    def meth_version(b: MethIn, s: Session = Depends(db),
                     u: User = Depends(require("methodology.version"))):
        s.add(MethodologyVersion(version=b.version, note=b.note))
        audit(s, "methodology.versioned", u.username, {"version": b.version})
        s.commit()
        return {"version": b.version}

    # ===== audit =====
    @app.patch("/api/v1/findings/{fid}")
    def update_finding(fid: int, b: FindingUpdateIn, s: Session = Depends(db),
                       u: User = Depends(require("finding.manage"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        f = s.get(Finding, fid)
        if not f:
            raise HTTPException(404, "finding not found")
        for fld, val in b.model_dump(exclude_none=True).items():
            setattr(f, fld, val)
        audit(s, "finding.updated", u.username, {"finding_id": fid})
        s.commit()
        return {"finding_id": fid, "updated": True}

    @app.post("/api/v1/findings/{fid}/reopen")
    def reopen_finding(fid: int, s: Session = Depends(db),
                       u: User = Depends(require("finding.manage"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        f = s.get(Finding, fid)
        if not f:
            raise HTTPException(404, "finding not found")
        f.status = "open"
        audit(s, "finding.reopened", u.username, {"finding_id": fid})
        s.commit()
        return {"finding_id": fid, "status": "open"}

    # ---- VRM: sign-off + review queue ----
    @app.get("/api/v1/agent/registry")
    def agent_registry(u: User = Depends(require("engagement.view"))):
        return {"agents": _A.AGENTS,
                "stages": [{"id": s.id, "name": s.name, "short": s.short} for s in _A.STAGES],
                "methodology": _A.METHODOLOGY}

    def _touch_session(sess, dossier=None):
        """Keep session provenance current so Previous Chats can list and rank it.

        Records last activity, and lifts the supplier/subject out of the dossier once
        the conversation has established it — without this the list shows only
        "Session 12" and is useless for picking up where you left off."""
        from datetime import datetime as _dt, timezone as _tz
        try:
            sess.updated_at = _dt.now(_tz.utc).replace(tzinfo=None)
            d = dossier if isinstance(dossier, dict) else {}
            if not sess.vendor_id:
                _v = d.get("vendor_id") or d.get("vendorId")
                if isinstance(_v, str) and _v.startswith("VEN-"):
                    sess.vendor_id = _v
            if not sess.subject_label:
                for k in ("vendor", "vendor_name", "supplier", "supplier_name",
                          "company", "legal_name", "engagement_title", "service"):
                    _n = d.get(k)
                    if isinstance(_n, str) and _n.strip():
                        sess.subject_label = _n.strip()[:120]
                        break
        except Exception:
            pass

    @app.post("/api/v1/agent/sessions")
    def open_session(b: ChatSessionIn, s: Session = Depends(db),
                     u: User = Depends(require("engagement.view"))):
        # v4.25.8: stamp provenance so the session can be found, resumed and scoped.
        _bu = None
        try:
            _bus = _RBAC.user_business_units(s, u)
            _bu = ",".join(sorted(_bus)) if _bus else None
        except Exception:
            pass
        sess = ConversationSession(engagement_id=b.engagement_id, actor_role="assessor",
                                   stage=0, active_agent="bro", dossier_json="{}",
                                   created_by=u.username, business_unit=_bu,
                                   status="active")
        s.add(sess); s.flush()
        opener = ("Bro here — your Risk Oracle. Exposure first. Controls second. Verdict last. "
                  "Drop everything you have on this engagement, or tell me about the supplier and "
                  "we start at intake.")
        s.add(ConversationMessage(session_id=sess.id, role="agent", agent="bro",
                                  stage=0, body=opener))
        audit(s, "agent.session_opened", u.username, {"session_id": sess.id})
        s.commit()
        return {"session_id": sess.id, "stage": 0, "active_agent": "bro"}

    # ---- Previous Chats: resumable BroAssess sessions (v4.25.8) -------------------
    def _session_scope_filter(s, u, stmt):
        """Access scope for chat history: admin / assessor / controller see all;
        a buyer sees only sessions from their business unit(s); anyone else sees
        only their own. Mirrors the vendor-scoping rule so the two cannot drift."""
        rk = u.role.key if u.role else None
        if rk in ("admin", "vrm", "controller", "exec"):
            return stmt
        if rk == "buyer":
            bus = _RBAC.user_business_units(s, u)
            if not bus:
                return stmt.where(ConversationSession.created_by == u.username)
            return stmt.where(_or_(ConversationSession.business_unit.in_(bus),
                                  ConversationSession.created_by == u.username))
        return stmt.where(ConversationSession.created_by == u.username)

    @app.get("/api/v1/agent/sessions")
    def list_sessions(s: Session = Depends(db),
                      u: User = Depends(require("engagement.view")),
                      status: str = "", limit: int = 50):
        """List BroAssess conversations, most recently active first.

        Default view is unfinished work — the point of the feature is resuming a
        conversation you had to abandon. Completed sessions carry their assessment
        id so the outcome can be opened directly."""
        from app.features.domain.registry_models import AssessmentRecord
        stmt = _session_scope_filter(s, u, select(ConversationSession))
        rows = s.scalars(stmt.order_by(
            ConversationSession.updated_at.desc().nullslast(),
            ConversationSession.id.desc()).limit(max(1, min(int(limit or 50), 200)))).all()
        # resolve assessments in one query rather than per row
        sids = [r.id for r in rows]
        amap = {}
        if sids:
            for a in s.scalars(select(AssessmentRecord)
                               .where(AssessmentRecord.session_id.in_(sids))).all():
                amap[a.session_id] = a
        n_stages = len(_A.STAGES)
        out = []
        for r in rows:
            a = amap.get(r.id)
            done = bool(a)
            msgs = s.scalar(select(_func_.count()).select_from(ConversationMessage)
                            .where(ConversationMessage.session_id == r.id)) or 0
            st = "completed" if done else (r.status or "active")
            if status and st != status:
                continue
            out.append({
                "session_id": r.id,
                "subject": r.subject_label or (f"Supplier {r.vendor_id}" if r.vendor_id
                                               else "Untitled conversation"),
                "vendor_id": r.vendor_id,
                "stage": r.stage, "stage_name": (_A.STAGES[r.stage].name
                                                 if 0 <= r.stage < n_stages else "—"),
                "stages_total": n_stages,
                "progress_pct": int(round(((r.stage + (1 if done else 0)) / n_stages) * 100))
                                 if not done else 100,
                "active_agent": r.active_agent,
                "status": st,
                "messages": msgs,
                "created_by": r.created_by,
                "business_unit": r.business_unit,
                "assessment_id": (a.assessment_id if a else None),
                "outcome": (a.outcome if a else None),
                "residual_band": (a.residual_band if a else None),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": (r.updated_at or r.created_at).isoformat()
                              if (r.updated_at or r.created_at) else None,
            })
        return {"sessions": out, "count": len(out)}

    # ═══ Conversation history: BroAssess + ProAssess in one place ═══════════════
    def _conv_scope(s, u, stmt):
        """Who may see which conversations. Assessor, controller and administrator see
        all — they are the review functions and cannot review what they cannot see. A
        buyer sees their business unit's work plus anything assigned to them. Everyone
        else sees only their own."""
        rk = u.role.key if u.role else None
        if rk in ("admin", "vrm", "controller"):
            return stmt
        if rk == "buyer":
            bus = _RBAC.user_business_units(s, u)
            conds = [ConversationSession.created_by == u.username,
                     ConversationSession.assigned_to == u.username]
            if bus:
                conds.append(ConversationSession.business_unit.in_(bus))
            return stmt.where(_or_(*conds))
        return stmt.where(_or_(ConversationSession.created_by == u.username,
                               ConversationSession.assigned_to == u.username))

    def _may_assign(u) -> bool:
        return (u.role.key if u.role else None) in ("admin", "vrm", "controller")

    @app.get("/api/v1/conversations")
    def conversation_history(s: Session = Depends(db),
                             u: User = Depends(require("engagement.view")),
                             status: str = "", owner: str = "", limit: int = 200):
        """Every conversation this user may see, BroAssess and ProAssess together.

        The objective is visibility of previous actions and continuity: an in-progress
        conversation can be resumed, and a concluded one opens the assessment it
        produced along with its engagement and supplier records."""
        from app.features.domain.registry_models import (AssessmentRecord,
                                                         EngagementRecord, VendorRecord)
        out = []

        # --- BroAssess conversations -----------------------------------------
        rows = s.scalars(_conv_scope(s, u, select(ConversationSession))
                         .order_by(ConversationSession.updated_at.desc().nullslast(),
                                   ConversationSession.id.desc()).limit(limit)).all()
        sids = [r.id for r in rows]
        amap = {}
        if sids:
            for a in s.scalars(select(AssessmentRecord)
                               .where(AssessmentRecord.session_id.in_(sids))).all():
                amap[a.session_id] = a
        n_stages = len(_A.STAGES)
        for r in rows:
            a = amap.get(r.id)
            concluded = bool(a)
            msgs = s.scalar(select(_func_.count()).select_from(ConversationMessage)
                            .where(ConversationMessage.session_id == r.id)) or 0
            out.append({
                "kind": "BroAssess", "ref": r.id, "session_id": r.id,
                "subject": r.subject_label or (f"Supplier {r.vendor_id}" if r.vendor_id
                                               else "Untitled conversation"),
                "vendor_id": r.vendor_id, "business_unit": r.business_unit,
                "status": "concluded" if concluded else "in_progress",
                "stage": r.stage, "stages_total": n_stages,
                "stage_name": (_A.STAGES[r.stage].name
                               if 0 <= r.stage < n_stages else "—"),
                "progress_pct": 100 if concluded else int(round(r.stage / n_stages * 100)),
                "messages": msgs,
                "started_by": r.created_by, "owner": r.assigned_to or r.created_by,
                "assigned_to": r.assigned_to, "assigned_by": r.assigned_by,
                "assessment_id": (a.assessment_id if a else None),
                "engagement_id": (a.engagement_id if a else None),
                "outcome": (a.outcome if a else None),
                "residual_band": (a.residual_band if a else None),
                "resumable": not concluded,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": (r.updated_at or r.created_at).isoformat()
                              if (r.updated_at or r.created_at) else None})

        # --- ProAssess runs ---------------------------------------------------
        astmt = select(AssessmentRecord).where(AssessmentRecord.session_id.is_(None))
        allowed = _RBAC.scoped_vendor_ids(s, u)
        if allowed is not None:
            astmt = astmt.where(AssessmentRecord.vendor_id.in_(allowed or ["__none__"]))
        aruns = s.scalars(astmt.order_by(AssessmentRecord.id.desc()).limit(limit)).all()
        vids = {r.vendor_id for r in aruns if r.vendor_id}
        vmap = ({v.vendor_id: v.legal_name for v in s.scalars(
                 select(VendorRecord).where(VendorRecord.vendor_id.in_(vids))).all()}
                if vids else {})
        for r in aruns:
            out.append({
                "kind": "ProAssess", "ref": r.assessment_id, "session_id": None,
                "subject": vmap.get(r.vendor_id) or r.vendor_id or "—",
                "vendor_id": r.vendor_id, "business_unit": None,
                # ProAssess is single-shot: there is nothing to resume, so it is
                # concluded the moment a record exists.
                "status": "concluded", "stage": 7, "stages_total": 7,
                "stage_name": "Decision", "progress_pct": 100, "messages": 0,
                "started_by": getattr(r, "assessor_user", None),
                "owner": getattr(r, "assessor_user", None),
                "assigned_to": None, "assigned_by": None,
                "assessment_id": r.assessment_id, "engagement_id": r.engagement_id,
                "outcome": r.outcome, "residual_band": r.residual_band,
                "resumable": False,
                "created_at": (r.created_at.isoformat()
                               if getattr(r, "created_at", None) else None),
                "updated_at": (r.created_at.isoformat()
                               if getattr(r, "created_at", None) else None)})

        if status:
            out = [o for o in out if o["status"] == status]
        if owner:
            out = [o for o in out if (o.get("owner") or "") == owner]
        out.sort(key=lambda o: (o.get("updated_at") or ""), reverse=True)
        return {"conversations": out[:limit], "count": len(out[:limit]),
                "in_progress": sum(1 for o in out if o["status"] == "in_progress"),
                "concluded": sum(1 for o in out if o["status"] == "concluded"),
                "can_assign": _may_assign(u), "viewer": u.username,
                "scope": ("all" if (u.role.key if u.role else "") in
                          ("admin", "vrm", "controller") else "scoped")}

    @app.post("/api/v1/conversations/{sid}/assign")
    def conversation_assign(sid: int, body: dict = Body(...), s: Session = Depends(db),
                            u: User = Depends(require("engagement.view"))):
        """Hand an in-progress conversation to another user.

        Only a controller, assessor or administrator may reassign, because handing
        someone else's unfinished assessment to a third party is a supervisory act.
        `created_by` is never overwritten — who started the work stays on the record."""
        if not _may_assign(u):
            raise HTTPException(403, "only an assessor, controller or administrator "
                                     "may reassign a conversation")
        to = (body.get("assigned_to") or "").strip()
        if not to:
            raise HTTPException(400, "assigned_to required")
        target = s.scalars(select(User).where(User.username == to)).first()
        if not target or not target.is_active:
            raise HTTPException(404, f"no active user '{to}'")
        sess = s.get(ConversationSession, sid)
        if not sess:
            raise HTTPException(404, "conversation not found")
        from app.features.domain.registry_models import AssessmentRecord
        if s.scalars(select(AssessmentRecord)
                     .where(AssessmentRecord.session_id == sid)).first():
            raise HTTPException(409, "this conversation has concluded and produced an "
                                     "assessment; there is nothing to hand over")
        from datetime import datetime as _dt, timezone as _tz
        prior = sess.assigned_to or sess.created_by
        sess.assigned_to = to
        sess.assigned_by = u.username
        sess.assigned_at = _dt.now(_tz.utc).replace(tzinfo=None)
        audit(s, "conversation.reassigned", u.username,
              {"session_id": sid, "from": prior, "to": to,
               "vendor_id": sess.vendor_id})
        s.commit()
        return {"ok": True, "session_id": sid, "from": prior, "to": to,
                "assigned_by": u.username}

    @app.get("/api/v2/proassess/history")
    def proassess_history(s: Session = Depends(db),
                          u: User = Depends(require("engagement.view")),
                          limit: int = 50):
        """Previous ProAssess runs with their outcome and assessment id.

        ProAssess is single-shot, so its history is the assessment records it
        produced — there is no partial run to resume."""
        from app.features.domain.registry_models import (AssessmentRecord,
                                                         EngagementRecord, VendorRecord)
        stmt = select(AssessmentRecord)
        allowed = _RBAC.scoped_vendor_ids(s, u)
        if allowed is not None:
            stmt = stmt.where(AssessmentRecord.vendor_id.in_(allowed or ["__none__"]))
        rows = s.scalars(stmt.order_by(AssessmentRecord.id.desc())
                         .limit(max(1, min(int(limit or 50), 200)))).all()
        vids = {r.vendor_id for r in rows if r.vendor_id}
        vmap = {}
        if vids:
            vmap = {v.vendor_id: v.legal_name for v in s.scalars(
                select(VendorRecord).where(VendorRecord.vendor_id.in_(vids))).all()}
        eids = {r.engagement_id for r in rows if r.engagement_id}
        emap = {}
        if eids:
            emap = {e.engagement_id: e.title for e in s.scalars(
                select(EngagementRecord).where(EngagementRecord.engagement_id.in_(eids))).all()}
        return {"runs": [{
            "assessment_id": r.assessment_id,
            "vendor_id": r.vendor_id,
            "vendor": vmap.get(r.vendor_id) or r.vendor_id or "—",
            "engagement_id": r.engagement_id,
            "engagement": emap.get(r.engagement_id) or r.engagement_id or "—",
            "status": r.status, "outcome": r.outcome,
            "inherent_band": r.inherent_band, "residual_band": r.residual_band,
            "session_id": r.session_id,
            "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
        } for r in rows], "count": len(rows)}

    @app.get("/api/v1/agent/sessions/{sid}")
    def get_session(sid: int, s: Session = Depends(db),
                    u: User = Depends(require("engagement.view"))):
        sess = s.get(ConversationSession, sid)
        if not sess:
            raise HTTPException(404, "session not found")
        msgs = s.scalars(select(ConversationMessage)
                         .where(ConversationMessage.session_id == sid)
                         .order_by(ConversationMessage.id)).all()
        insights = s.scalars(select(BackgroundInsight)
                             .where(BackgroundInsight.session_id == sid)
                             .order_by(BackgroundInsight.id.desc())).all()
        learnings = s.scalars(select(AgentLearning).order_by(AgentLearning.id.desc())).all()
        from app.features.lifecycle.documents import StoredDocument as _SD
        _docs = s.scalars(select(_SD).where(_SD.purpose == f"broassess:{sid}")
                          .order_by(_SD.id)).all()
        return {
            "session_id": sess.id, "stage": sess.stage, "active_agent": sess.active_agent,
            "dossier": json.loads(sess.dossier_json or "{}"),
            "messages": [{"id": m.id, "role": m.role, "agent": m.agent,
                          "stage": m.stage, "body": m.body} for m in msgs],
            "insights": [{"kind": i.kind, "severity": i.severity, "detail": i.detail} for i in insights],
            "learnings": [{"id": l.id, "text": l.text, "stage": l.stage} for l in learnings],
            "documents": [{"doc_id": d.doc_id, "filename": d.filename,
                           "content_type": d.content_type, "size_bytes": d.size_bytes,
                           "uploaded_by": d.uploaded_by,
                           "created_at": d.created_at.isoformat() if d.created_at else None}
                          for d in _docs],
        }

    # ---- in-conversation document upload (stored in DB, linked for audit) ----
    @app.post("/api/v1/agent/sessions/{sid}/documents")
    def agent_upload_docs(sid: int, b: dict = Body(...), s: Session = Depends(db),
                          u: User = Depends(require("engagement.view"))):
        """Store files uploaded during a BroAssess conversation. Each file is persisted
        in the document store, tagged to this session (purpose 'broassess:<sid>') and to
        the engagement when the session has one, so it is retrievable for audit. On
        capture-to-assessment the tag is re-linked to the resulting engagement/vendor."""
        sess = s.get(ConversationSession, sid)
        if not sess:
            raise HTTPException(404, "session not found")
        from app.features.lifecycle import documents as DOCS
        files = b.get("files") or []
        if not files:
            raise HTTPException(400, "no files supplied")
        eng_ref = str(sess.engagement_id) if sess.engagement_id else None
        stored = []
        for f in files:
            try:
                d = DOCS.store_document(
                    s, filename=f.get("filename") or "document",
                    content_type=f.get("content_type") or "application/octet-stream",
                    data_b64=f.get("data_b64") or "",
                    engagement_id=eng_ref, uploaded_by=u.username,
                    purpose=f"broassess:{sid}")
            except ValueError as e:
                raise HTTPException(422, str(e))
            stored.append({"doc_id": d.doc_id, "filename": d.filename,
                           "content_type": d.content_type, "size_bytes": d.size_bytes})
            s.add(ConversationMessage(
                session_id=sid, role="system", agent="bro", stage=sess.stage,
                body=f"📎 Document received — **{d.filename}** "
                     f"({max(1, (d.size_bytes or 0) // 1024)} KB), stored for audit as {d.doc_id}. "
                     f"I'll factor it into the assessment."))
        audit(s, "agent.documents_uploaded", u.username,
              {"session_id": sid, "count": len(stored),
               "doc_ids": [x["doc_id"] for x in stored]})
        s.commit()
        return {"session_id": sid, "uploaded": stored}

    @app.get("/api/v1/agent/sessions/{sid}/documents")
    def agent_list_docs(sid: int, s: Session = Depends(db),
                        u: User = Depends(require("engagement.view"))):
        from app.features.lifecycle.documents import StoredDocument as _SD
        rows = s.scalars(select(_SD).where(_SD.purpose == f"broassess:{sid}")
                         .order_by(_SD.id)).all()
        return {"documents": [{"doc_id": d.doc_id, "filename": d.filename,
                "content_type": d.content_type, "size_bytes": d.size_bytes,
                "uploaded_by": d.uploaded_by,
                "created_at": d.created_at.isoformat() if d.created_at else None} for d in rows]}

    @app.get("/api/v1/agent/documents/{doc_id}/download")
    def agent_download_doc(doc_id: str, s: Session = Depends(db),
                           u: User = Depends(require("engagement.view"))):
        from app.features.lifecycle import documents as DOCS
        import base64 as _b64
        d = DOCS.get_document(s, doc_id)
        if not d:
            raise HTTPException(404, "document not found")
        try:
            raw = _b64.b64decode(d.data_b64 or "", validate=False)
        except Exception:
            raise HTTPException(500, "document payload corrupt")
        return Response(content=raw, media_type=d.content_type or "application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{d.filename}"'})

    @app.post("/api/v1/agent/send")
    def agent_send(b: ChatSendIn, s: Session = Depends(db),
                   u: User = Depends(require("engagement.view"))):
        sess = s.get(ConversationSession, b.session_id)
        if not sess:
            raise HTTPException(404, "session not found")
        dossier = json.loads(sess.dossier_json or "{}")
        learn_texts = [l.text for l in s.scalars(select(AgentLearning)).all()]
        # prior conversation (before this message) — passed to the model as memory
        _prior = s.scalars(select(ConversationMessage)
                           .where(ConversationMessage.session_id == sess.id)
                           .order_by(ConversationMessage.id)).all()
        history = [{"role": m.role, "agent": m.agent, "body": m.body}
                   for m in _prior if m.role in ("user", "agent")]

        # record the user message
        s.add(ConversationMessage(session_id=sess.id, role="user", stage=sess.stage,
                                  body=b.message))

        # AI-only workflow: without a live AI engine, do not proceed — hold.
        if not _ai_live():
            s.add(ConversationMessage(session_id=sess.id, role="agent", agent="bro",
                                      stage=sess.stage, body=AI_HOLDING))
            s.commit()
            return {"session_id": sess.id, "stage": sess.stage, "active_agent": "bro",
                    "advanced": False, "holding": True,
                    "produced": [{"agent": "bro", "body": AI_HOLDING}], "stage_complete": None}

        from app.features.assessment import methodology as _M
        _meth = _M.methodology_directive(s)
        _briefs = {aid: PROMPTS.resolve(s, f"agent_persona_{aid}") for aid in _A.AGENTS}

        # background consistency check (Sara, silent) — persist insights
        for ins in _AE.consistency_check(dossier, b.message, learn_texts):
            detail = ins.get("issue") or ins.get("concern") or ""
            if ins.get("with"):
                detail += f" (↳ {ins['with']})"
            if ins.get("claim"):
                detail += f" (↳ \"{ins['claim']}\")"
            s.add(BackgroundInsight(session_id=sess.id, kind=ins["kind"],
                                    severity=ins.get("severity", "medium"), detail=detail))

        # choose agent: explicit mention > current floor holder > stage owner
        target = b.agent if (b.agent in _A.AGENTS) else \
            (sess.active_agent if sess.active_agent in _A.AGENTS else _A.route_next_agent(sess.stage))

        # run the agent turn (deterministic-local or live)
        _deep = bool(getattr(b, "deep", False))
        turn = _AE.run_turn(target, sess.stage, dossier, learn_texts, b.message, _meth, _briefs, deep=_deep, history=history)
        produced = []
        _du = dict(turn.dossier_update or {})

        # follow up to two handoffs to keep it bounded
        hops = 0
        while turn.handoff and hops < 2:
            s.add(ConversationMessage(session_id=sess.id, role="agent",
                                      agent=turn.agent_id, stage=sess.stage, body=turn.body))
            produced.append({"agent": turn.agent_id, "body": turn.body})
            target = turn.handoff
            turn = _AE.run_turn(target, sess.stage, dossier, learn_texts, b.message, _meth, _briefs, deep=_deep, history=history)
            if turn.dossier_update:
                _du.update(turn.dossier_update)
            hops += 1

        s.add(ConversationMessage(session_id=sess.id, role="agent",
                                  agent=turn.agent_id, stage=sess.stage, body=turn.body))
        produced.append({"agent": turn.agent_id, "body": turn.body})
        sess.active_agent = turn.agent_id

        # persist the dossier: merge structured captures + accumulate the user's answer, so the
        # engagement picture grows across turns. (Previously the dossier was never written back,
        # so the model saw "(empty)" every turn and looped on intake.)
        if _du:
            dossier.update(_du)
        if b.message and b.message.strip():
            _notes = dossier.setdefault("intake_notes", [])
            _notes.append(b.message.strip()[:400])
            dossier["intake_notes"] = _notes[-40:]
        sess.dossier_json = json.dumps(dossier)
        _touch_session(sess, dossier)

        advanced = False
        if turn.stage_complete and sess.stage < len(_A.STAGES) - 1:
            sess.stage += 1
            sess.active_agent = _A.route_next_agent(sess.stage)
            advanced = True
            s.add(ConversationMessage(session_id=sess.id, role="system", agent="bro",
                                      stage=sess.stage,
                                      body=f"Stage advanced — {turn.stage_complete} Now at Stage "
                                           f"{sess.stage}: {_A.STAGES[sess.stage].name}."))

        audit(s, "agent.turn", u.username,
              {"session_id": sess.id, "agent": turn.agent_id, "advanced": advanced})
        s.commit()
        return {"session_id": sess.id, "stage": sess.stage,
                "active_agent": sess.active_agent, "advanced": advanced,
                "produced": produced, "stage_complete": turn.stage_complete}

    @app.post("/api/v1/agent/stream")
    def agent_stream(b: ChatSendIn, s: Session = Depends(db),
                     u: User = Depends(require("engagement.view"))):
        """Near-real-time chat: streams the lead agent's reply token-by-token over
        SSE (single-pass, fast-fail). The non-streaming /agent/send remains for the
        full multi-agent orchestration. Falls back to the holding message when AI
        is not live, streamed instantly."""
        from fastapi.responses import StreamingResponse
        sess = s.get(ConversationSession, b.session_id)
        if not sess:
            raise HTTPException(404, "session not found")
        dossier = json.loads(sess.dossier_json or "{}")
        learn_texts = [l.text for l in s.scalars(select(AgentLearning)).all()]
        _prior = s.scalars(select(ConversationMessage)
                           .where(ConversationMessage.session_id == sess.id)
                           .order_by(ConversationMessage.id)).all()
        history = [{"role": m.role, "agent": m.agent, "body": m.body}
                   for m in _prior if m.role in ("user", "agent")]
        s.add(ConversationMessage(session_id=sess.id, role="user", stage=sess.stage,
                                  body=b.message))
        # background consistency check (Sara, silent) — persist insights
        for ins in _AE.consistency_check(dossier, b.message, learn_texts):
            detail = ins.get("issue") or ins.get("concern") or ""
            if ins.get("with"):
                detail += f" (↳ {ins['with']})"
            if ins.get("claim"):
                detail += f" (↳ \"{ins['claim']}\")"
            s.add(BackgroundInsight(session_id=sess.id, kind=ins["kind"],
                                    severity=ins.get("severity", "medium"), detail=detail))
        s.commit()

        live = _ai_live()
        sid = sess.id
        stage = sess.stage
        # who speaks now: explicit @mention > the agent currently holding the floor
        # (set by the previous turn's handoff / stage change) > the stage's default owner.
        target = b.agent if (b.agent in _A.AGENTS) else \
            (sess.active_agent if sess.active_agent in _A.AGENTS else _A.route_next_agent(stage))
        from app.features.assessment import methodology as _M
        _meth = _M.methodology_directive(s)
        _briefs = {aid: PROMPTS.resolve(s, f"agent_persona_{aid}") for aid in _A.AGENTS}
        user_name = u.username

        def _sse(event, payload):
            return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

        def gen():
            yield _sse("meta", {"session_id": sid, "stage": stage, "agent": target, "live": live})
            acc = []
            if live:
                try:
                    for delta in _AE.stream_turn(target, stage, dossier, learn_texts,
                                                 b.message, _meth, _briefs, history=history):
                        acc.append(delta)
                        yield _sse("delta", {"t": delta})
                except Exception as e:  # never hang the client on a provider fault
                    yield _sse("delta", {"t": ""})
                    _obs_swallow('bro_app.py', e)
            text = "".join(acc).strip()
            parsed = _A.parse_directives(text) if (live and text) else None
            body = (parsed.body if (parsed and parsed.body) else text) or AI_HOLDING
            if not text:  # AI off or empty → stream the holding message now
                yield _sse("delta", {"t": body})
            advanced = False
            with SessionFactory() as s2:
                s2.add(ConversationMessage(session_id=sid, role="agent", agent=target,
                                           stage=stage, body=body))
                sess2 = s2.get(ConversationSession, sid)
                # persist the dossier (memory) — merge structured captures + the user's answer
                if sess2:
                    _dj = json.loads(sess2.dossier_json or "{}")
                    if parsed and parsed.dossier_update:
                        _dj.update(parsed.dossier_update)
                    if b.message and b.message.strip():
                        _n = _dj.setdefault("intake_notes", [])
                        _n.append(b.message.strip()[:400])
                        _dj["intake_notes"] = _n[-40:]
                    sess2.dossier_json = json.dumps(_dj)
                    _touch_session(sess2, _dj)
                # who takes the floor next: an explicit HANDOFF wins; otherwise the
                # stage's owner on advance; otherwise the same agent keeps going.
                _handoff = (parsed.handoff or {}).get("to") if parsed else None
                _handoff = _handoff if _handoff in _A.AGENTS else None
                if parsed and parsed.stage_complete and sess2 and sess2.stage < len(_A.STAGES) - 1:
                    sess2.stage += 1
                    sess2.active_agent = _handoff or _A.route_next_agent(sess2.stage)
                    advanced = True
                    s2.add(ConversationMessage(session_id=sid, role="system", agent="bro",
                            stage=sess2.stage,
                            body=f"Stage advanced — {parsed.stage_complete} Now at Stage "
                                 f"{sess2.stage}: {_A.STAGES[sess2.stage].name}."))
                elif sess2:
                    sess2.active_agent = _handoff or target
                try:
                    audit(s2, "agent.turn_stream", user_name,
                          {"session_id": sid, "agent": target, "advanced": advanced})
                except Exception:
                    pass
                s2.commit()
                final_stage = sess2.stage if sess2 else stage
                final_agent = sess2.active_agent if sess2 else target
            yield _sse("done", {"agent": target, "next_agent": final_agent, "stage": final_stage,
                                "advanced": advanced,
                                "stage_complete": (parsed.stage_complete if parsed else None)})

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.post("/api/v1/agent/learnings")
    def add_learning(b: LearningIn, s: Session = Depends(db),
                     u: User = Depends(require("engagement.view"))):
        text = _A.synthesize_learning(b.rating, b.agent, b.issue or "", b.note or "", b.stage)
        row = AgentLearning(rating=b.rating, agent=b.agent, stage=b.stage,
                            issue=b.issue, note=b.note, text=text)
        s.add(row); s.flush()
        audit(s, "agent.learning_captured", u.username, {"learning_id": row.id})
        s.commit()
        return {"learning_id": row.id, "text": text}

    @app.get("/api/v1/agent/learnings")
    def list_learnings(s: Session = Depends(db), u: User = Depends(require("engagement.view"))):
        return [{"id": l.id, "text": l.text, "rating": l.rating, "stage": l.stage}
                for l in s.scalars(select(AgentLearning).order_by(AgentLearning.id.desc())).all()]

    @app.delete("/api/v1/agent/learnings/{lid}")
    def delete_learning(lid: int, s: Session = Depends(db),
                        u: User = Depends(require("engagement.view"))):
        row = s.get(AgentLearning, lid)
        if row:
            s.delete(row); s.commit()
        return {"deleted": True}

    # ============================================================
    #  Registry v2 — exhaustive vendor/engagement model + masters
    # ============================================================
    from app.features.domain import registry_service as RS
    from app.features.intelligence import financial as FIN
    from app.features.domain.registry_models import (
        IndustryMaster, MaterialGroupMaster, VendorGroup, VendorRecord,
        VendorIndustry, ContactRecord, EngagementRecord, AssessmentRecord,
        FindingRecord, RemediationRecord, FourthPartyRecord, FourthPartyVendor,
        ArtefactRecord, IssueRecord,
    )

    # ---- master lists ----
    def _finding_row(f):
        import json as _j
        return {"finding_id": f.finding_id, "title": f.title, "heading": f.title,
                "description": f.description, "severity": f.severity, "source": f.source,
                "status": f.status, "domain": f.domain, "owner": f.owner,
                "assessor": f.assessor, "suggested_remediation": f.suggested_remediation,
                "suggested_closure": f.suggested_closure, "due_date": f.due_date,
                "engagement_id": f.engagement_id, "vendor_id": f.vendor_id,
                "assessment_id": f.assessment_id, "remediation_id": f.remediation_id,
                "risk_accepted": bool(f.risk_accepted), "acceptance_expiry": f.acceptance_expiry,
                "acceptance_rationale": f.acceptance_rationale, "accepted_by": f.accepted_by,
                "progress_notes": _j.loads(f.progress_notes or "[]"),
                "attachments": _j.loads(f.attachments or "[]"),
                "raised_by": f.raised_by, "created_at": str(f.created_at)}

    def _assessor_owns(u, f, s):
        """Assessor may modify only findings on engagements assigned to them
        (or where they are the named assessor). Admin/controller/others by perm."""
        role = (getattr(u, "role", None) and u.role.key) or ""
        if role != "vrm":
            return True  # gating handled by require(); non-assessors not scoped here
        if f.assessor and f.assessor == u.username:
            return True
        if f.engagement_id:
            eng = s.scalars(select(EngagementRecord).where(
                EngagementRecord.engagement_id == f.engagement_id)).first()
            if eng and eng.assigned_assessor == u.username:
                return True
        return False

    @app.post("/api/v2/findings")
    def v2_create_finding(b: V2FindingIn, s: Session = Depends(db),
                          u: User = Depends(require("finding.manage"))):
        f = RS.create_finding(s, title=b.title, severity=b.severity or "Medium",
                              source=b.source or "Assessor", description=b.description,
                              domain=b.domain, engagement_id=b.engagement_id,
                              vendor_id=b.vendor_id, assessment_id=b.assessment_id,
                              raised_by=u.username, due_date=b.due_date,
                              owner=b.owner, assessor=b.assessor,
                              suggested_remediation=b.suggested_remediation,
                              suggested_closure=b.suggested_closure,
                              status=b.status or "Draft")
        audit(s, "v2.finding_created", u.username,
              {"finding_id": f.finding_id, "severity": f.severity})
        s.commit()
        return _finding_row(f)

    @app.get("/api/v2/findings")
    def v2_list_findings(engagement_id: Optional[str] = None, vendor_id: Optional[str] = None,
                         assessment_id: Optional[str] = None, status: Optional[str] = None,
                         severity: Optional[str] = None, source: Optional[str] = None,
                         assessor: Optional[str] = None, accepted: Optional[str] = None,
                         s: Session = Depends(db), u: User = Depends(require("finding.view"))):
        rows = s.scalars(select(FindingRecord).order_by(FindingRecord.id.desc())).all()
        _av = _RBAC.scoped_vendor_ids(s, u)
        out = []
        for f in rows:
            if _av is not None and f.vendor_id not in _av: continue
            if engagement_id and f.engagement_id != engagement_id: continue
            if vendor_id and f.vendor_id != vendor_id: continue
            if assessment_id and f.assessment_id != assessment_id: continue
            if status and f.status != status: continue
            if severity and f.severity != severity: continue
            if source and f.source != source: continue
            if assessor and f.assessor != assessor: continue
            if accepted in ("true", "1") and not f.risk_accepted: continue
            if accepted in ("false", "0") and f.risk_accepted: continue
            out.append(_finding_row(f))
        return out

    @app.get("/api/v2/findings/{fid}")
    def v2_get_finding(fid: str, s: Session = Depends(db),
                       u: User = Depends(require("finding.view"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        f = s.scalars(select(FindingRecord).where(FindingRecord.finding_id == fid)).first()
        if not f: raise HTTPException(404, "finding not found")
        if not _RBAC.can_see_vendor(s, u, f.vendor_id):
            raise HTTPException(403, "not authorised for this finding")
        row = _finding_row(f)
        row["can_modify"] = _assessor_owns(u, f, s)
        row["statuses"] = FINDING_STATUSES
        return row

    @app.put("/api/v2/findings/{fid}")
    def v2_update_finding(fid: str, b: FindingPatchIn, s: Session = Depends(db),
                          u: User = Depends(require("finding.manage"))):
        f = s.scalars(select(FindingRecord).where(FindingRecord.finding_id == fid)).first()
        if not f: raise HTTPException(404, "finding not found")
        if not _assessor_owns(u, f, s):
            raise HTTPException(403, "Assessors may only modify findings on engagements assigned to them")
        from app.features.domain import vocab as _V
        for k in ("title", "description", "severity", "status", "owner", "assessor",
                  "suggested_remediation", "suggested_closure", "due_date"):
            v = getattr(b, k)
            if v is not None:
                # DB-05: accept legacy and case variants, store the canonical value.
                if k == "status":
                    v = _V.normalise("finding_status", v)
                    if not _V.is_valid("finding_status", v):
                        raise HTTPException(400, f"invalid status; allowed: {FINDING_STATUSES}")
                elif k == "severity":
                    v = _V.normalise("severity", v)
                setattr(f, k, v)
        if b.status == "Closed" and not f.closed_date:
            from datetime import date
            f.closed_date = date.today().isoformat()
        s.flush(); RS._recompute_open_actions(s, f.engagement_id)
        audit(s, "v2.finding_updated", u.username, {"finding_id": fid, "status": f.status})
        s.commit()
        return _finding_row(f)

    @app.post("/api/v2/findings/{fid}/risk-accept")
    def v2_finding_risk_accept(fid: str, b: RiskAcceptIn, s: Session = Depends(db),
                               u: User = Depends(require("acceptance.manage"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        f = s.scalars(select(FindingRecord).where(FindingRecord.finding_id == fid)).first()
        if not f: raise HTTPException(404, "finding not found")
        f.risk_accepted = bool(b.accept)
        f.acceptance_rationale = b.rationale if b.accept else None
        f.acceptance_expiry = b.expiry_date if b.accept else None
        f.accepted_by = u.username if b.accept else None
        s.flush()
        audit(s, "v2.finding_risk_accept", u.username,
              {"finding_id": fid, "accepted": bool(b.accept), "expiry": b.expiry_date})
        notify(s, (f"Risk acceptance recorded on {fid} (expires {b.expiry_date})"
                   if b.accept else f"Risk acceptance revoked on {fid}"), "all",
               body=f"Vendor {f.vendor_id or '—'} · engagement {f.engagement_id or '—'}")
        s.commit()
        return _finding_row(f)

    @app.post("/api/v2/findings/{fid}/note")
    def v2_finding_note(fid: str, b: FindingNoteIn, s: Session = Depends(db),
                        u: User = Depends(require("finding.manage"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        import json as _j
        from datetime import datetime as _dt
        f = s.scalars(select(FindingRecord).where(FindingRecord.finding_id == fid)).first()
        if not f: raise HTTPException(404, "finding not found")
        if not _assessor_owns(u, f, s):
            raise HTTPException(403, "Assessors may only update findings assigned to them")
        notes = _j.loads(f.progress_notes or "[]")
        notes.append({"ts": _dt.utcnow().isoformat(timespec="seconds"),
                      "user": u.username, "note": b.note})
        f.progress_notes = _j.dumps(notes); s.flush()
        audit(s, "v2.finding_note", u.username, {"finding_id": fid})
        s.commit()
        return {"finding_id": fid, "progress_notes": notes}

    @app.post("/api/v2/findings/{fid}/attach")
    def v2_finding_attach(fid: str, b: FindingAttachIn, s: Session = Depends(db),
                          u: User = Depends(require("finding.manage"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        import json as _j
        f = s.scalars(select(FindingRecord).where(FindingRecord.finding_id == fid)).first()
        if not f: raise HTTPException(404, "finding not found")
        if not _assessor_owns(u, f, s):
            raise HTTPException(403, "Assessors may only update findings assigned to them")
        atts = _j.loads(f.attachments or "[]")
        atts.append({"doc_id": b.doc_id, "name": b.name or b.doc_id})
        f.attachments = _j.dumps(atts); s.flush()
        audit(s, "v2.finding_attach", u.username, {"finding_id": fid, "doc_id": b.doc_id})
        s.commit()
        return {"finding_id": fid, "attachments": atts}

    @app.delete("/api/v2/findings/{fid}")
    def v2_delete_finding(fid: str, s: Session = Depends(db),
                          u: User = Depends(require("finding.delete"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        f = s.scalars(select(FindingRecord).where(FindingRecord.finding_id == fid)).first()
        if not f: raise HTTPException(404, "finding not found")
        eng = f.engagement_id
        s.delete(f); s.flush(); RS._recompute_open_actions(s, eng)
        audit(s, "v2.finding_deleted", u.username, {"finding_id": fid})
        s.commit()
        return {"deleted": fid}

    # ---- remediation plans (RMD) ----
    @app.post("/api/v2/findings/{fid}/remediation")
    def v2_finding_remediation(fid: str, body: dict = Body(default={}), s: Session = Depends(db),
                               u: User = Depends(require("finding.manage"))):
        _RBAC.assert_object_visible(s, u, 'finding', fid)
        """Create (or fetch) the remediation plan linked to a finding."""
        from app.features.domain.registry_models import FindingRecord, RemediationRecord
        from app.features.domain import registry_service as RS
        f = s.scalars(select(FindingRecord).where(FindingRecord.finding_id == fid)).first()
        if not f: raise HTTPException(404, "finding not found")
        r = None
        if f.remediation_id:
            r = s.scalars(select(RemediationRecord).where(
                RemediationRecord.remediation_id == f.remediation_id)).first()
        if not r:
            rid = RS.next_id(s, "remediation")
            r = RemediationRecord(remediation_id=rid, finding_id=fid,
                                  plan=body.get("plan") or (f.suggested_remediation or "Remediation plan to be defined."),
                                  owner=body.get("owner") or f.owner, target_date=body.get("target_date") or f.due_date,
                                  status="Planned", progress_pct=0)
            s.add(r); s.flush()
            f.remediation_id = rid
            if f.status in ("Draft", "Published"):
                f.status = "Under Remediation"
        audit(s, "v2.remediation_create", u.username, {"finding_id": fid, "remediation_id": r.remediation_id})
        s.commit()
        return _rmd_row(s, r)

    @app.get("/api/v2/criticality/model")
    def v2_criticality_model(u: User = Depends(require("vendor.view")), s: Session = Depends(db)):
        from app.features.assessment import criticality as CRIT
        return CRIT.model(s)

    # ===== Supplier Incidents =====
    _INC_SLA = {"Critical": 24, "High": 48, "Medium": 72, "Low": 120}

    @app.post("/api/v2/copilot/ask")
    def v2_copilot_ask(b: I18nTextIn, s: Session = Depends(db),
                       u: User = Depends(require("vendor.view"))):
        from app.features.assessment import copilot as COP
        from app.agents import llm_config
        res = COP.answer_query(s, b.text or "")
        res["ai"] = False
        if llm_config.status().get("live_ready") and res["rows"]:
            try:
                top = "; ".join(f"{r['label']} ({r['sublabel']})" for r in res["rows"][:12])
                out = llm_config.complete(
                    PROMPTS.resolve(s, "copilot_interpret"),
                    f"Question: {b.text}\nResult: {res['answer']}\nTop records: {top}",
                    domain="risk", max_tokens=220)
                if out and out.strip():
                    res["narrative"] = out.strip(); res["ai"] = True
            except Exception as _e:
                _obs_swallow('bro_app.py', _e)
        audit(s, "v2.copilot_ask", u.username, {"q": (b.text or "")[:120], "n": res["count"]})
        s.commit()
        return res

    @app.get("/api/v2/methodology/docs")
    def v2_meth_list(s: Session = Depends(db), u: User = Depends(require("admin.integrations"))):
        from app.features.assessment import methodology as M
        return {"docs": M.list_docs(s), "has_methodology": bool(M.methodology_text(s))}

    @app.post("/api/v2/methodology/docs")
    def v2_meth_add(b: MethodologyIn, s: Session = Depends(db),
                    u: User = Depends(require("admin.integrations"))):
        from app.features.assessment import methodology as M
        content = b.content_text or ""
        if not content and b.data_b64:
            import base64 as _b64
            try:
                content = _b64.b64decode(b.data_b64).decode("utf-8", "replace")
            except Exception:
                raise HTTPException(422, "could not decode uploaded text")
        if not content.strip():
            raise HTTPException(422, "empty methodology content")
        d = M.add_doc(s, title=b.title or "Methodology", content_text=content,
                      filename=b.filename or "", uploaded_by=u.username)
        audit(s, "methodology.added", u.username, {"doc_id": d.doc_id, "chars": len(content)})
        s.commit()
        return {"doc_id": d.doc_id}

    @app.get("/api/v2/methodology/docs/{doc_id}")
    def v2_meth_get(doc_id: str, s: Session = Depends(db), u: User = Depends(require("admin.integrations"))):
        from app.features.assessment import methodology as M
        d = M.get_doc(s, doc_id)
        if not d:
            raise HTTPException(404, "not found")
        return {"doc_id": d.doc_id, "title": d.title, "filename": d.filename,
                "active": d.active, "content_text": d.content_text}

    @app.post("/api/v2/methodology/docs/{doc_id}/active")
    def v2_meth_active(doc_id: str, b: ActiveIn, s: Session = Depends(db),
                       u: User = Depends(require("admin.integrations"))):
        from app.features.assessment import methodology as M
        M.set_active(s, doc_id, b.active)
        s.commit()
        return {"ok": True}

    @app.delete("/api/v2/methodology/docs/{doc_id}")
    def v2_meth_del(doc_id: str, s: Session = Depends(db), u: User = Depends(require("admin.integrations"))):
        from app.features.assessment import methodology as M
        ok = M.delete_doc(s, doc_id)
        audit(s, "methodology.deleted", u.username, {"doc_id": doc_id})
        s.commit()
        return {"deleted": ok}

    # ===== AI-driven FDD + Reputation (Claude searches, infers, organises) =====
    @app.post("/api/v2/feedback")
    def v2_feedback_add(body: dict = Body(...), s: Session = Depends(db), u: User = Depends(actor)):
        from app.features.assessment import feedback as FB
        fid = FB.record(s, u.username, body.get("surface") or "general",
                        body.get("query"), body.get("answer"),
                        rating=body.get("rating") or "na", comment=body.get("comment"),
                        engine=body.get("engine"))
        audit(s, "v2.feedback", u.username, {"id": fid, "surface": body.get("surface"),
                                             "rating": body.get("rating")})
        s.commit()
        return {"id": fid, "ok": True}

    @app.get("/api/v2/feedback")
    def v2_feedback_list(surface: Optional[str] = None, rating: Optional[str] = None,
                         s: Session = Depends(db), u: User = Depends(actor)):
        from app.features.assessment import feedback as FB
        return {"summary": FB.summary(s), "items": FB.list_recent(s, surface=surface, rating=rating)}

    @app.post("/api/v2/feedback/{fid}/used")
    def v2_feedback_used(fid: int, body: dict = Body(default={}), s: Session = Depends(db),
                         u: User = Depends(actor)):
        from app.features.assessment import feedback as FB
        res = FB.set_used(s, fid, body.get("used", True), u.username)
        if not res:
            raise HTTPException(404, "feedback not found")
        s.commit()
        return res

    @app.put("/api/v2/engagements/{eid}/criticality-inputs")
    def v2_crit_inputs(eid: str, b: CriticalityInputIn, s: Session = Depends(db),
                       u: User = Depends(require("engagement.edit"))):
        from app.features.domain import master_service as MS
        if not s.scalars(select(EngagementRecord).where(
                EngagementRecord.engagement_id == eid)).first():
            raise HTTPException(404, "engagement not found")
        MS.set_criticality_inputs(s, eid, b.model_dump())
        res = MS.score_engagement_criticality(s, eid)
        audit(s, "v2.criticality_inputs", u.username, {"engagement_id": eid, "score": res["score"]})
        s.commit()
        return res

    @app.get("/api/v2/engagements/{eid}/criticality")
    def v2_crit_score(eid: str, s: Session = Depends(db),
                      u: User = Depends(require("engagement.view"))):
        _RBAC.assert_object_visible(s, u, 'engagement', eid)
        from app.features.domain import master_service as MS
        res = MS.score_engagement_criticality(s, eid)
        if res.get("exists") is False:
            raise HTTPException(404, "engagement not found")
        return res

    @app.post("/api/v2/engagements/{eid}/criticality-override")
    def v2_eng_crit_override(eid: str, b: CriticalOverrideIn, s: Session = Depends(db),
                             u: User = Depends(require("engagement.edit"))):
        _RBAC.assert_object_visible(s, u, 'engagement', eid)
        from app.features.domain import master_service as MS
        res = MS.override_engagement_criticality(s, eid, b.is_critical, b.reason or "manual", u.username)
        if res.get("exists") is False:
            raise HTTPException(404, "engagement not found")
        audit(s, "v2.eng_criticality_override", u.username,
              {"engagement_id": eid, "is_critical": b.is_critical})
        s.commit()
        return res

    # ============================================================
    # REQ 4 — VENDOR PERFORMANCE MANAGEMENT (critical vendors)
    # ============================================================
    @app.get("/api/v2/learnings")
    def v2_list_learnings(category: Optional[str] = None, vendor_id: Optional[str] = None,
                          s: Session = Depends(db), u: User = Depends(require("engagement.view"))):
        return [LEARN.row(l) for l in LEARN.list_learnings(s, category, vendor_id)]

    @app.get("/api/v2/learnings/summary")
    def v2_learnings_summary(s: Session = Depends(db),
                             u: User = Depends(require("engagement.view"))):
        return LEARN.summary(s)

    @app.post("/api/v2/learnings")
    def v2_create_learning(b: LearningIn, s: Session = Depends(db),
                           u: User = Depends(require("engagement.edit"))):
        l = LEARN.create(s, category=b.category, insight=b.insight,
                         confidence=b.confidence or "Medium", origin="human",
                         source_engagement=b.source_engagement, source_vendor=b.source_vendor,
                         created_by=u.username)
        audit(s, "v2.learning_created", u.username, {"id": l.id, "category": l.category})
        s.commit()
        return LEARN.row(l)

    @app.post("/api/v2/learnings/{lid}/applied")
    def v2_learning_applied(lid: int, s: Session = Depends(db),
                            u: User = Depends(require("engagement.view"))):
        l = LEARN.mark_applied(s, lid)
        if not l:
            raise HTTPException(404, "learning not found")
        s.commit()
        return LEARN.row(l)

    @app.delete("/api/v2/learnings/{lid}")
    def v2_delete_learning(lid: int, s: Session = Depends(db),
                           u: User = Depends(require("engagement.edit"))):
        l = s.get(LEARN.PlatformLearning, lid)
        if not l:
            raise HTTPException(404, "learning not found")
        s.delete(l)
        audit(s, "v2.learning_deleted", u.username, {"id": lid})
        s.commit()
        return {"id": lid, "deleted": True}

    @app.post("/api/v2/engagements/{eid}/capture-learnings")
    def v2_capture_learnings(eid: str, s: Session = Depends(db),
                             u: User = Depends(require("engagement.edit"))):
        _RBAC.assert_object_visible(s, u, 'engagement', eid)
        """Derive durable learnings from the most recent assessment on an engagement."""
        from app.features.domain import registry_models as RM
        a = s.scalar(select(RM.AssessmentRecord)
                     .where(RM.AssessmentRecord.engagement_id == eid)
                     .order_by(RM.AssessmentRecord.id.desc()))
        if not a:
            raise HTTPException(404, "no assessment on this engagement")
        finds = s.scalars(select(RM.FindingRecord)
                          .where(RM.FindingRecord.engagement_id == eid)).all()
        created = LEARN.capture_from_assessment(s, a, list(finds), actor=u.username)
        audit(s, "v2.learnings_captured", u.username, {"engagement_id": eid, "count": len(created)})
        s.commit()
        return {"captured": len(created), "learnings": [LEARN.row(l) for l in created]}

    # ================= EXTERNAL INTEGRATION CONNECTORS =================
    from app.features.admin import integrations as INTEG

    @app.post("/api/v2/agent/sessions/{sid}/interim-report")
    def v2_interim_report(sid: int, s: Session = Depends(db),
                          u: User = Depends(require("engagement.view"))):
        """Build an interim assessment report from a live BRO Chat session:
        an AI narrative of the assessment so far (deterministic fallback when AI
        is unavailable) plus an annex of every document and key input submitted.
        Returns HTML the client renders and prints to PDF."""
        from app.features.domain import models_feature as MF
        from app.features.lifecycle import documents as DOCS
        sess = s.get(MF.ConversationSession, sid)
        if not sess:
            raise HTTPException(404, "session not found")
        msgs = s.scalars(select(MF.ConversationMessage)
                         .where(MF.ConversationMessage.session_id == sid)
                         .order_by(MF.ConversationMessage.id)).all()
        dossier = json.loads(sess.dossier_json or "{}")
        eng_id = sess.engagement_id
        docs = []
        if eng_id:
            docs = s.scalars(select(DOCS.StoredDocument)
                             .where(DOCS.StoredDocument.engagement_id == eng_id)).all()

        user_inputs = [m.body for m in msgs if m.role == "user"]
        agent_msgs = [m for m in msgs if m.role == "agent"]
        transcript = "\n".join(f"{m.role.upper()}"
                               f"{('/'+m.agent) if m.agent else ''}: {m.body}" for m in msgs)

        # AI narrative (deterministic fallback)
        ai_mode = "deterministic"
        narrative = None
        try:
            from app.agents import llm_config
            if llm_config.is_enabled():
                sys = ("You are BRO, a senior TPRM assessor. Write a concise interim assessment "
                       "report (250-400 words) summarising the assessment performed so far from the "
                       "conversation: scope, exposure identified, controls discussed, open questions, "
                       "and provisional direction. Be factual and grounded only in the transcript. "
                       "Plain prose, no markdown headers.")
                narrative = llm_config.complete(sys, transcript[:9000], domain="interim_report",
                                                review=False, max_tokens=700)
                if narrative:
                    ai_mode = "ai"
        except Exception:
            narrative = None
        if not narrative:
            stage = sess.stage or 0
            narrative = (
                f"This interim report summarises the assessment in progress for engagement "
                f"{eng_id or '(unassigned)'}. The conversation has reached stage {stage} of the "
                f"assessment lifecycle, with {len(user_inputs)} input(s) from the business and "
                f"{len(agent_msgs)} specialist response(s) on record. "
                + ("Key context captured so far: " + "; ".join(
                    f"{k}: {v}" for k, v in list(dossier.items())[:8] if v) + ". "
                   if dossier else "No structured dossier fields have been captured yet. ")
                + f"A total of {len(docs)} supporting document(s) have been submitted and are listed "
                "in the annex below. This is a provisional, working view: the assessment is not yet "
                "complete and no final risk decision has been recorded. A full assessment report is "
                "produced once the engagement is captured and signed off.")

        # render HTML report (self-contained, print-ready)
        def esc(t):
            return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        from datetime import datetime as _dt, timezone as _tz
        stamp = _dt.now(_tz.utc).strftime("%d %b %Y %H:%M UTC")
        annex_docs = "".join(
            f"<tr><td>{i+1}</td><td>{esc(d.filename)}</td><td>{esc(d.purpose or '—')}</td>"
            f"<td>{(d.size_bytes or 0)//1024} KB</td><td>{esc(d.uploaded_by or '—')}</td></tr>"
            for i, d in enumerate(docs)) or '<tr><td colspan="5" style="color:#888">No documents submitted yet.</td></tr>'
        annex_inputs = "".join(
            f"<li>{esc(t)}</li>" for t in user_inputs[:30]) or "<li style='color:#888'>No user inputs recorded yet.</li>"
        para = "".join(f"<p>{esc(p)}</p>" for p in narrative.split("\n") if p.strip())
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Interim Assessment Report</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;line-height:1.6;max-width:880px;margin:0 auto;padding:40px}}
h1{{font-family:Georgia,serif;color:#14302A;font-size:28px;margin:0 0 4px}}.sub{{color:#5a6472;font-size:13px;margin-bottom:24px}}
h2{{font-family:Georgia,serif;color:#14302A;font-size:18px;border-bottom:2px solid #B8862B;padding-bottom:5px;margin:26px 0 12px}}
.badge{{display:inline-block;background:#FBF4E4;border:1px solid #e8c07a;color:#7a5015;font-size:11px;padding:2px 10px;border-radius:20px;margin-left:8px}}
.meta{{display:grid;grid-template-columns:1fr 1fr;gap:8px 24px;background:#F7F5F0;border:1px solid #E5DFD0;border-radius:10px;padding:16px;font-size:13px;margin-bottom:8px}}
.meta b{{color:#14302A}}table{{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0}}
th{{background:#14302A;color:#fff;text-align:left;padding:8px 10px;font-size:11px}}td{{border-bottom:1px solid #E5DFD0;padding:7px 10px}}
ul{{font-size:13px}}.foot{{margin-top:30px;border-top:1px solid #E5DFD0;padding-top:12px;color:#888;font-size:11px}}
p{{font-size:13.5px}}@media print{{body{{padding:0}}}}</style></head><body>
<h1>Interim Assessment Report <span class="badge">AI · {ai_mode}</span></h1>
<div class="sub">BRO Risk Oracle · session #{sid} · generated {stamp}</div>
<div class="meta"><div><b>Engagement</b><br>{esc(eng_id or 'Unassigned')}</div>
<div><b>Lifecycle stage</b><br>Stage {sess.stage or 0}</div>
<div><b>Inputs on record</b><br>{len(user_inputs)} business input(s)</div>
<div><b>Documents submitted</b><br>{len(docs)}</div></div>
<h2>Assessment so far</h2>{para}
<h2>Annex A — Documents submitted</h2>
<table><thead><tr><th>#</th><th>Document</th><th>Purpose</th><th>Size</th><th>Submitted by</th></tr></thead><tbody>{annex_docs}</tbody></table>
<h2>Annex B — Information submitted by the user</h2><ul>{annex_inputs}</ul>
<div class="foot">Interim, working document — the assessment is not complete and no final risk decision is recorded.
Generated by Brata (BRO Risk Oracle). AI narrative mode: {ai_mode}.</div></body></html>"""
        audit(s, "v2.interim_report", u.username, {"session_id": sid, "ai_mode": ai_mode})
        s.commit()
        return {"session_id": sid, "ai_mode": ai_mode, "html": html,
                "documents": len(docs), "inputs": len(user_inputs)}


    @app.post("/api/v2/proassess/run")
    def v2_proassess_run(b: ProAssessRunIn, s: Session = Depends(db),
                         u: User = Depends(require("engagement.view"))):
        if not _ai_live():
            return {"available": False, "holding": True, "message": AI_HOLDING}
        from app.features.domain import master_service as MS
        report = MS.run_proassess(s, vendor_id=b.vendor_id, engagement_id=b.engagement_id,
                                  irq=b.irq, ddq=b.ddq, documents=b.documents,
                                  extracted=b.extracted, deep=bool(getattr(b,"deep",False)))
        audit(s, "v2.proassess_run", u.username,
              {"vendor_id": b.vendor_id, "inherent": report["inherent_band"],
               "residual": report["residual_band"], "gaps": report["gap_count"]})
        s.commit()
        return report

    @app.post("/api/v2/proassess/register")
    def v2_proassess_register(b: ProAssessRegisterIn, s: Session = Depends(db),
                              u: User = Depends(require("engagement.create"))):
        from app.features.domain import master_service as MS
        res = MS.register_proassess(s, b.report, u.username)
        audit(s, "v2.proassess_register", u.username, res)
        s.commit()
        return res

    @app.post("/api/v2/proassess/autonomous")
    def v2_proassess_autonomous(b: ProAssessAutoIn, s: Session = Depends(db),
                                u: User = Depends(require("engagement.create"))):
        """CR-4: single-input, document-aware, autonomous ProAssess. Works for new or
        existing vendors; creates records across the databases when create_records=True."""
        if not _ai_live():
            return {"available": False, "holding": True, "message": AI_HOLDING}
        from app.features.domain import master_service as MS
        if not b.vendor_id and not b.new_vendor_name:
            raise HTTPException(422, "provide vendor_id or new_vendor_name")
        try:
            report = MS.run_proassess_autonomous(
                s, free_text=b.free_text or "", documents=b.documents,
                vendor_id=b.vendor_id, new_vendor_name=b.new_vendor_name,
                engagement_title=b.engagement_title, ddq=b.ddq,
                user=u.username, create_records=b.create_records, deep=bool(getattr(b,"deep",False)))
        except Exception as e:
            s.rollback()
            raise HTTPException(400, f"autonomous assessment failed: {e}")
        if report.get("error"):
            raise HTTPException(422, report["error"])
        audit(s, "v2.proassess_autonomous", u.username,
              {"vendor_id": report.get("vendor_id"), "created_vendor": report.get("created_vendor"),
               "tables_written": report.get("tables_written", [])})
        s.commit()
        return report

    # ============================================================
    # REQ 6 — VENDOR 360 DASHBOARD (compile + correlate)
    # ============================================================

    return r
