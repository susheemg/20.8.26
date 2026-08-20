"""
Unified monitoring engine.

Runs the recurring risk sweeps that previously had to be triggered by hand, on a
schedule (Render Cron or an in-process scheduler) or on demand:

  * sanctions_rescreen     — re-screen every vendor against the watchlist (+live feeds),
                             apply outcomes (auto-Issue / criticality escalation / auto-close)
  * certificate_revalidation — refresh artefact statuses, raise/clear expiry Issues
  * evidence_expiring      — count evidence (documents + certs) expiring within 90 days
  * reassessment_due       — count engagements whose reassessment date has passed

Each run is logged to monitoring_runs for audit and "last run / next due" reporting.
Tasks are isolated: one failing task does not abort the others.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.domain import registry_service as RS
from app.features.intelligence import sanctions as SANC
from app.features.domain.registry_models import (
    VendorRecord, SanctionsScreening, WatchlistEntry, MonitoringRun, EngagementRecord,
)
from app.features.domain.models_feature import Certification, Document


def live_entries(s: Session) -> list:
    out = []
    for w in s.scalars(select(WatchlistEntry)).all():
        out.append({"id": w.ext_id, "name": w.name, "aliases": json.loads(w.aliases or "[]"),
                    "category": w.category, "source": w.source, "list": w.list_name,
                    "program": w.program, "country": w.country, "nationality": w.nationality,
                    "entity_type": w.entity_type, "dob": w.dob, "live": True})
    return out


def _task_sanctions_rescreen(s, by, audit_fn):
    extra = live_entries(s)
    screened = hits = reviews = cleared = logged = 0
    for v in s.scalars(select(VendorRecord)).all():
        r = SANC.screen_name(v.legal_name, v.hq_country, extra=extra)
        band = r["band"]; screened += 1
        hits += band == "Hit"; reviews += band == "Review"; cleared += band == "Clear"
        top = r["hits"][0]["matched_name"] if r["hits"] else ""
        RS.apply_screening_outcome(s, v.vendor_id, v.legal_name, band,
                                   f"{band} — {v.legal_name} vs {top}".strip(" —"),
                                   by, audit_fn=audit_fn)
        if band != "Clear":
            sid = RS.next_id(s, "screening")
            s.add(SanctionsScreening(
                screening_id=sid, vendor_id=v.vendor_id, screened_name=v.legal_name,
                country=v.hq_country, band=band, hit_count=r["hit_count"],
                hits=json.dumps(r["hits"]), sources_used=json.dumps(r["sources_screened"]),
                screened_by=by))
            logged += 1
    return {"screened": screened, "hits": hits, "reviews": reviews, "clear": cleared,
            "screenings_logged": logged, "live_entries": len(extra)}


def _task_certificate_revalidation(s, by, audit_fn):
    out = RS.revalidation_run(s)
    return {"expiry_notices_7d": len(out.get("notify_7day", [])),
            "new_issues": len(out.get("new_issues", []))}


def _task_evidence_expiring(s, by, audit_fn):
    horizon = datetime.utcnow() + timedelta(days=90)
    docs = s.scalars(select(Document).where(
        Document.next_validation != None,  # noqa: E711
        Document.next_validation <= horizon)).all()
    certs = s.scalars(select(Certification).where(
        Certification.valid_until != None,  # noqa: E711
        Certification.valid_until <= horizon,
        Certification.superseded == False)).all()  # noqa: E712
    return {"expiring_90d": len(docs) + len(certs)}


def _task_reassessment_due(s, by, audit_fn):
    today = date.today().isoformat()
    due = s.scalars(select(EngagementRecord).where(
        EngagementRecord.next_assessment_due != None,  # noqa: E711
        EngagementRecord.next_assessment_due <= today)).all()
    return {"reassessments_due": len(due)}


def _task_band_reconciliation(s: Session, by: str, audit_fn=None) -> dict:
    """DB-08: detect divergence between the copies of the same risk fact.

    Inherent and residual bands are stored on the engagement, on the assessment
    snapshot and on the consolidated vendor profile. The denormalisation is
    deliberate — the snapshot is a point-in-time fact and the profile is a
    materialised aggregate — but nothing previously checked that the live copies
    agree. A failure mid-chain, a manual correction, or a future writer could leave
    them disagreeing silently. This compares the engagement against its latest
    assessment and reports divergence rather than guessing which side is right.
    """
    from app.features.domain.registry_models import EngagementRecord, AssessmentRecord
    diverged, checked = [], 0
    engs = s.scalars(select(EngagementRecord)).all()
    for e in engs:
        latest = s.scalars(
            select(AssessmentRecord)
            .where(AssessmentRecord.engagement_id == e.engagement_id)
            .order_by(AssessmentRecord.id.desc())).first()
        if not latest:
            continue
        checked += 1
        for field in ("inherent_band", "residual_band"):
            ev, av = getattr(e, field, None), getattr(latest, field, None)
            if ev and av and str(ev).upper() != str(av).upper():
                diverged.append({"engagement_id": e.engagement_id,
                                 "assessment_id": latest.assessment_id,
                                 "field": field, "engagement": ev, "assessment": av})
    if diverged and audit_fn:
        audit_fn(s, "monitoring.band_divergence", by,
                 {"count": len(diverged), "sample": diverged[:10]})
    return {"checked": checked, "diverged": len(diverged), "items": diverged[:25]}


TASKS = [
    ("sanctions_rescreen", _task_sanctions_rescreen),
    ("certificate_revalidation", _task_certificate_revalidation),
    ("evidence_expiring", _task_evidence_expiring),
    ("reassessment_due", _task_reassessment_due),
    ("band_reconciliation", _task_band_reconciliation),
]


def run_all(s: Session, by: str = "manual", trigger: str = "manual", audit_fn=None,
            only: list | None = None) -> dict:
    rid = RS.next_id(s, "monitoring")
    started = datetime.now(timezone.utc)
    run = MonitoringRun(run_id=rid, trigger=trigger, started_at=started)
    s.add(run); s.flush()
    tasks: dict = {}
    ok = True
    for name, fn in TASKS:
        if only and name not in only:
            continue
        try:
            tasks[name] = fn(s, by, audit_fn)
        except Exception as e:  # isolate task failures
            tasks[name] = {"error": str(e)}
            ok = False
    run.finished_at = datetime.now(timezone.utc)
    run.ok = ok
    run.tasks = json.dumps(tasks)
    if audit_fn:
        audit_fn(s, "monitoring.run", by, {"run_id": rid, "trigger": trigger, "ok": ok})
    s.commit()
    return {"run_id": rid, "trigger": trigger, "ok": ok, "tasks": tasks,
            "started_at": started.isoformat(), "finished_at": run.finished_at.isoformat()}


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if (dt and dt.tzinfo is None) else dt


def claim_due_run(s: Session, interval_hours: float) -> bool:
    """Lightweight scheduler guard: only run if the last run is older than the interval.
    Reduces (does not fully eliminate) duplicate runs across workers."""
    last = s.scalars(select(MonitoringRun).order_by(MonitoringRun.id.desc())).first()
    la = _aware(last.started_at) if last else None
    if la and datetime.now(timezone.utc) - la < timedelta(hours=interval_hours):
        return False
    return True


def status(s: Session, interval_hours: float = 24) -> dict:
    last = s.scalars(select(MonitoringRun).order_by(MonitoringRun.id.desc())).first()
    if not last:
        return {"last_run": None, "next_due": "now", "interval_hours": interval_hours,
                "tasks": {}, "ok": None, "trigger": None}
    la = _aware(last.started_at)
    return {"last_run": la.isoformat() if la else None, "trigger": last.trigger,
            "ok": last.ok, "interval_hours": interval_hours,
            "next_due": (la + timedelta(hours=interval_hours)).isoformat() if la else "now",
            "tasks": json.loads(last.tasks or "{}")}
