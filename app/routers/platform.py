"""Auto-extracted platform routes (RouterDeps pattern). See app/routers/deps.py.

Behaviour is byte-identical to the pre-split monolith; per-instance deps are bound
as locals (multi-app isolation), invariant models/imports come from bro_app globals.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import (PlainTextResponse, StreamingResponse,
    HTMLResponse, JSONResponse, FileResponse, RedirectResponse)

from .deps import RouterDeps
from ._shared import bind_shared


def build_platform_router(deps: RouterDeps) -> APIRouter:
    import app.bro_app as _M
    globals().update({k: v for k, v in vars(_M).items() if not k.startswith("__")})
    r = APIRouter()
    app = r
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


    def _connector_status():
        import os as _os
        return {
            "rapidratings": {"name": "RapidRatings", "domain": "Financial DD",
                             "mode": "live" if _os.environ.get("RAPIDRATINGS_API_KEY") else "demonstrator",
                             "mcp": _os.environ.get("RAPIDRATINGS_MCP_URL"),
                             "webhook": "/api/v2/webhooks/rapidratings"},
            "interos": {"name": "Interos", "domain": "Reputation & resilience",
                        "mode": "live" if _os.environ.get("INTEROS_API_KEY") else "demonstrator",
                        "mcp": _os.environ.get("INTEROS_MCP_URL"),
                        "webhook": "/api/v2/webhooks/interos"},
        }

    @app.get("/api/v2/connectors/status")
    def v2_connector_status(u: User = Depends(require("intel.financial"))):
        return _connector_status()

    @app.post("/api/v2/connectors/rapidratings/pull")
    def v2_rapidratings_pull(b: ConnectorPullIn, s: Session = Depends(db),
                             u: User = Depends(require("intel.financial"))):
        st = _connector_status()["rapidratings"]
        # DEMONSTRATOR payload — live mode would call the RapidRatings API / MCP here.
        payload = {"provider": "RapidRatings", "vendor_id": b.vendor_id,
                   "fhr": 62, "core_health_score": 58, "financial_health_band": "Adequate",
                   "trend": "stable", "as_of": "latest",
                   "summary": "Financial Health Rating in the adequate band; stable trend; "
                              "no going-concern flag.", "mode": st["mode"]}
        doc = _file_monitoring_report(s, b.vendor_id, "rapidratings", st["mode"], payload, u.username)
        audit(s, "v2.connector_rapidratings", u.username, {"vendor_id": b.vendor_id, "doc": doc})
        s.commit()
        return {"provider": "rapidratings", "mode": st["mode"], "filed_report": doc, "data": payload}

    @app.post("/api/v2/connectors/interos/pull")
    def v2_interos_pull(b: ConnectorPullIn, s: Session = Depends(db),
                        u: User = Depends(require("intel.reputation"))):
        st = _connector_status()["interos"]
        payload = {"provider": "Interos", "vendor_id": b.vendor_id,
                   "reputation_band": "Caution", "resilience_score": 71,
                   "adverse_media": True, "esg_flag": "Moderate",
                   "summary": "One adverse-media item in the last 12 months; resilience score "
                              "within tolerance; ESG exposure moderate.", "mode": st["mode"]}
        doc = _file_monitoring_report(s, b.vendor_id, "interos", st["mode"], payload, u.username)
        audit(s, "v2.connector_interos", u.username, {"vendor_id": b.vendor_id, "doc": doc})
        s.commit()
        return {"provider": "interos", "mode": st["mode"], "filed_report": doc, "data": payload}

    @app.get("/api/v2/platform-docs/versions")
    def v2_doc_versions(s: Session = Depends(db), u: User = Depends(require("engagement.view"))):
        return PDOCS.version_history()

    @app.get("/api/v2/platform-docs/{kind}")
    def v2_get_doc(kind: str, s: Session = Depends(db),
                   u: User = Depends(require("engagement.view"))):
        if kind not in PDOCS.KINDS:
            raise HTTPException(404, "unknown document")
        row = PDOCS.get_doc(s, kind)
        s.commit()
        return {"kind": kind, "title": PDOCS.KINDS[kind]["title"],
                "doc_version": row.doc_version, "updated_at": row.updated_at.isoformat(),
                "updated_by": row.updated_by, "html": row.html}

    @app.post("/api/v2/platform-docs/{kind}/ai-update")
    def v2_ai_update_doc(kind: str, s: Session = Depends(db),
                         u: User = Depends(require("admin.users"))):
        if kind not in PDOCS.KINDS:
            raise HTTPException(404, "unknown document")
        res = PDOCS.ai_update_doc(s, kind, actor=u.username)
        audit(s, "v2.doc_ai_update", u.username, {"kind": kind, "version": res["doc_version"]})
        s.commit()
        return res

    # ================= PLATFORM LEARNINGS =================
    from app.features.assessment import learnings as LEARN


    return r
