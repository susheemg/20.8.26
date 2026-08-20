"""Shared route helpers used across >1 package. Bound as locals per build call
(closing over this call's deps) so multi-app isolation is preserved."""
from __future__ import annotations

from fastapi.responses import (PlainTextResponse, StreamingResponse,
    HTMLResponse, JSONResponse, FileResponse, RedirectResponse)

import threading as _threading, uuid as _uuid, time as _time
import json as _json, socket as _socket, os as _os_
from sqlalchemy import text as _sqltext
# Background research jobs. State is persisted (see _job_table) so that more than
# one worker can serve a status poll — the previous in-process dict could not.


def bind_shared(deps):
    import app.bro_app as _M
    globals().update({k: v for k, v in vars(_M).items() if not k.startswith("__")})
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


    def _monitor_interval() -> float:
        try:
            return float(_os.environ.get("BRO_MONITORING_INTERVAL_HOURS", "24"))
        except ValueError:
            return 24.0

    def _rmd_row(s, r):
        from app.features.domain.registry_models import FindingRecord
        f = s.scalars(select(FindingRecord).where(FindingRecord.finding_id == r.finding_id)).first()
        return {"remediation_id": r.remediation_id, "finding_id": r.finding_id,
                "finding_title": f.title if f else None, "severity": f.severity if f else None,
                "vendor_id": f.vendor_id if f else None, "engagement_id": f.engagement_id if f else None,
                "plan": r.plan, "owner": r.owner, "target_date": r.target_date,
                "status": r.status, "progress_pct": r.progress_pct, "evidence": r.evidence,
                "completed_date": r.completed_date, "verified_by": r.verified_by,
                "created_at": r.created_at.isoformat() if r.created_at else None}

    def _file_monitoring_report(s, vendor_id, provider, mode, payload, actor):
        """File a connector pull as a tagged report + update the vendor indicator."""
        import base64 as _b64, json as _j
        from app.features.lifecycle import documents as DOC
        from app.features.domain.registry_models import VendorRecord
        v = s.scalars(select(VendorRecord).where(
            VendorRecord.vendor_id == vendor_id)).first() if vendor_id else None
        purpose = "fdd_report" if provider == "rapidratings" else "reputation_report"
        data = _b64.b64encode(_j.dumps(payload, indent=2).encode()).decode()
        doc = DOC.store_document(
            s, filename=f"{provider}_{(v.legal_name if v else vendor_id or 'entity')}.json"[:80],
            content_type="application/json", data_b64=data,
            vendor_id=vendor_id, uploaded_by=f"{provider}:{mode}", purpose=purpose)
        if v:
            if provider == "rapidratings" and payload.get("financial_health_band"):
                v.financial_health_band = payload["financial_health_band"]
            if provider == "interos" and payload.get("reputation_band"):
                try: v.reputation_band = payload["reputation_band"]
                except Exception: pass
        notify(s, f"{provider.title()} monitoring update filed for {vendor_id or 'entity'}", "all")
        return doc.doc_id

    def _ai_research(s, *, vendor_id, company, jurisdiction, identifier, mode, actor, deep=False):
        """mode = 'fdd' | 'reputation' | 'both'. Claude web-searches & organises;
        the result is auto-filed as a report and indicators are updated everywhere."""
        from app.features.intelligence import entity_resolve as ER
        from app.features.assessment import methodology as M
        from app.features.lifecycle import documents as DOCS
        from app.features.domain.registry_models import VendorRecord, FinMonitorRecord
        from app.features.domain.master_ext import VendorMasterExt, VendorMonitorSignal
        import base64 as _b64, datetime as _dt
        # resolve company name from vendor if needed
        if vendor_id and not company:
            v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
            company = v.legal_name if v else vendor_id
        res = ER.web_research_fdd_reputation(company, jurisdiction or "UK", identifier or "", deep=deep,
                                             methodology=M.methodology_directive(s), mode=mode)
        if not res.get("available"):
            return {"available": False, "holding": True, "message": AI_HOLDING,
                    "limitations": res.get("limitations")}
        # available but the AI call didn't produce usable findings -> surface, don't file
        if res.get("limitations") and not res.get("matched") and not (res.get("financials") or res.get("reputation")):
            return {"available": False, "holding": True,
                    "message": res.get("limitations")}
        # auto-file as a report
        import json as _json
        purpose = {"fdd": "fdd_report", "reputation": "reputation_report"}.get(mode, "fdd_reputation_report")
        fname = f"{purpose}_{(company or vendor_id or 'entity').replace(' ', '_')[:40]}.json"
        doc_id = None
        try:
            payload = _b64.b64encode(_json.dumps(res, indent=2).encode()).decode()
            doc = DOCS.store_document(s, filename=fname, content_type="application/json",
                                      data_b64=payload, vendor_id=vendor_id, uploaded_by=actor, purpose=purpose)
            doc_id = doc.doc_id
        except Exception:
            doc_id = None
        # auto-update indicators everywhere
        updated = []
        if vendor_id:
            fhb = (res.get("financial_health_band") or res.get("fdd", {}).get("financial_health_band")
                   if isinstance(res.get("fdd"), dict) else res.get("financial_health_band"))
            if mode in ("fdd", "both") and fhb:
                ext = s.scalars(select(VendorMasterExt).where(VendorMasterExt.vendor_id == vendor_id)).first()
                if ext:
                    ext.financial_health_band = str(fhb)[:40]; updated.append("financial_health_band")
                fm = s.scalars(select(FinMonitorRecord).where(FinMonitorRecord.vendor_id == vendor_id)).first()
                if fm:
                    fm.last_result = str(fhb)[:40]
                    fm.last_signal = (res.get("summary") or "AI FDD research")[:200]
                    fm.last_swept = _dt.datetime.now(_dt.timezone.utc); updated.append("fin_monitor")
            if mode in ("reputation", "both"):
                adverse = res.get("adverse_media") or res.get("reputation", {}).get("adverse_media") \
                    if isinstance(res.get("reputation"), dict) else res.get("adverse_media")
                s.add(VendorMonitorSignal(vendor_id=vendor_id, signal_type="adverse_media",
                                          value="flagged" if adverse else "clear",
                                          source="AI reputation research"))
                updated.append("reputation_signal")
        res["filed_report"] = doc_id
        res["indicators_updated"] = updated
        return res


    def _job_table(sess):
        """APP-01: job state lives in the database, not process memory.

        The previous registry was a module-level dict, which meant a run died with
        its process and a status poll could land on a worker that had never heard of
        the job. Persisting it is the minimum that makes more than one worker safe;
        it is not full durable execution (nothing re-drives an interrupted run), and
        that distinction is recorded rather than glossed."""
        sess.execute(_sqltext(
            "CREATE TABLE IF NOT EXISTS research_jobs ("
            "job_id TEXT PRIMARY KEY, status TEXT NOT NULL, mode TEXT, actor TEXT, "
            "vendor_id TEXT, company TEXT, result_json TEXT, error TEXT, "
            "started_at REAL, finished_at REAL, worker TEXT)"))
        sess.commit()

    def _start_research_job(*, vendor_id, company, jurisdiction, identifier, mode, deep, actor):
        """Run web-search research off the request thread; the client polls for the
        result. The result is filed in AI Reports regardless of whether anyone waits."""
        job_id = _uuid.uuid4().hex[:12]
        _worker = f"{_socket.gethostname()}:{_os_.getpid()}"
        with SessionFactory() as _s:
            _job_table(_s)
            _s.execute(_sqltext(
                "INSERT INTO research_jobs (job_id,status,mode,actor,vendor_id,company,"
                "started_at,worker) VALUES (:j,'running',:m,:a,:v,:c,:t,:w)"),
                {"j": job_id, "m": mode, "a": actor, "v": vendor_id, "c": company,
                 "t": _time.time(), "w": _worker})
            _s.commit()

        def _run():
            try:
                with SessionFactory() as _s:
                    r = _ai_research(_s, vendor_id=vendor_id, company=company,
                                     jurisdiction=jurisdiction, identifier=identifier,
                                     mode=mode, actor=actor, deep=deep)
                    _s.commit()
                with SessionFactory() as _s:
                    _s.execute(_sqltext(
                        "UPDATE research_jobs SET status='done', result_json=:r, "
                        "finished_at=:t WHERE job_id=:j"),
                        {"r": _json.dumps(r, default=str)[:2000000], "t": _time.time(),
                         "j": job_id})
                    _s.commit()
            except Exception as e:
                try:
                    with SessionFactory() as _s:
                        _s.execute(_sqltext(
                            "UPDATE research_jobs SET status='error', error=:e, "
                            "finished_at=:t WHERE job_id=:j"),
                            {"e": f"{type(e).__name__}: {str(e)[:300]}", "t": _time.time(),
                             "j": job_id})
                        _s.commit()
                except Exception:
                    pass
            finally:
                try:  # retention: jobs are operational state, not audit
                    with SessionFactory() as _s:
                        _s.execute(_sqltext("DELETE FROM research_jobs WHERE started_at < :c"),
                                   {"c": _time.time() - 86400})
                        _s.commit()
                except Exception:
                    pass

        _threading.Thread(target=_run, daemon=True).start()
        return job_id

    def _research_job_status(job_id):
        with SessionFactory() as _s:
            try:
                _job_table(_s)
                row = _s.execute(_sqltext(
                    "SELECT status, mode, actor, result_json, error, started_at "
                    "FROM research_jobs WHERE job_id=:j"), {"j": job_id}).fetchone()
            except Exception:
                return None
        if not row:
            return None
        st, mode, actor, rj, err, started = row
        out = {"status": st, "mode": mode, "actor": actor, "error": err,
               "started": started or 0, "result": None}
        if rj:
            try:
                out["result"] = _json.loads(rj)
            except Exception:
                out["result"] = None
        return out

    return {
        "_monitor_interval": _monitor_interval,
        "_rmd_row": _rmd_row,
        "_file_monitoring_report": _file_monitoring_report,
        "_ai_research": _ai_research,
        "_start_research_job": _start_research_job,
        "_research_job_status": _research_job_status,
    }
