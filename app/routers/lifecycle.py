"""Auto-extracted lifecycle routes (RouterDeps pattern). See app/routers/deps.py.

Behaviour is byte-identical to the pre-split monolith; per-instance deps are bound
as locals (multi-app isolation), invariant models/imports come from bro_app globals.
"""
from __future__ import annotations

from fastapi import APIRouter
import app.features.admin.rbac as _RBAC
from fastapi.responses import (PlainTextResponse, StreamingResponse,
    HTMLResponse, JSONResponse, FileResponse, RedirectResponse)

from .deps import RouterDeps
from ._shared import bind_shared


def build_lifecycle_router(deps: RouterDeps) -> APIRouter:
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


    @app.post("/api/v2/monitoring/run")
    def v2_monitoring_run(body: dict = Body(default={}), s: Session = Depends(db),
                          u: User = Depends(require("admin.config"))):
        only = body.get("only")  # optional list of task names
        return MON.run_all(s, by=u.username, trigger="manual", audit_fn=audit, only=only)

    @app.get("/api/v2/monitoring/status")
    def v2_monitoring_status(s: Session = Depends(db),
                             u: User = Depends(require("vendor.view"))):
        st = MON.status(s, _monitor_interval())
        st["tasks_available"] = [n for n, _ in MON.TASKS]
        st["scheduler_enabled"] = _os.environ.get("BRO_SCHEDULER_ENABLED") == "1"
        return st

    @app.get("/api/v2/monitoring/runs")
    def v2_monitoring_runs(limit: int = 20, s: Session = Depends(db),
                           u: User = Depends(require("vendor.view"))):
        from app.features.domain.registry_models import MonitoringRun
        rows = s.scalars(select(MonitoringRun).order_by(MonitoringRun.id.desc())).all()[:limit]
        return [{"run_id": r.run_id, "trigger": r.trigger, "ok": r.ok,
                 "started_at": r.started_at.isoformat() if r.started_at else None,
                 "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                 "tasks": json.loads(r.tasks or "{}")} for r in rows]




    @app.post("/api/v1/monitoring/sweep")
    def monitoring_sweep(b: IntelIn, s: Session = Depends(db),
                         u: User = Depends(require("lifecycle.monitoring"))):
        fin = intel.vera_financial(b.payload)
        status = "OK" if (fin.score or 0) >= 55 else "ALERT" if (fin.score or 0) >= 35 else "CRITICAL"
        s.add(Monitoring(vendor_id=b.vendor_id, sweep_type="financial",
                         status=status, detail=fin.narrative))
        if status in ("ALERT", "CRITICAL"):
            # auto-raise a reassessment + notify VRM and business
            s.add(Reassessment(engagement_id=0, mode="triggered"))
            notify(s, f"Monitoring {status} for vendor {b.vendor_id}", "all")
        audit(s, "monitoring.sweep", u.username, {"vendor_id": b.vendor_id, "status": status})
        s.commit()
        return {"vendor_id": b.vendor_id, "status": status}

    @app.post("/api/v1/incidents")
    def create_incident(b: IntelIn, s: Session = Depends(db),
                        u: User = Depends(require("lifecycle.incident"))):
        row = Incident(vendor_id=b.vendor_id, title=b.payload.get("title", "Incident"),
                       severity=b.payload.get("severity", "medium"))
        s.add(row); s.flush()
        audit(s, "incident.raised", u.username, {"incident_id": row.id})
        notify(s, "Third-party incident raised", "all")
        s.commit()
        return {"incident_id": row.id, "status": row.status}

    # ===== conversational assessment (role-aware, our Q1 model) =====


    @app.post("/api/v1/documents")
    def add_document(b: DocIn, s: Session = Depends(db),
                     u: User = Depends(require("lifecycle.documents"))):
        from datetime import datetime as _dt
        nv = _dt.fromisoformat(b.next_validation) if b.next_validation else None
        row = Document(vendor_id=b.vendor_id, engagement_id=b.engagement_id,
                       name=b.name, doc_type=b.doc_type, next_validation=nv)
        s.add(row); s.flush()
        audit(s, "document.added", u.username, {"document_id": row.id})
        s.commit()
        return {"document_id": row.id, "name": row.name}

    @app.post("/api/v1/engagements/{eid}/contract")
    def gen_contract(eid: int, s: Session = Depends(db),
                     u: User = Depends(require("intel.contract"))):
        _RBAC.assert_object_visible(s, u, 'engagement', eid)
        e = s.get(EngagementRow, eid)
        if not e:
            raise HTTPException(404, "engagement not found")
        v = s.get(Vendor, e.vendor_id)
        out = intel.matt_contract(v.tier if v else "Tier 3")
        row = Contract(engagement_id=eid, tier=v.tier if v else "Tier 3",
                       terms_json=json.dumps(list(out.signals)))
        s.add(row); s.flush()
        if e.stage == "decision":
            e.stage = "contract"
        audit(s, "contract.generated", u.username, {"engagement_id": eid})
        s.commit()
        return {"contract_id": row.id, "tier": row.tier, "terms": out.signals}

    # ===== reassessments =====
    @app.post("/api/v1/documents/upload")
    async def upload_document(
        file: UploadFile = File(...),
        vendor_id: Optional[int] = Form(default=None),
        engagement_id: Optional[int] = Form(default=None),
        s: Session = Depends(db),
        u: User = Depends(require("lifecycle.documents")),
    ):
        from app.features.platform import uploads
        data = await file.read()
        _uerr = SEC.upload_check(file.filename or "upload", data)
        if _uerr:
            raise HTTPException(413 if "MB" in _uerr else 415, _uerr)
        try:
            res = uploads.process_upload(
                data=data, filename=file.filename or "upload",
                content_type=file.content_type or "application/octet-stream",
                org_id="org", engagement_id=str(engagement_id or ""),
                vendor_id=vendor_id,
            )
        except ValueError as e:
            raise HTTPException(415, str(e))

        from datetime import datetime as _dt
        nv = _dt.fromisoformat(res.next_validation) if res.next_validation else None
        doc = Document(vendor_id=vendor_id, engagement_id=engagement_id,
                       name=file.filename or "upload", doc_type=res.doc_type,
                       object_uri=res.object_key, next_validation=nv)
        s.add(doc); s.flush()

        if res.isaac and vendor_id:
            s.add(IntelResult(vendor_id=vendor_id, engine="evidence",
                              score=res.isaac["score"], band=res.isaac["band"],
                              narrative=res.isaac["narrative"]))

        audit(s, "document.uploaded", u.username,
              {"document_id": doc.id, "doc_type": res.doc_type,
               "classified_confidence": res.classification_confidence,
               "isaac_band": res.isaac["band"] if res.isaac else None,
               "evidence_count": res.evidence_count})
        if res.needs_human:
            notify(s, f"Document '{file.filename}' needs human classification review", "all")
        s.commit()

        return {
            "document_id": doc.id,
            "object_key": res.object_key,
            "doc_type": res.doc_type,
            "classification_confidence": res.classification_confidence,
            "needs_human_review": res.needs_human,
            "page_count": res.page_count,
            "scanned_pdf": res.scanned,
            "extracted_chars": res.extracted_chars,
            "isaac": res.isaac,
            "evidence_count": res.evidence_count,
            "next_validation": res.next_validation,
        }

    # ============================================================
    #  CRUD / edit, list+search, admin, VRM, auth, reporting, email
    # ============================================================
    from fastapi.responses import PlainTextResponse
    import csv as _csv, io as _io
    from datetime import datetime as _dt2

    # ---- Vendor: update, delete, list+search, detail ----
    @app.post("/api/v1/contracts/{cid}/gap-review")
    def contract_gap_review(cid: int, s: Session = Depends(db), u: User = Depends(require("intel.contract"))):
        c = s.get(Contract, cid)
        if not c:
            raise HTTPException(404, "contract not found")
        required = json.loads(c.terms_json) if c.terms_json else []
        # deterministic gap review: in absence of a drafted contract, flag all
        # required terms as 'to confirm'; production diffs against uploaded draft.
        gaps = [t for t in required]
        c.gap_review = json.dumps({"missing_or_unconfirmed": gaps, "count": len(gaps)})
        audit(s, "contract.gap_review", u.username, {"contract_id": cid, "gaps": len(gaps)})
        s.commit()
        return {"contract_id": cid, "gap_count": len(gaps), "gaps": gaps}

    # ---- Reassessment: cadence sweep + delta ----
    @app.post("/api/v2/incidents/{iid}/notable")
    def incident_notable(iid: str, s: Session = Depends(db),
                         u: User = Depends(require("incident.view"))):
        _RBAC.assert_object_visible(s, u, 'incident', iid)
        from app.features.domain.registry_models import IncidentRecord
        from app.features.admin import notifications as NOTIF
        from app.features.domain import config_store as CFG
        r = s.scalars(select(IncidentRecord).where(IncidentRecord.incident_id == iid)).first()
        if not r and str(iid).isdigit():
            r = s.get(IncidentRecord, int(iid))
        if not r:
            raise HTTPException(404, "incident not found")
        iid = r.incident_id
        lst = CFG.get_json(s, "notable_incidents", []) or []
        if iid not in lst:
            lst.append(iid)
            CFG.upsert_json(s, "notable_incidents", lst, updated_by=u.username, category="incidents")
        NOTIF.emit(s, "incident.notable",
                   f"NOTABLE EVENT: {r.incident_type or 'Incident'} at {r.vendor_name or r.vendor_id or 'vendor'}",
                   f"{r.incident_id} · severity {r.severity or '—'} · status {r.status or '—'} · flagged by {u.username}",
                   link="incidents", audience="management", force=True)
        audit(s, "incident.notable", u.username, {"incident_id": iid}); s.commit()
        return {"id": iid, "notable": True, "notable_ids": lst}

    @app.post("/api/v2/integrity/sweep")
    def v2_integrity_sweep(b: IntegritySweepIn, s: Session = Depends(db),
                           u: User = Depends(require("integrity.view"))):
        from app.features.lifecycle import integrity as INTEG
        res = INTEG.run_sweep(s, limit=b.limit, vendor_ids=b.vendor_ids)
        audit(s, "v2.integrity_sweep", u.username,
              {"checked": res["vendors_checked"], "issues": res["health"]["issue_count"]})
        s.commit()
        return res

    @app.get("/api/v2/integrity/digest")
    def v2_integrity_digest(s: Session = Depends(db),
                            u: User = Depends(require("integrity.view"))):
        from app.features.lifecycle import integrity as INTEG
        res = INTEG.run_sweep(s)
        top = sorted(res["issues"], key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["severity"], 3))[:8]
        return {"generated_at": res["generated_at"], "health": res["health"],
                "vendors_checked": res["vendors_checked"], "top_issues": top,
                "duplicate_clusters": len(res["duplicate_clusters"])}

    @app.post("/api/v2/integrity/fix")
    def v2_integrity_fix(b: IntegrityFixIn, s: Session = Depends(db),
                         u: User = Depends(require("integrity.manage"))):
        from app.features.domain.registry_models import VendorRecord
        if b.field not in _ALLOWED_FIX_FIELDS:
            raise HTTPException(400, f"field not fixable: {b.field}")
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == b.vendor_id)).first()
        if not v:
            raise HTTPException(404, "vendor not found")
        old = getattr(v, b.field, None)
        setattr(v, b.field, b.value if b.value not in ("", None) else None)
        s.flush()
        from app.features.domain import registry_service as _RS
        n_re = _RS.schedule_reassessment(s, vendor_id=b.vendor_id,
                                         reason=f"Vendor data updated (integrity fix: {b.field})")
        audit(s, "v2.integrity_fix", u.username,
              {"vendor_id": b.vendor_id, "field": b.field, "from": old, "to": b.value,
               "reassessment_scheduled": n_re})
        s.commit()
        return {"vendor_id": b.vendor_id, "field": b.field, "value": b.value}

    @app.post("/api/v2/integrity/merge")
    def v2_integrity_merge(b: IntegrityMergeIn, s: Session = Depends(db),
                           u: User = Depends(require("integrity.manage"))):
        from app.features.domain.registry_models import (VendorRecord, EngagementRecord,
                                              AssessmentRecord, FindingRecord)
        if b.primary_vendor_id == b.duplicate_vendor_id:
            raise HTTPException(400, "primary and duplicate are the same")
        prim = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == b.primary_vendor_id)).first()
        dup = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == b.duplicate_vendor_id)).first()
        if not prim or not dup:
            raise HTTPException(404, "vendor not found")
        moved = {"engagements": 0, "assessments": 0, "findings": 0, "documents": 0}
        for e in s.scalars(select(EngagementRecord).where(EngagementRecord.vendor_id == b.duplicate_vendor_id)).all():
            e.vendor_id = b.primary_vendor_id; moved["engagements"] += 1
        for a in s.scalars(select(AssessmentRecord).where(AssessmentRecord.vendor_id == b.duplicate_vendor_id)).all():
            a.vendor_id = b.primary_vendor_id; moved["assessments"] += 1
        for f in s.scalars(select(FindingRecord).where(FindingRecord.vendor_id == b.duplicate_vendor_id)).all():
            f.vendor_id = b.primary_vendor_id; moved["findings"] += 1
        try:
            from app.features.lifecycle.documents import StoredDocument as _SD
            for d in s.scalars(select(_SD).where(_SD.vendor_id == b.duplicate_vendor_id)).all():
                d.vendor_id = b.primary_vendor_id; moved["documents"] += 1
        except Exception as _e:
            _obs_swallow('bro_app.py', _e)
        # carry over any field the primary is missing
        from app.features.lifecycle.integrity import COMPLETENESS_FIELDS as _CF
        for field, _w, _l in _CF:
            if getattr(prim, field, None) in (None, "") and getattr(dup, field, None):
                setattr(prim, field, getattr(dup, field))
        s.delete(dup); s.flush()
        audit(s, "v2.integrity_merge", u.username,
              {"primary": b.primary_vendor_id, "merged": b.duplicate_vendor_id, "moved": moved})
        s.commit()
        return {"primary_vendor_id": b.primary_vendor_id, "merged": b.duplicate_vendor_id, "moved": moved}

    @app.post("/api/v2/integrity/enrich")
    def v2_integrity_enrich(b: IntegrityVendorIn, s: Session = Depends(db),
                            u: User = Depends(require("integrity.manage"))):
        from app.features.domain.registry_models import VendorRecord
        from app.features.lifecycle import integrity as INTEG
        from app.agents import llm_config
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == b.vendor_id)).first()
        if not v:
            raise HTTPException(404, "vendor not found")
        _score, missing = INTEG.completeness(v)
        if not llm_config.status().get("live_ready"):
            return {"holding": True, "message": AI_HOLDING, "missing": missing, "suggestions": []}
        if not missing:
            return {"holding": False, "missing": [], "suggestions": []}
        prompt = "\n".join([
            f"Entity: {v.legal_name}" + (f" ({v.website})" if v.website else ""),
            f"Country (HQ): {v.hq_country or 'unknown'}.",
            "Web-search authoritative sources and return the following missing reference fields.",
            "Fields: " + ", ".join(missing),
            "JSON array only, no prose/fences.",
            "Per item: {field:str(snake_case of label),value:str,confidence:int(0-100),source:str(url)}."])
        try:
            out = llm_config.complete(
                PROMPTS.resolve(s, "enrichment_corporate"),
                prompt, domain="enrichment", web_search=True, max_tokens=700)
        except Exception:
            out = ""
        # reuse the regulatory JSON extractor
        import json as _j
        sug = []
        try:
            t = (out or "").replace("```json", "").replace("```", "").strip()
            i, e = t.find("["), t.rfind("]")
            if i != -1 and e != -1:
                arr = _j.loads(t[i:e + 1])
                sug = [x for x in arr if isinstance(x, dict) and x.get("field")]
        except Exception:
            sug = []
        audit(s, "v2.integrity_enrich", u.username, {"vendor_id": b.vendor_id, "n": len(sug)})
        s.commit()
        return {"holding": False, "missing": missing, "suggestions": sug}

    @app.post("/api/v2/integrity/chase")
    def v2_integrity_chase(b: IntegrityVendorIn, s: Session = Depends(db),
                           u: User = Depends(require("integrity.view"))):
        from app.features.domain.registry_models import VendorRecord
        from app.features.lifecycle import integrity as INTEG
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == b.vendor_id)).first()
        if not v:
            raise HTTPException(404, "vendor not found")
        want = INTEG.expected_evidence(v)
        try:
            from app.features.lifecycle.documents import StoredDocument as _SD
            have = {(d.purpose or "").lower() + " " + (d.filename or "").lower()
                    for d in s.scalars(select(_SD).where(_SD.vendor_id == b.vendor_id)).all()}
        except Exception:
            have = set()
        missing = [w for w in want if not any(w.split()[0].lower() in h for h in have)]
        return {"vendor": v.legal_name, "expected": want, "missing_evidence": missing}

    # ===== Phase 2 — Entity / ownership graph, concentration & contagion =====
    @app.post("/api/v2/incidents/match")
    def v2_incident_match(b: IncidentMatchIn, s: Session = Depends(db),
                          u: User = Depends(require("finding.view"))):
        from app.features.intelligence import exposure as EXP
        res = EXP.incident_match(s, b.vendor_id, b.description or "", b.domain)
        audit(s, "v2.incident_match", u.username,
              {"vendor_id": b.vendor_id, "matched": len(res["matched_findings"]),
               "peers": res["peer_count"]})
        s.commit()
        return res

    def _notif_light(date_of_incident, notified_at, sla_hours):
        from datetime import datetime, timezone, timedelta
        if not date_of_incident or not sla_hours:
            return None
        def _p(x):
            try:
                d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        di = _p(date_of_incident)
        if not di:
            return None
        due = di + timedelta(hours=sla_hours)
        if notified_at:
            n = _p(notified_at)
            if not n:
                return "amber"
            return "green" if n <= due else "red"
        return "amber" if datetime.now(timezone.utc) <= due else "red"

    def _inc_out(r):
        return {
            "incident_id": r.incident_id, "date_of_incident": r.date_of_incident,
            "reported_date": r.reported_date, "reported_by": r.reported_by,
            "vendor_id": r.vendor_id, "vendor_name": r.vendor_name,
            "engagement_id": r.engagement_id,
            "active_engagements": json.loads(r.active_engagements or "[]"),
            "incident_type": r.incident_type, "severity": r.severity,
            "customer_impacting": r.customer_impacting, "impacts_client_org": r.impacts_client_org,
            "impact_description": r.impact_description, "region": json.loads(r.region or "[]"),
            "root_cause_assessment": r.root_cause_assessment,
            "risk_entry_needed": r.risk_entry_needed, "risk_entry_ref": r.risk_entry_ref,
            "notes_log": json.loads(r.notes_log or "[]"),
            "attachments": json.loads(r.attachments or "[]"), "status": r.status,
            "vendor_notified_at": r.vendor_notified_at,
            "notification_sla_hours": r.notification_sla_hours,
            "notification_compliant": r.notification_compliant,
            "contract_notification_summary": r.contract_notification_summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "created_by": r.created_by,
        }

    def _inc_get(s, iid):
        from app.features.domain.registry_models import IncidentRecord
        r = s.scalars(select(IncidentRecord).where(IncidentRecord.incident_id == iid)).first()
        if not r:
            raise HTTPException(404, "incident not found")
        return r

    @app.get("/api/v2/incidents")
    def v2_incidents_list(status: str = None, severity: str = None, vendor_id: str = None,
                          s: Session = Depends(db), u: User = Depends(require("incident.view"))):
        from app.features.domain.registry_models import IncidentRecord
        rows = s.scalars(select(IncidentRecord).order_by(IncidentRecord.id.desc())).all()
        out = []
        for r in rows:
            if status and r.status != status:
                continue
            if severity and r.severity != severity:
                continue
            if vendor_id and r.vendor_id != vendor_id:
                continue
            out.append(_inc_out(r))
        return out

    @app.post("/api/v2/incidents")
    def v2_incidents_create(b: IncidentIn, s: Session = Depends(db),
                            u: User = Depends(require("incident.manage"))):
        from app.features.domain.registry_models import IncidentRecord, VendorRecord, EngagementRecord
        from app.features.domain import registry_service as RS
        iid = RS.next_id(s, "incident")
        vname = None
        active = []
        if b.vendor_id:
            v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == b.vendor_id)).first()
            vname = v.legal_name if v else None
            # auto-tag active engagements
            active = [e.engagement_id for e in s.scalars(select(EngagementRecord).where(
                EngagementRecord.vendor_id == b.vendor_id)).all() if (e.status or "Active") == "Active"]
        from app.features.domain import config_store as _CFG
        _sla_map = _CFG.incident_sla_map(s)
        sla = b.notification_sla_hours or _sla_map.get(b.severity or "Medium", 72)
        light = _notif_light(b.date_of_incident, b.vendor_notified_at, sla)
        r = IncidentRecord(
            incident_id=iid, date_of_incident=b.date_of_incident,
            reported_date=b.reported_date, reported_by=b.reported_by or u.username,
            vendor_id=b.vendor_id, vendor_name=vname,
            engagement_id=b.engagement_id,
            active_engagements=json.dumps(active), incident_type=b.incident_type,
            severity=b.severity or "Medium", customer_impacting=bool(b.customer_impacting),
            impacts_client_org=bool(b.impacts_client_org), impact_description=b.impact_description,
            region=json.dumps(b.region or []), root_cause_assessment=b.root_cause_assessment,
            risk_entry_needed=bool(b.risk_entry_needed), status=b.status or "Drafted",
            vendor_notified_at=b.vendor_notified_at, notification_sla_hours=sla,
            notification_compliant=light, created_by=u.username)
        s.add(r)
        audit(s, "v2.incident_create", u.username, {"incident_id": iid, "vendor_id": b.vendor_id,
              "severity": r.severity, "auto_tagged": len(active)})
        notify(s, f"Supplier incident {iid} raised ({r.severity})", "all")
        s.commit()
        return _inc_out(r)

    @app.get("/api/v2/incidents/{iid}")
    def v2_incident_get(iid: str, s: Session = Depends(db), u: User = Depends(require("incident.view"))):
        _RBAC.assert_object_visible(s, u, 'incident', iid)
        return _inc_out(_inc_get(s, iid))

    @app.put("/api/v2/incidents/{iid}")
    def v2_incident_update(iid: str, b: IncidentIn, s: Session = Depends(db),
                           u: User = Depends(require("incident.manage"))):
        r = _inc_get(s, iid)
        for f in ("date_of_incident", "reported_date", "reported_by", "incident_type",
                  "severity", "impact_description", "root_cause_assessment", "status",
                  "vendor_notified_at", "engagement_id"):
            v = getattr(b, f)
            if v is not None:
                setattr(r, f, v)
        if b.customer_impacting is not None:
            r.customer_impacting = bool(b.customer_impacting)
        if b.impacts_client_org is not None:
            r.impacts_client_org = bool(b.impacts_client_org)
        if b.risk_entry_needed is not None:
            r.risk_entry_needed = bool(b.risk_entry_needed)
        if b.region is not None:
            r.region = json.dumps(b.region)
        if b.notification_sla_hours is not None:
            r.notification_sla_hours = b.notification_sla_hours
        if not r.notification_sla_hours:
            from app.features.domain import config_store as _CFG
            r.notification_sla_hours = _CFG.incident_sla_map(s).get(r.severity or "Medium", 72)
        r.notification_compliant = _notif_light(r.date_of_incident, r.vendor_notified_at, r.notification_sla_hours)
        audit(s, "v2.incident_update", u.username, {"incident_id": iid, "status": r.status})
        s.commit()
        return _inc_out(r)

    @app.post("/api/v2/incidents/{iid}/note")
    def v2_incident_note(iid: str, b: IncidentNoteIn, s: Session = Depends(db),
                         u: User = Depends(require("incident.manage"))):
        _RBAC.assert_object_visible(s, u, 'incident', iid)
        import datetime as _dt
        r = _inc_get(s, iid)
        log = json.loads(r.notes_log or "[]")
        log.append({"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                    "user": u.username, "note": b.note})
        r.notes_log = json.dumps(log)
        audit(s, "v2.incident_note", u.username, {"incident_id": iid})
        s.commit()
        return _inc_out(r)

    @app.post("/api/v2/incidents/{iid}/attach")
    def v2_incident_attach(iid: str, b: IncidentAttachIn, s: Session = Depends(db),
                           u: User = Depends(require("incident.manage"))):
        _RBAC.assert_object_visible(s, u, 'incident', iid)
        r = _inc_get(s, iid)
        att = json.loads(r.attachments or "[]")
        att.append(b.name)
        r.attachments = json.dumps(att)
        audit(s, "v2.incident_attach", u.username, {"incident_id": iid, "name": b.name})
        s.commit()
        return _inc_out(r)

    @app.post("/api/v2/incidents/{iid}/draft-risk")
    def v2_incident_draft_risk(iid: str, s: Session = Depends(db),
                               u: User = Depends(require("incident.manage"))):
        _RBAC.assert_object_visible(s, u, 'incident', iid)
        from app.features.domain import registry_service as RS
        from app.agents import llm_config
        r = _inc_get(s, iid)
        engs = json.loads(r.active_engagements or "[]")
        summary = (f"Incident {r.incident_id} ({r.severity}, {r.incident_type or 'incident'}) for "
                   f"{r.vendor_name or r.vendor_id}. Impact: {r.impact_description or 'n/a'}. "
                   f"Root cause: {r.root_cause_assessment or 'n/a'}.")
        title = f"Risk from incident {r.incident_id}: {(r.incident_type or 'supplier incident')}"
        description = summary
        remediation = "Confirm containment, validate root-cause remediation, and re-test affected controls."
        if llm_config.status().get("live_ready"):
            try:
                out = llm_config.complete(
                    PROMPTS.resolve(s, "incident_risk_entry"),
                    summary, domain="risk", max_tokens=600)
                t = (out or "").replace("```json", "").replace("```", "").strip()
                i, e = t.find("{"), t.rfind("}")
                d = json.loads(t[i:e + 1]) if (i != -1 and e != -1) else {}
                title = d.get("title") or title
                description = d.get("description") or description
                remediation = d.get("suggested_remediation") or remediation
            except Exception as _e:
                _obs_swallow('bro_app.py', _e)
        f = RS.create_finding(s, title=title, severity=r.severity or "Medium", source="Incident",
                              description=description, suggested_remediation=remediation,
                              vendor_id=r.vendor_id, engagement_id=(engs[0] if engs else None),
                              status="Draft")
        r.risk_entry_needed = True
        r.risk_entry_ref = f.finding_id
        audit(s, "v2.incident_draft_risk", u.username, {"incident_id": iid, "finding_id": f.finding_id})
        s.commit()
        return {"finding_id": f.finding_id, "title": title, "incident_id": iid}

    @app.post("/api/v2/incidents/{iid}/contract-summary")
    def v2_incident_contract_summary(iid: str, s: Session = Depends(db),
                                     u: User = Depends(require("incident.view"))):
        _RBAC.assert_object_visible(s, u, 'incident', iid)
        from app.agents import llm_config
        r = _inc_get(s, iid)
        light = _notif_light(r.date_of_incident, r.vendor_notified_at, r.notification_sla_hours)
        r.notification_compliant = light
        # locate a contract document for the vendor (demonstrator)
        contract_text = None
        try:
            from app.features.lifecycle.documents import StoredDocument as _SD
            doc = s.scalars(select(_SD).where(_SD.vendor_id == r.vendor_id)).first()
            contract_text = (doc.content if doc and getattr(doc, "content", None) else None)
        except Exception:
            contract_text = None
        if not llm_config.status().get("live_ready"):
            r.contract_notification_summary = None
            s.commit()
            return {"holding": True, "message": AI_HOLDING, "traffic_light": light,
                    "sla_hours": r.notification_sla_hours}
        prompt = ("Summarise the supplier's INCIDENT-NOTIFICATION obligation from this contract "
                  "(required notification window, to whom, and any conditions). If no contract text is "
                  "available, state the typical market obligation for this severity. Be concise (3-4 lines).\n\n"
                  f"Severity: {r.severity}. Contract text: {contract_text or '[not on file]'}")
        try:
            summ = llm_config.complete(PROMPTS.resolve(s, "contract_summary"), prompt,
                                       domain="legal", max_tokens=400)
        except Exception:
            summ = None
        r.contract_notification_summary = (summ or "").strip() or None
        audit(s, "v2.incident_contract_summary", u.username, {"incident_id": iid, "light": light})
        s.commit()
        return {"holding": False, "summary": r.contract_notification_summary,
                "traffic_light": light, "sla_hours": r.notification_sla_hours,
                "vendor_notified_at": r.vendor_notified_at, "date_of_incident": r.date_of_incident}

    @app.get("/api/v2/incidents/{iid}/warroom")
    def v2_incident_warroom(iid: str, s: Session = Depends(db),
                            u: User = Depends(require("incident.view"))):
        _RBAC.assert_object_visible(s, u, 'incident', iid)
        from app.features.intelligence import exposure as EXP
        from app.features.domain.registry_models import (EngagementRecord, FourthPartyVendor,
                                              FourthPartyRecord)
        from app.agents import llm_config
        r = _inc_get(s, iid)
        vid = r.vendor_id
        active = json.loads(r.active_engagements or "[]")
        engs = s.scalars(select(EngagementRecord).where(EngagementRecord.vendor_id == vid)).all() if vid else []
        eng_map = {e.engagement_id: e for e in engs}
        affected = [eng_map[e] for e in active if e in eng_map] or engs
        bus = sorted({e.business_unit for e in affected if e.business_unit})
        affected_out = [{"engagement_id": e.engagement_id, "title": e.title,
                         "business_unit": e.business_unit, "inherent_band": e.inherent_band,
                         "residual_band": e.residual_band,
                         "annual_value": round(float(e.annual_value or 0))} for e in affected]
        # incident → issue matching (open findings implicated + peers with same gap)
        desc = " ".join(x for x in [r.impact_description, r.root_cause_assessment] if x)
        match = EXP.incident_match(s, vid, desc, r.incident_type) if vid else {"matched_findings": [], "peer_exposure": [], "peer_count": 0}
        # BU exposure profiles for the affected BUs
        bu_all = EXP.bu_exposure(s)["business_units"]
        bu_prof = [b for b in bu_all if b["business_unit"] in bus]
        # fourth-party concentration the vendor relies on (+ SPOF)
        links = s.scalars(select(FourthPartyVendor)).all()
        cnt = {}
        for ln in links:
            cnt.setdefault(ln.fourth_party_id, []).append(ln.vendor_id)
        total = len({ln.vendor_id for ln in links}) or 1
        fps = {f.fourth_party_id: f for f in s.scalars(select(FourthPartyRecord)).all()}
        fp_ids = [ln.fourth_party_id for ln in links if ln.vendor_id == vid]
        fourth = [{"fourth_party_id": fid, "legal_name": (fps[fid].legal_name if fid in fps else fid),
                   "shared_with": len(cnt.get(fid, [])),
                   "spof": len(cnt.get(fid, [])) >= max(10, total * 0.15)} for fid in fp_ids]
        fourth.sort(key=lambda x: -x["shared_with"])
        light = _notif_light(r.date_of_incident, r.vendor_notified_at, r.notification_sla_hours)
        # Ecosystem impact — UPSTREAM vendors: those who declared THIS vendor as their 4th party
        upstream = []
        if vid:
            from app.features.domain.registry_models import VendorRecord as _VR
            vmap = {v.vendor_id: v.legal_name for v in s.scalars(select(_VR)).all()}
            self_fp_ids = [f.fourth_party_id for f in s.scalars(select(FourthPartyRecord)
                           .where(FourthPartyRecord.vendor_id == vid)).all()]
            seen_up = set()
            for ln in links:
                if ln.fourth_party_id in self_fp_ids and ln.vendor_id and ln.vendor_id != vid \
                        and ln.vendor_id not in seen_up:
                    seen_up.add(ln.vendor_id)
                    upstream.append({"vendor_id": ln.vendor_id,
                                     "legal_name": vmap.get(ln.vendor_id, ln.vendor_id)})
        stats = {
            "engagements_affected": len(affected), "bus_affected": len(bus),
            "peers_same_gap": match["peer_count"], "open_findings_matched": len(match["matched_findings"]),
            "fourth_party_deps": len(fourth), "spof_deps": sum(1 for x in fourth if x["spof"]),
        }
        brief = (f"{r.severity} {r.incident_type or 'incident'} at {r.vendor_name or vid}. "
                 f"{stats['engagements_affected']} engagement(s) across {stats['bus_affected']} business unit(s) affected; "
                 f"{stats['open_findings_matched']} open finding(s) directly implicated; "
                 f"{stats['peers_same_gap']} peer vendor(s) carry the same unremediated gap. "
                 f"Vendor notification status: {(light or 'n/a').upper()}."
                 + (f" Concentration risk: relies on {stats['spof_deps']} single-point-of-failure sub-provider(s)." if stats['spof_deps'] else ""))
        ai = False
        if llm_config.status().get("live_ready"):
            try:
                out = llm_config.complete(
                    PROMPTS.resolve(s, "incident_board_note"),
                    f"Incident: {r.severity} {r.incident_type} at {r.vendor_name}. Impact: {r.impact_description}. RCA: {r.root_cause_assessment}. "
                    f"Systemic: {brief}", domain="risk", max_tokens=400)
                if out and out.strip():
                    brief = out.strip(); ai = True
            except Exception as _e:
                _obs_swallow('bro_app.py', _e)
        return {"incident": _inc_out(r), "sla_light": light, "stats": stats,
                "affected_engagements": affected_out, "business_units": bu_prof,
                "matched_findings": match["matched_findings"], "peer_exposure": match["peer_exposure"],
                "fourth_party_deps": fourth, "upstream_vendors": upstream, "brief": brief, "brief_ai": ai}

    @app.post("/api/v2/documents/upload")
    def v2_doc_upload(b: DocUploadIn, s: Session = Depends(db),
                      u: User = Depends(require("lifecycle.documents"))):
        from app.features.lifecycle import documents as DOC
        out = []
        for f in b.files:
            try:
                row = DOC.store_document(s, filename=f.filename, content_type=f.content_type or "",
                                         data_b64=f.data_b64, vendor_id=b.vendor_id,
                                         engagement_id=b.engagement_id, uploaded_by=u.username,
                                         purpose=b.purpose)
            except ValueError as e:
                raise HTTPException(422, str(e))
            out.append({"doc_id": row.doc_id, "filename": row.filename, "size": row.size_bytes})
        audit(s, "v2.doc_upload", u.username, {"count": len(out), "purpose": b.purpose})
        s.commit()
        return {"documents": out}

    @app.get("/api/v2/documents")
    def v2_doc_list(purpose: str = "", vendor_id: str = "", ai_only: bool = False,
                    s: Session = Depends(db), u: User = Depends(require("lifecycle.documents"))):
        """List stored documents/reports. ai_only filters to AI-generated reports;
        purpose/vendor_id narrow further. Used by the Documents and AI Reports views."""
        from app.features.lifecycle.documents import StoredDocument
        from app.features.domain.registry_models import VendorRecord
        from sqlalchemy.orm import defer
        AI_PURPOSES = ("fdd_report", "reputation_report", "fdd_reputation_report", "proassess_report")
        # Never load the base64 blob for a list view — it is the single biggest
        # over-fetch (file content is 100s of KB/row and is not serialized here).
        q = s.query(StoredDocument).options(defer(StoredDocument.data_b64))
        if purpose:
            q = q.filter(StoredDocument.purpose == purpose)
        if vendor_id:
            q = q.filter(StoredDocument.vendor_id == vendor_id)
        if ai_only:
            q = q.filter(StoredDocument.purpose.in_(AI_PURPOSES))
        rows = q.order_by(StoredDocument.id.desc()).all()
        vmap = {v.vendor_id: v.legal_name for v in s.query(VendorRecord).all()}
        return {"documents": [{
            "doc_id": d.doc_id, "filename": d.filename, "purpose": d.purpose,
            "content_type": d.content_type, "size_bytes": d.size_bytes,
            "vendor_id": d.vendor_id, "vendor_name": vmap.get(d.vendor_id) if d.vendor_id else None,
            "engagement_id": d.engagement_id, "uploaded_by": d.uploaded_by,
            "is_ai_report": d.purpose in AI_PURPOSES,
            "url": f"/api/v2/documents/{d.doc_id}",
            "created_at": d.created_at.isoformat() if d.created_at else None,
        } for d in rows]}

    @app.get("/api/v2/documents/{doc_id}")
    def v2_doc_get(doc_id: str, s: Session = Depends(db),
                   u: User = Depends(require("lifecycle.documents"))):
        from app.features.lifecycle import documents as DOC
        import base64 as _b64
        from fastapi import Response
        d = DOC.get_document(s, doc_id)
        if not d:
            raise HTTPException(404, "document not found")
        raw = _b64.b64decode(d.data_b64 or "")
        return Response(content=raw, media_type=d.content_type,
                        headers={"Content-Disposition": f'inline; filename="{d.filename}"'})

    @app.post("/api/v2/contracts/terms")
    def v2_contract_terms(b: ContractTermsIn, s: Session = Depends(db),
                          u: User = Depends(require("intel.contract"))):
        from app.features.lifecycle import contracts as CON
        from app.features.intelligence import entity_resolve as ER
        ent = ER.resolve_entity(s, vendor_id=b.vendor_id, other_name=b.other_name)
        terms = CON.required_terms(b.inherent_band, b.exposure or {})
        audit(s, "v2.contract_terms", u.username,
              {"inherent": b.inherent_band, "count": len(terms), "entity": ent["vendor_name"]})
        s.commit()
        return {"inherent_band": b.inherent_band, "required_terms": terms,
                "count": len(terms), "entity": ent}

    @app.post("/api/v2/contracts/gap-report")
    def v2_contract_gap(b: ContractGapIn, s: Session = Depends(db),
                        u: User = Depends(require("intel.contract"))):
        from app.features.lifecycle import contracts as CON
        rep = CON.gap_report(b.contract_text, b.inherent_band, b.exposure or {})
        audit(s, "v2.contract_gap_report", u.username,
              {"gaps": len(rep["gaps"]), "critical": rep["critical_gaps"]})
        s.commit()
        return rep

    @app.post("/api/v2/contracts/diff")
    def v2_contract_diff(b: ContractDiffIn, s: Session = Depends(db),
                         u: User = Depends(require("intel.contract"))):
        from app.features.lifecycle import contracts as CON
        rep = CON.existing_vs_to_add(b.inherent_band, b.exposure or {},
                                     b.prior_contract_texts or [])
        audit(s, "v2.contract_diff", u.username,
              {"existing": len(rep["terms_already_existing"]),
               "to_add": len(rep["terms_to_be_added"])})
        s.commit()
        return rep

    @app.post("/api/v2/contracts/gap-from-document")
    def v2_contract_gap_doc(b: ContractGapDocIn, s: Session = Depends(db),
                            u: User = Depends(require("intel.contract"))):
        """CR-12: upload a contract document; AI extracts terms; gap review runs against
        the required terms for the engagement's inherent band. For a REGISTERED engagement
        the inherent band and exposure are inherited automatically; only an 'Other' vendor
        is prompted for the band."""
        from app.features.lifecycle import documents as DOC
        from app.features.lifecycle import contracts as CON
        from app.features.domain import master_service as MS
        band = b.inherent_band
        exposure = {}
        engagement_id = b.engagement_id
        vendor_id = b.vendor_id
        # inherit from the engagement where registered
        if engagement_id:
            eng = MS.engagement_full(s, engagement_id)
            if not eng:
                raise HTTPException(404, "engagement not found")
            base = eng.get("base", {}); ext = eng.get("ext", {}) or {}
            band = base.get("inherent_band") or band
            vendor_id = base.get("vendor_id") or vendor_id
            # derive exposure flags from engagement risk fields
            exposure = {
                "personal_data": bool(ext.get("personal_data")),
                "cross_border": bool(ext.get("cross_border")),
                "mission_critical": bool(ext.get("mission_critical")),
                "regulated": bool(ext.get("regulated_activity")),
            }
        if not band:
            raise HTTPException(422, "inherent band required for an 'Other' (unregistered) vendor")
        # store + extract
        try:
            doc = DOC.store_document(s, filename=b.file.filename,
                                     content_type=b.file.content_type or "",
                                     data_b64=b.file.data_b64, vendor_id=vendor_id,
                                     engagement_id=engagement_id, uploaded_by=u.username,
                                     purpose="contract")
        except ValueError as e:
            raise HTTPException(422, str(e))
        terms = DOC.extract_contract_terms(s, doc)
        text = DOC._decode_text(doc)
        rep = CON.gap_report(text, band, exposure)
        audit(s, "v2.contract_gap_doc", u.username,
              {"doc_id": doc.doc_id, "engagement_id": engagement_id,
               "gaps": len(rep["gaps"])})
        s.commit()
        return {"doc_id": doc.doc_id, "doc_link": f"/api/v2/documents/{doc.doc_id}",
                "inherited_from_engagement": bool(engagement_id),
                "inherent_band": band, "exposure": exposure,
                "extracted_terms": terms, "gap_report": rep,
                "readable": terms.get("readable", False)}

    # ---- management dashboard + chat (leadership-gated) ----
    @app.get("/api/v2/exit/portfolio")
    def v2_exit_portfolio(s: Session = Depends(db), u: User = Depends(require("engagement.view"))):
        from app.features.lifecycle import exit_planning as EX
        return EX.portfolio(s)

    @app.get("/api/v2/exit/triggers")
    def v2_exit_trig_cat(u: User = Depends(require("engagement.view"))):
        from app.features.lifecycle import exit_planning as EX
        return {"catalogue": EX.TRIGGER_CATALOGUE, "strategies": EX.STRATEGY_LABELS}

    @app.post("/api/v2/exit/triggers/scan")
    def v2_exit_trig_scan(s: Session = Depends(db), u: User = Depends(require("lifecycle.offboard"))):
        from app.features.lifecycle import exit_planning as EX
        fired = EX.scan_triggers(s)
        audit(s, "exit.trigger_scan", u.username, {"fired": fired})
        s.commit()
        return {"fired": fired}

    @app.get("/api/v2/exit/plan/{vendor_id}")
    def v2_exit_get(vendor_id: str, s: Session = Depends(db), u: User = Depends(require("engagement.view"))):
        from app.features.lifecycle import exit_planning as EX
        data = EX.plan_full(s, vendor_id)
        s.commit()
        return data

    @app.post("/api/v2/exit/plan/{vendor_id}/ai-draft")
    def v2_exit_ai_draft(vendor_id: str, s: Session = Depends(db),
                         u: User = Depends(require("engagement.view"))):
        """Viny drafts an exit plan from organisation data (+ public web data when a live
        model is configured). Returns a draft for review — it does not save anything."""
        from app.features.lifecycle import exit_planning as EX
        from app.agents import llm_config
        import json as _json
        ctx = EX.draft_context(s, vendor_id)
        draft = EX.deterministic_draft(ctx)
        engine, sources = "rules", []
        if llm_config.status().get("live_ready"):
            try:
                system = (PROMPTS.resolve(s, "exit_plan_persona") + "\n\n"
                          + PROMPTS.resolve(s, "exit_plan_draft"))
                raw = llm_config.complete(system, "ORGANISATION DATA (JSON):\n" + _json.dumps(ctx),
                                          domain="exit", web_search=True, max_tokens=1600) or ""
                from app.features.assessment.ai_json import parse_json_strict
                ai = parse_json_strict(raw)
                if ai:
                    for k in ("strategy_type", "target_window", "rationale", "impact_summary",
                              "data_plan", "comms_plan"):
                        if ai.get(k):
                            draft[k] = ai[k]
                    if isinstance(ai.get("steps"), list) and ai["steps"]:
                        draft["steps"] = ai["steps"]
                    if isinstance(ai.get("alternatives"), list):
                        draft["alternatives"] = ai["alternatives"]
                    sources = ai.get("sources") or []
                    engine = "ai"
            except Exception:
                engine = "rules"
        audit(s, "exit.ai_draft", u.username, {"vendor_id": vendor_id, "engine": engine})
        s.commit()
        return {"engine": engine, "by": "Viny", "draft": draft, "sources": sources,
                "context_used": {k: ctx[k] for k in
                                 ("vendor_name", "is_critical", "residual_band", "dependencies",
                                  "existing_alternatives", "contract_exit_clause")}}

    @app.put("/api/v2/exit/plan/{vendor_id}")
    def v2_exit_put(vendor_id: str, b: ExitPlanIn, s: Session = Depends(db),
                    u: User = Depends(require("lifecycle.offboard"))):
        from app.features.lifecycle import exit_planning as EX
        EX.upsert_plan(s, vendor_id, b.model_dump(exclude_none=True))
        audit(s, "exit.plan_saved", u.username, {"vendor_id": vendor_id})
        s.commit()
        return EX.plan_full(s, vendor_id)

    @app.post("/api/v2/exit/plan/{vendor_id}/child")
    def v2_exit_child_add(vendor_id: str, b: ExitChildIn, s: Session = Depends(db),
                          u: User = Depends(require("lifecycle.offboard"))):
        from app.features.lifecycle import exit_planning as EX
        if b.kind == "alternative":
            EX.add_alternative(s, vendor_id, b.name or "Alternative", b.prequalified, b.lead_time_days, b.viability, b.note)
        elif b.kind == "step":
            EX.add_step(s, vendor_id, b.description or "Step", b.owner, b.duration_days, b.rto, b.rpo, b.dependency)
        elif b.kind == "dependency":
            EX.add_dependency(s, vendor_id, b.service_name or "Service", b.impact_tolerance, b.max_downtime, b.criticality)
        else:
            raise HTTPException(400, "unknown child kind")
        audit(s, "exit.child_added", u.username, {"vendor_id": vendor_id, "kind": b.kind})
        s.commit()
        return EX.plan_full(s, vendor_id)

    @app.delete("/api/v2/exit/plan/{vendor_id}/child/{kind}/{cid}")
    def v2_exit_child_del(vendor_id: str, kind: str, cid: int, s: Session = Depends(db),
                          u: User = Depends(require("lifecycle.offboard"))):
        from app.features.lifecycle import exit_planning as EX
        EX.remove_child(s, kind, cid, vendor_id)
        s.commit()
        return EX.plan_full(s, vendor_id)

    @app.post("/api/v2/exit/plan/{vendor_id}/test")
    def v2_exit_test(vendor_id: str, b: ExitTestIn, s: Session = Depends(db),
                     u: User = Depends(require("lifecycle.offboard"))):
        from app.features.lifecycle import exit_planning as EX
        EX.log_test(s, vendor_id, method=b.method, outcome=b.outcome, lessons=b.lessons,
                    participants=b.participants, passed=b.passed)
        audit(s, "exit.test_logged", u.username, {"vendor_id": vendor_id, "method": b.method, "passed": b.passed})
        s.commit()
        return EX.plan_full(s, vendor_id)

    @app.post("/api/v2/exit/plan/{vendor_id}/attest")
    def v2_exit_attest(vendor_id: str, s: Session = Depends(db),
                       u: User = Depends(require("lifecycle.offboard"))):
        from app.features.lifecycle import exit_planning as EX
        EX.attest(s, vendor_id)
        audit(s, "exit.attested", u.username, {"vendor_id": vendor_id})
        s.commit()
        return EX.plan_full(s, vendor_id)

    @app.post("/api/v2/exit/plan/{vendor_id}/invoke")
    def v2_exit_invoke(vendor_id: str, b: ExitInvokeIn, s: Session = Depends(db),
                       u: User = Depends(require("lifecycle.offboard"))):
        from app.features.lifecycle import exit_planning as EX
        res = EX.invoke(s, vendor_id, mode=b.mode)
        audit(s, "exit.invoked", u.username, {"vendor_id": vendor_id, "mode": b.mode})
        notify(s, f"Exit invoked ({b.mode}) for {vendor_id}", "vrm")
        s.commit()
        return res

    @app.post("/api/v2/contracts")
    def v2_contract_create(b: ContractCreateIn, s: Session = Depends(db),
                           u: User = Depends(require("intel.contract"))):
        from app.features.domain import master_service as MS
        if not b.vendor_id and not b.engagement_id:
            raise HTTPException(400, "a contract must link to a vendor (MSA) or an engagement (Contract/PO)")
        row = MS.create_contract(s, contract_type=b.contract_type, vendor_id=b.vendor_id,
                                 engagement_id=b.engagement_id, parent_msa=b.parent_msa,
                                 data=b.data or {})
        audit(s, "v2.contract_create", u.username,
              {"contract_id": row.contract_id, "type": row.contract_type,
               "primary": row.primary_link})
        s.commit()
        return {"contract_id": row.contract_id, "primary_link": row.primary_link,
                "vendor_id": row.vendor_id, "engagement_id": row.engagement_id,
                "contract_type": row.contract_type}

    @app.get("/api/v2/contracts")
    def v2_contract_list(vendor_id: Optional[str] = None, engagement_id: Optional[str] = None,
                         s: Session = Depends(db), u: User = Depends(require("intel.contract"))):
        from app.features.domain import master_service as MS
        return MS.list_contracts(s, vendor_id=vendor_id, engagement_id=engagement_id)

    @app.put("/api/v2/contracts/{cid}")
    def v2_contract_update(cid: str, b: ContractUpdateIn, s: Session = Depends(db),
                           u: User = Depends(require("intel.contract"))):
        from app.features.domain import master_service as MS
        row = MS.update_contract(s, cid, b.data)
        if not row:
            raise HTTPException(404, "contract not found")
        audit(s, "v2.contract_update", u.username, {"contract_id": cid})
        s.commit()
        return {"contract_id": row.contract_id, "status": row.status}

    @app.post("/api/v2/contracts/migrate-v1")
    def v2_contract_migrate(s: Session = Depends(db),
                            u: User = Depends(require("intel.contract"))):
        from app.features.domain import master_service as MS
        n = MS.migrate_v1_contracts(s)
        audit(s, "v2.contract_migrate_v1", u.username, {"migrated": n})
        s.commit()
        return {"migrated": n}

    @app.post("/api/v2/performance/scorecards")
    def v2_perf_create(b: ScorecardCreateIn, s: Session = Depends(db),
                       u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        try:
            sc = MS.create_scorecard(s, b.vendor_id, b.period_label,
                                     period_start=b.period_start, period_end=b.period_end,
                                     cadence=b.cadence)
        except ValueError as e:
            raise HTTPException(409, str(e))
        MS.auto_source_kpis(s, sc.scorecard_id)
        MS.compute_scorecard(s, sc.scorecard_id)
        audit(s, "v2.scorecard_create", u.username,
              {"scorecard_id": sc.scorecard_id, "vendor_id": b.vendor_id})
        s.commit()
        return MS.get_scorecard(s, sc.scorecard_id)

    @app.get("/api/v2/performance/scorecards/{sid}")
    def v2_perf_get(sid: str, s: Session = Depends(db),
                    u: User = Depends(require("vendor.view"))):
        from app.features.domain import master_service as MS
        sc = MS.get_scorecard(s, sid)
        if not sc:
            raise HTTPException(404, "scorecard not found")
        return sc

    # CR-11: performance enrolment (any vendor, not only critical)
    @app.get("/api/v2/performance/enrolment")
    def v2_perf_enrolment_list(s: Session = Depends(db),
                               u: User = Depends(require("vendor.view"))):
        from app.features.domain import master_service as MS
        return MS.list_perf_enrolment(s)

    @app.post("/api/v2/performance/enrolment")
    def v2_perf_enrol(b: PerfEnrolIn, s: Session = Depends(db),
                      u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        added = []
        for vid in b.vendor_ids:
            MS.enrol_vendor(s, vid, source="manual", user=u.username)
            added.append(vid)
        audit(s, "v2.perf_enrol", u.username, {"vendors": added})
        s.commit()
        return {"enrolled": added}

    @app.delete("/api/v2/performance/enrolment/{vid}")
    def v2_perf_unenrol(vid: str, s: Session = Depends(db),
                        u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        ok = MS.unenrol_vendor(s, vid)
        audit(s, "v2.perf_unenrol", u.username, {"vendor_id": vid})
        s.commit()
        return {"unenrolled": ok}

    @app.get("/api/v2/performance/vendor/{vid}")
    def v2_perf_list(vid: str, s: Session = Depends(db),
                     u: User = Depends(require("vendor.view"))):
        _RBAC.assert_object_visible(s, u, "vendor", vid)
        from app.features.domain import master_service as MS
        return MS.list_scorecards(s, vid)

    @app.put("/api/v2/performance/kpi/{kpi_id}")
    def v2_perf_kpi(kpi_id: int, b: KPIScoreIn, s: Session = Depends(db),
                    u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        row = MS.set_kpi_score(s, kpi_id, actual=b.actual, score=b.score,
                               excluded=b.excluded, exclude_reason=b.exclude_reason)
        if not row:
            raise HTTPException(404, "kpi not found")
        MS.compute_scorecard(s, row.scorecard_id)
        s.commit()
        return MS.get_scorecard(s, row.scorecard_id)

    @app.post("/api/v2/performance/scorecards/{sid}/recompute")
    def v2_perf_recompute(sid: str, s: Session = Depends(db),
                          u: User = Depends(require("vendor.view"))):
        from app.features.domain import master_service as MS
        # recompute only; auto-sourcing happens at creation or via explicit re-source
        res = MS.compute_scorecard(s, sid)
        s.commit()
        return res

    @app.post("/api/v2/performance/scorecards/{sid}/resource")
    def v2_perf_resource(sid: str, s: Session = Depends(db),
                         u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        n = MS.auto_source_kpis(s, sid)
        res = MS.compute_scorecard(s, sid)
        s.commit()
        return {"sourced": n, **res}

    @app.post("/api/v2/performance/scorecards/{sid}/agree")
    def v2_perf_agree(sid: str, b: AgreeIn, s: Session = Depends(db),
                      u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        sc = MS.agree_scorecard(s, sid, b.party)
        if not sc:
            raise HTTPException(404, "scorecard not found")
        audit(s, "v2.scorecard_agree", u.username, {"scorecard_id": sid, "party": b.party})
        s.commit()
        return {"scorecard_id": sid, "status": sc.status, "agreed_with_vendor": True}

    @app.post("/api/v2/performance/scorecards/{sid}/publish")
    def v2_perf_publish(sid: str, s: Session = Depends(db),
                        u: User = Depends(require("vendor.critical"))):
        from app.features.domain import master_service as MS
        res = MS.publish_scorecard(s, sid, u.username)
        if not res:
            raise HTTPException(404, "scorecard not found")
        audit(s, "v2.scorecard_publish", u.username,
              {"scorecard_id": sid, "score": res.get("composite_score")})
        s.commit()
        return res

    @app.post("/api/v2/performance/vendor/{vid}/reviews")
    def v2_perf_review_create(vid: str, b: ReviewIn, s: Session = Depends(db),
                              u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        row = MS.create_review(s, vid, b.data)
        audit(s, "v2.perf_review", u.username, {"review_id": row.review_id, "vendor_id": vid})
        s.commit()
        return {"review_id": row.review_id, "review_date": row.review_date}

    @app.post("/api/v2/performance/reviews/{rid}/acknowledge")
    def v2_perf_review_ack(rid: str, s: Session = Depends(db),
                           u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        row = MS.acknowledge_review(s, rid)
        if not row:
            raise HTTPException(404, "review not found")
        s.commit()
        return {"review_id": rid, "vendor_acknowledged": True}

    # ================= SLA MANAGEMENT (Performance) =================
    from app.features.lifecycle import performance_service as PERF

    @app.get("/api/v2/performance-issues")
    def v2_list_perf_issues(engagement_id: Optional[str] = None, vendor_id: Optional[str] = None,
                            status: Optional[str] = None, severity: Optional[str] = None,
                            source: Optional[str] = None, category: Optional[str] = None,
                            s: Session = Depends(db), u: User = Depends(require("finding.view"))):
        rows = PERF.list_issues(s, engagement_id, vendor_id, status, severity, source, category)
        return [PERF.issue_row(i) for i in rows]

    @app.get("/api/v2/performance-issues/summary")
    def v2_perf_issue_summary(engagement_id: str, s: Session = Depends(db),
                              u: User = Depends(require("finding.view"))):
        return PERF.issue_severity_counts(s, engagement_id)

    @app.post("/api/v2/performance-issues")
    def v2_create_perf_issue(b: PerfIssueIn, s: Session = Depends(db),
                             u: User = Depends(require("finding.manage"))):
        i = PERF.create_issue(s, engagement_id=b.engagement_id, vendor_id=b.vendor_id,
                              title=b.title, description=b.description, category=b.category,
                              severity=b.severity or "Medium", source=b.source or "Manual",
                              status=b.status or "Open", owner=b.owner, due_date=b.due_date,
                              linked_ref=b.linked_ref, suggested_remediation=b.suggested_remediation,
                              raised_by=u.username)
        audit(s, "v2.perf_issue_created", u.username,
              {"pis_id": i.pis_id, "severity": i.severity})
        s.commit()
        return PERF.issue_row(i)

    @app.put("/api/v2/performance-issues/{pis_id}")
    def v2_update_perf_issue(pis_id: str, b: PerfIssueEditIn, s: Session = Depends(db),
                             u: User = Depends(require("finding.manage"))):
        i = s.scalar(select(PERF.PerformanceIssue).where(PERF.PerformanceIssue.pis_id == pis_id))
        if not i:
            raise HTTPException(404, "issue not found")
        PERF.update_issue(s, i, actor=u.username, **b.model_dump(exclude_none=True))
        audit(s, "v2.perf_issue_updated", u.username, {"pis_id": pis_id, "status": i.status})
        s.commit()
        return PERF.issue_row(i)

    @app.post("/api/v2/performance-issues/{pis_id}/advance")
    def v2_advance_perf_issue(pis_id: str, s: Session = Depends(db),
                              u: User = Depends(require("finding.manage"))):
        i = s.scalar(select(PERF.PerformanceIssue).where(PERF.PerformanceIssue.pis_id == pis_id))
        if not i:
            raise HTTPException(404, "issue not found")
        PERF.advance_issue(s, i, u.username)
        audit(s, "v2.perf_issue_advanced", u.username, {"pis_id": pis_id, "status": i.status})
        s.commit()
        return PERF.issue_row(i)

    @app.post("/api/v2/performance-issues/{pis_id}/note")
    def v2_note_perf_issue(pis_id: str, b: NoteIn, s: Session = Depends(db),
                           u: User = Depends(require("finding.manage"))):
        i = s.scalar(select(PERF.PerformanceIssue).where(PERF.PerformanceIssue.pis_id == pis_id))
        if not i:
            raise HTTPException(404, "issue not found")
        PERF._add_note(i, u.username, b.note)
        s.commit()
        return PERF.issue_row(i)

    @app.delete("/api/v2/performance-issues/{pis_id}")
    def v2_delete_perf_issue(pis_id: str, s: Session = Depends(db),
                             u: User = Depends(require("finding.delete"))):
        i = s.scalar(select(PERF.PerformanceIssue).where(PERF.PerformanceIssue.pis_id == pis_id))
        if not i:
            raise HTTPException(404, "issue not found")
        s.delete(i)
        audit(s, "v2.perf_issue_deleted", u.username, {"pis_id": pis_id})
        s.commit()
        return {"pis_id": pis_id, "deleted": True}

    @app.post("/api/v2/performance-issues/raise-from-sla")
    def v2_raise_from_sla(b: RaiseFromSLAIn, s: Session = Depends(db),
                          u: User = Depends(require("finding.manage"))):
        sla = s.scalar(select(PERF.SLARecord).where(PERF.SLARecord.sla_id == b.sla_id))
        if not sla:
            raise HTTPException(404, "SLA not found")
        issue = PERF.raise_from_breach(s, sla, u.username)
        if not issue:
            s.commit()
            return {"raised": False, "reason": "SLA not in breach or issue already open"}
        audit(s, "v2.perf_issue_from_sla", u.username,
              {"pis_id": issue.pis_id, "sla_id": b.sla_id})
        s.commit()
        return {"raised": True, "issue": PERF.issue_row(issue)}

    # ================= PLATFORM DOCUMENTATION (SOP / TDA / versions) =================
    from app.features.platform import platform_docs as PDOCS

    @app.post("/api/v2/performance/capa")
    def v2_perf_capa(b: PerfCapaIn, s: Session = Depends(db),
                     u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        sc = MS.get_scorecard(s, b.scorecard_id)
        if not sc:
            raise HTTPException(404, "scorecard not found")
        res = MS.raise_performance_capa(s, sc["vendor_id"], b.scorecard_id,
                                        b.gap, b.owner, b.due_date)
        audit(s, "v2.perf_capa", u.username, res)
        s.commit()
        return res

    @app.post("/api/v2/performance/capa/{rid}/verify")
    def v2_perf_capa_verify(rid: str, b: CapaVerifyIn, s: Session = Depends(db),
                            u: User = Depends(require("vendor.critical"))):
        from app.features.domain import master_service as MS
        res = MS.verify_performance_capa(s, rid, u.username, b.evidence)
        if not res:
            raise HTTPException(404, "remediation not found")
        audit(s, "v2.perf_capa_verify", u.username, {"remediation_id": rid})
        s.commit()
        return res

    # ============================================================
    # REQ 5 — ProAssess (autonomous assessment)
    # ============================================================

    return r
