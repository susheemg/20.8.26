"""
Exit Strategy & Exit Planning (vendor level) — CMORG-aligned.

Holds one exit strategy per vendor with planned + stressed exit, triggers,
alternatives, transition steps, dependent business services, tests and a
deterministic Exit Readiness Index. Reconciles with engagement resilience
fields, contracts and monitoring signals already in BRO rather than
duplicating them. Execution hands off to the existing offboarding workflow.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import String, Integer, Boolean, Float, Text, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.features.domain.models_db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ───────────────────────── models ─────────────────────────
class VendorExitPlan(Base):
    __tablename__ = "vendor_exit_plan"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[str] = mapped_column(String, index=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    exit_mode: Mapped[str] = mapped_column(String, default="both")          # planned|stressed|both
    strategy_type: Mapped[str] = mapped_column(String, default="")          # alternative_provider|insource|multi_source|run_off|market_exit
    rationale: Mapped[str] = mapped_column(Text, default="")
    target_window: Mapped[str] = mapped_column(String, default="")
    impact_summary: Mapped[str] = mapped_column(Text, default="")
    data_plan: Mapped[str] = mapped_column(Text, default="")
    comms_plan: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String, default="")
    approver: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="draft")            # draft|approved|invoked|retired
    one_off_cost: Mapped[Optional[float]] = mapped_column(Float, default=None)
    dual_running_cost: Mapped[Optional[float]] = mapped_column(Float, default=None)
    penalty_cost: Mapped[Optional[float]] = mapped_column(Float, default=None)
    readiness_score: Mapped[int] = mapped_column(Integer, default=0)
    readiness_band: Mapped[str] = mapped_column(String, default="RED")
    last_reviewed: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    next_review: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    last_tested: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    next_test_due: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ExitAlternative(Base):
    __tablename__ = "exit_alternative"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    prequalified: Mapped[bool] = mapped_column(Boolean, default=False)
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    viability: Mapped[int] = mapped_column(Integer, default=3)               # 1..5
    note: Mapped[str] = mapped_column(String, default="")


class ExitTransitionStep(Base):
    __tablename__ = "exit_transition_step"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(String)
    owner: Mapped[str] = mapped_column(String, default="")
    duration_days: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    rto: Mapped[str] = mapped_column(String, default="")
    rpo: Mapped[str] = mapped_column(String, default="")
    dependency: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="planned")


class ExitDependency(Base):
    __tablename__ = "exit_dependency"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    service_name: Mapped[str] = mapped_column(String)
    impact_tolerance: Mapped[str] = mapped_column(String, default="")
    max_downtime: Mapped[str] = mapped_column(String, default="")
    criticality: Mapped[str] = mapped_column(String, default="Important")


class ExitTriggerEvent(Base):
    __tablename__ = "exit_trigger_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, default="")
    severity: Mapped[str] = mapped_column(String, default="medium")
    source: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[str] = mapped_column(String, default="")
    fired_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    status: Mapped[str] = mapped_column(String, default="open")              # open|closed


class ExitTest(Base):
    __tablename__ = "exit_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    test_date: Mapped[datetime] = mapped_column(DateTime, default=_now)
    method: Mapped[str] = mapped_column(String, default="tabletop")          # tabletop|walkthrough|live
    participants: Mapped[str] = mapped_column(String, default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    lessons: Mapped[str] = mapped_column(Text, default="")
    passed: Mapped[bool] = mapped_column(Boolean, default=True)


# ───────────────────────── catalogue ─────────────────────────
TRIGGER_CATALOGUE = [
    {"code": "financial_distress", "category": "Financial distress", "severity": "high", "auto": True},
    {"code": "performance", "category": "Performance", "severity": "medium", "auto": True},
    {"code": "security_breach", "category": "Security / breach", "severity": "high", "auto": True},
    {"code": "sanctions_regulatory", "category": "Regulatory / sanctions", "severity": "high", "auto": True},
    {"code": "change_of_control", "category": "Change of control / M&A", "severity": "medium", "auto": False},
    {"code": "concentration", "category": "Concentration", "severity": "high", "auto": True},
    {"code": "commercial", "category": "Commercial / strategic", "severity": "low", "auto": False},
]

STRATEGY_LABELS = {
    "alternative_provider": "Migrate to alternative provider",
    "insource": "Insource",
    "multi_source": "Multi-source",
    "run_off": "Run-off",
    "market_exit": "Market exit",
}

# test cadence (days) by criticality tier
_CADENCE = {"critical": 365, "high": 540, "standard": 730}


# ───────────────────────── deterministic readiness engine ─────────────────────────
def compute_exit_readiness(plan, alts, steps, deps, tests,
                           contract_exit_clause: bool, eng_tested: bool,
                           is_critical: bool) -> dict:
    """Pure, reproducible Exit Readiness Index (0..100) + RAG band + components."""
    comp = {}
    # strategy documented & approved (15)
    if plan.strategy_type and plan.status == "approved":
        comp["strategy"] = 15
    elif plan.strategy_type:
        comp["strategy"] = 8
    else:
        comp["strategy"] = 0
    # stressed-exit playbook present (15)
    has_stressed = plan.exit_mode in ("stressed", "both")
    if has_stressed and len(steps) >= 3:
        comp["stressed_playbook"] = 15
    elif has_stressed and len(steps) >= 1:
        comp["stressed_playbook"] = 8
    else:
        comp["stressed_playbook"] = 0
    # tested within cadence (20)
    cadence = _CADENCE["critical"] if is_critical else _CADENCE["standard"]
    passed = [t for t in tests if t.passed]
    last = max((t.test_date for t in passed), default=None)
    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = (_now() - last).days
        comp["tested"] = 20 if age <= cadence else 8
    elif eng_tested:
        comp["tested"] = 8
    else:
        comp["tested"] = 0
    # alternative provider identified & viable (15)
    viable = [a for a in alts if a.prequalified and (a.lead_time_days is not None) and a.viability >= 3]
    if viable:
        comp["alternative"] = 15
    elif alts:
        comp["alternative"] = 8
    else:
        comp["alternative"] = 0
    # data retrieval / portability defined (10)
    comp["data_plan"] = 10 if (plan.data_plan or "").strip() else 0
    # contractual enablers (10)
    comp["contractual"] = 10 if contract_exit_clause else 0
    # impact tolerance mapped (10)
    comp["impact_tolerance"] = 10 if deps else 0
    # costed (5)
    comp["costed"] = 5 if any(x is not None for x in (plan.one_off_cost, plan.dual_running_cost, plan.penalty_cost)) else 0

    score = sum(comp.values())
    band = "GREEN" if score >= 80 else "AMBER" if score >= 55 else "RED"
    # escalation override: a critical vendor with no passing test cannot be Green
    if is_critical and comp["tested"] < 20 and band == "GREEN":
        band = "AMBER"
    return {"score": score, "band": band, "components": comp,
            "test_cadence_days": cadence}


# ───────────────────────── services ─────────────────────────
def _seq(s: Session, model) -> int:
    n = s.scalar(select(model.id).order_by(model.id.desc())) or 0
    return n + 1


def get_plan(s: Session, vendor_id: str) -> Optional[VendorExitPlan]:
    return s.scalars(select(VendorExitPlan).where(VendorExitPlan.vendor_id == vendor_id)).first()


def get_or_create_plan(s: Session, vendor_id: str) -> VendorExitPlan:
    p = get_plan(s, vendor_id)
    if not p:
        p = VendorExitPlan(plan_id=f"EXP-{_seq(s, VendorExitPlan):06d}", vendor_id=vendor_id)
        s.add(p); s.flush()
    return p


def _contract_has_exit_clause(s: Session, vendor_id: str) -> bool:
    """Reconcile with the contracts module: an MSA implies the exit/assistance clause set."""
    from app.features.domain.master_ext import ContractRecord
    return bool(s.scalars(select(ContractRecord).where(
        ContractRecord.vendor_id == vendor_id, ContractRecord.contract_type == "MSA")).first())


def _engagement_tested(s: Session, vendor_id: str):
    """Roll-up of engagement-level resilience inputs already held in BRO."""
    from app.features.domain.master_ext import EngagementExt
    from app.features.domain.registry_models import EngagementRecord
    eids = [e.engagement_id for e in s.scalars(
        select(EngagementRecord).where(EngagementRecord.vendor_id == vendor_id)).all()]
    tested = False; alt = None
    if eids:
        for x in s.scalars(select(EngagementExt).where(EngagementExt.engagement_id.in_(eids))).all():
            if getattr(x, "exit_plan_tested", None):
                tested = True
            if getattr(x, "alternative_provider", None) and not alt:
                alt = x.alternative_provider
    return tested, alt


def _is_critical(s: Session, vendor_id: str) -> bool:
    from app.features.domain.registry_models import VendorRecord
    v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
    return bool(v and v.is_critical)


def recompute(s: Session, vendor_id: str) -> VendorExitPlan:
    p = get_or_create_plan(s, vendor_id)
    alts = s.scalars(select(ExitAlternative).where(ExitAlternative.vendor_id == vendor_id)).all()
    steps = s.scalars(select(ExitTransitionStep).where(ExitTransitionStep.vendor_id == vendor_id)).all()
    deps = s.scalars(select(ExitDependency).where(ExitDependency.vendor_id == vendor_id)).all()
    tests = s.scalars(select(ExitTest).where(ExitTest.vendor_id == vendor_id)).all()
    eng_tested, _ = _engagement_tested(s, vendor_id)
    r = compute_exit_readiness(p, alts, steps, deps, tests,
                               _contract_has_exit_clause(s, vendor_id), eng_tested,
                               _is_critical(s, vendor_id))
    p.readiness_score = r["score"]; p.readiness_band = r["band"]
    passed = [t.test_date for t in tests if t.passed]
    if passed:
        last = max(passed)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        p.last_tested = last
        p.next_test_due = last + timedelta(days=r["test_cadence_days"])
    p.updated_at = _now()
    return p


def upsert_plan(s: Session, vendor_id: str, data: dict) -> VendorExitPlan:
    p = get_or_create_plan(s, vendor_id)
    for k in ("exit_mode", "strategy_type", "rationale", "target_window", "impact_summary",
              "data_plan", "comms_plan", "owner", "approver", "status"):
        if k in data and data[k] is not None:
            setattr(p, k, data[k])
    for k in ("one_off_cost", "dual_running_cost", "penalty_cost"):
        if k in data and data[k] not in (None, ""):
            setattr(p, k, float(data[k]))
    return recompute(s, vendor_id)


def add_alternative(s: Session, vendor_id, name, prequalified=False, lead_time_days=None, viability=3, note=""):
    s.add(ExitAlternative(vendor_id=vendor_id, name=name, prequalified=bool(prequalified),
                          lead_time_days=lead_time_days, viability=int(viability or 3), note=note or ""))
    s.flush(); return recompute(s, vendor_id)


def add_step(s: Session, vendor_id, description, owner="", duration_days=None, rto="", rpo="", dependency="", seq=None):
    if seq is None:
        seq = (s.scalar(select(ExitTransitionStep.seq).where(ExitTransitionStep.vendor_id == vendor_id)
                        .order_by(ExitTransitionStep.seq.desc())) or 0) + 1
    s.add(ExitTransitionStep(vendor_id=vendor_id, seq=seq, description=description, owner=owner,
                             duration_days=duration_days, rto=rto, rpo=rpo, dependency=dependency))
    s.flush(); return recompute(s, vendor_id)


def add_dependency(s: Session, vendor_id, service_name, impact_tolerance="", max_downtime="", criticality="Important"):
    s.add(ExitDependency(vendor_id=vendor_id, service_name=service_name, impact_tolerance=impact_tolerance,
                         max_downtime=max_downtime, criticality=criticality))
    s.flush(); return recompute(s, vendor_id)


def remove_child(s: Session, kind: str, cid: int, vendor_id: str):
    model = {"alternative": ExitAlternative, "step": ExitTransitionStep, "dependency": ExitDependency}.get(kind)
    if not model:
        return None
    row = s.get(model, cid)
    if row:
        s.delete(row); s.flush()
    return recompute(s, vendor_id)


def log_test(s: Session, vendor_id, method="tabletop", outcome="", lessons="", participants="", passed=True, test_date=None):
    s.add(ExitTest(vendor_id=vendor_id, method=method, outcome=outcome, lessons=lessons,
                   participants=participants, passed=bool(passed), test_date=test_date or _now()))
    s.flush(); return recompute(s, vendor_id)


def attest(s: Session, vendor_id, tier_days=365):
    p = get_or_create_plan(s, vendor_id)
    p.last_reviewed = _now(); p.next_review = _now() + timedelta(days=tier_days)
    return recompute(s, vendor_id)


def invoke(s: Session, vendor_id, mode="planned"):
    """Hand execution to the existing offboarding workflow for each engagement."""
    from app.features.domain.models_feature import Offboarding
    from app.features.domain.registry_models import EngagementRecord
    try:
        from app.features.assessment.bro_engine import OFFBOARDING_STEPS
        steps = [k for (k, _desc) in OFFBOARDING_STEPS]
    except Exception:
        steps = ["notice", "knowledge", "data_return", "access", "assets", "settlement", "records", "exit"]
    p = get_or_create_plan(s, vendor_id)
    p.status = "invoked"
    engs = s.scalars(select(EngagementRecord).where(EngagementRecord.vendor_id == vendor_id)).all()
    created = 0
    for e in engs:
        eid_int = getattr(e, "id", None)
        if eid_int is None:
            continue
        for k in steps:
            s.add(Offboarding(engagement_id=eid_int, step_key=k, done=False)); created += 1
    s.flush()
    return {"status": "invoked", "mode": mode, "engagements": len(engs), "offboarding_steps": created}


def scan_triggers(s: Session) -> int:
    """Auto-raise exit triggers from monitoring / findings / screening / concentration."""
    from app.features.domain.registry_models import FinMonitorRecord, FindingRecord
    from app.features.domain.master_ext import VendorMonitorSignal, VendorScreening
    plans = s.scalars(select(VendorExitPlan)).all()
    existing = {(t.vendor_id, t.code) for t in s.scalars(
        select(ExitTriggerEvent).where(ExitTriggerEvent.status == "open")).all()}
    fired = 0

    def raise_t(vid, code, cat, sev, src, detail):
        nonlocal fired
        if (vid, code) in existing:
            return
        s.add(ExitTriggerEvent(vendor_id=vid, code=code, category=cat, severity=sev,
                               source=src, detail=detail))
        existing.add((vid, code)); fired += 1

    for p in plans:
        vid = p.vendor_id
        fm = s.scalars(select(FinMonitorRecord).where(FinMonitorRecord.vendor_id == vid)).first()
        if fm and (fm.last_result or "").lower() in ("watch", "distress", "weak"):
            raise_t(vid, "financial_distress", "Financial distress", "high",
                    "Financial monitoring", f"Monitoring result: {fm.last_result}")
        breach = s.scalars(select(FindingRecord).where(
            FindingRecord.vendor_id == vid,
            FindingRecord.severity.in_(["Critical", "High"]),
            FindingRecord.status.in_(["Open", "open", "In-Progress"]))).first()
        if breach:
            raise_t(vid, "security_breach", "Security / breach", "high",
                    "Findings", f"Open {breach.severity} finding")
        sig = s.scalars(select(VendorMonitorSignal).where(
            VendorMonitorSignal.vendor_id == vid,
            VendorMonitorSignal.signal_type == "adverse_media",
            VendorMonitorSignal.value == "flagged")).first()
        scr = s.scalars(select(VendorScreening).where(VendorScreening.vendor_id == vid)).first()
        if sig or (scr and getattr(scr, "result", "") and str(getattr(scr, "result", "")).lower() in ("hit", "match", "flagged")):
            raise_t(vid, "sanctions_regulatory", "Regulatory / sanctions", "high",
                    "Screening / reputation", "Adverse media / screening signal")
    return fired


def plan_full(s: Session, vendor_id: str) -> dict:
    from app.features.domain.registry_models import VendorRecord
    v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
    p = recompute(s, vendor_id)
    alts = s.scalars(select(ExitAlternative).where(ExitAlternative.vendor_id == vendor_id)).all()
    steps = sorted(s.scalars(select(ExitTransitionStep).where(ExitTransitionStep.vendor_id == vendor_id)).all(),
                   key=lambda x: x.seq)
    deps = s.scalars(select(ExitDependency).where(ExitDependency.vendor_id == vendor_id)).all()
    tests = sorted(s.scalars(select(ExitTest).where(ExitTest.vendor_id == vendor_id)).all(),
                   key=lambda x: x.test_date, reverse=True)
    trigs = s.scalars(select(ExitTriggerEvent).where(
        ExitTriggerEvent.vendor_id == vendor_id, ExitTriggerEvent.status == "open")).all()
    alts2, _ = (lambda t: t)(_engagement_tested(s, vendor_id)), None
    eng_tested, eng_alt = _engagement_tested(s, vendor_id)

    def iso(d):
        return d.isoformat() if d else None
    # recompute components for display
    r = compute_exit_readiness(p, alts, steps, deps, tests,
                               _contract_has_exit_clause(s, vendor_id), eng_tested, _is_critical(s, vendor_id))
    return {
        "vendor_id": vendor_id, "vendor_name": v.legal_name if v else vendor_id,
        "is_critical": bool(v and v.is_critical), "tier": v.tier if v else None,
        "plan": {
            "plan_id": p.plan_id, "exit_mode": p.exit_mode, "strategy_type": p.strategy_type,
            "strategy_label": STRATEGY_LABELS.get(p.strategy_type, p.strategy_type or ""),
            "rationale": p.rationale, "target_window": p.target_window, "impact_summary": p.impact_summary,
            "data_plan": p.data_plan, "comms_plan": p.comms_plan, "owner": p.owner, "approver": p.approver,
            "status": p.status, "one_off_cost": p.one_off_cost, "dual_running_cost": p.dual_running_cost,
            "penalty_cost": p.penalty_cost, "last_reviewed": iso(p.last_reviewed), "next_review": iso(p.next_review),
            "last_tested": iso(p.last_tested), "next_test_due": iso(p.next_test_due),
        },
        "readiness": r,
        "rollup": {"engagement_exit_tested": eng_tested, "engagement_alternative": eng_alt,
                   "contract_exit_clause": _contract_has_exit_clause(s, vendor_id)},
        "alternatives": [{"id": a.id, "name": a.name, "prequalified": a.prequalified,
                          "lead_time_days": a.lead_time_days, "viability": a.viability, "note": a.note} for a in alts],
        "steps": [{"id": x.id, "seq": x.seq, "description": x.description, "owner": x.owner,
                   "duration_days": x.duration_days, "rto": x.rto, "rpo": x.rpo, "dependency": x.dependency,
                   "status": x.status} for x in steps],
        "dependencies": [{"id": d.id, "service_name": d.service_name, "impact_tolerance": d.impact_tolerance,
                          "max_downtime": d.max_downtime, "criticality": d.criticality} for d in deps],
        "tests": [{"id": t.id, "test_date": iso(t.test_date), "method": t.method, "passed": t.passed,
                   "outcome": t.outcome, "lessons": t.lessons, "participants": t.participants} for t in tests],
        "triggers": [{"id": t.id, "code": t.code, "category": t.category, "severity": t.severity,
                      "source": t.source, "detail": t.detail, "fired_at": iso(t.fired_at)} for t in trigs],
    }


def portfolio(s: Session) -> dict:
    from app.features.domain.registry_models import VendorRecord
    plans = s.scalars(select(VendorExitPlan)).all()
    by_vendor = {p.vendor_id: p for p in plans}
    rows = []
    crit = [v for v in s.scalars(select(VendorRecord)).all() if v.is_critical]
    open_trig = {}
    for t in s.scalars(select(ExitTriggerEvent).where(ExitTriggerEvent.status == "open")).all():
        open_trig[t.vendor_id] = open_trig.get(t.vendor_id, 0) + 1
    for p in plans:
        recompute(s, p.vendor_id)
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == p.vendor_id)).first()
        rows.append({"vendor_id": p.vendor_id, "vendor_name": v.legal_name if v else p.vendor_id,
                     "is_critical": bool(v and v.is_critical), "band": p.readiness_band,
                     "score": p.readiness_score, "status": p.status,
                     "tested": bool(p.last_tested), "open_triggers": open_trig.get(p.vendor_id, 0)})
    rows.sort(key=lambda r: (not r["is_critical"], {"RED": 0, "AMBER": 1, "GREEN": 2}.get(r["band"], 3), r["score"]))
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for r in rows:
        counts[r["band"]] = counts.get(r["band"], 0) + 1
    missing = [{"vendor_id": v.vendor_id, "vendor_name": v.legal_name}
               for v in crit if v.vendor_id not in by_vendor]
    untested = [r for r in rows if r["is_critical"] and not r["tested"]]
    triggered = [r for r in rows if r["open_triggers"] > 0]
    return {"counts": counts, "total_plans": len(rows), "critical_total": len(crit),
            "rows": rows, "gaps": {"missing_critical": missing, "untested_critical": untested,
                                   "triggered": triggered}}


def seed_demo_plans(s: Session, vendors) -> int:
    """Create reconciled exit plans for criticals + a sample of others."""
    import random
    n = 0
    for v in vendors:
        if not (v.is_critical or random.random() < 0.30):
            continue
        p = get_or_create_plan(s, v.vendor_id)
        crit = v.is_critical
        p.exit_mode = "both"
        p.strategy_type = random.choice(["alternative_provider", "multi_source"] if crit
                                        else ["alternative_provider", "insource", "multi_source"])
        p.rationale = ("Sole-source systemic dependency — alternative capacity and a tested stressed-exit playbook required."
                       if crit else "Substitutable service; orderly migration to an alternative provider.")
        p.target_window = random.choice(["3 months", "6 months", "9 months", "12 months"])
        p.impact_summary = ("Loss would breach the impact tolerance of one or more important business services."
                            if crit else "Moderate impact; within tolerance with a planned migration.")
        p.data_plan = "Retrieve all firm data via documented export (CSV/API), certified deletion within 30 days; escrow for code where applicable."
        p.comms_plan = "Notify internal stakeholders, affected customers, the regulator (if material) and the supplier on invocation."
        p.owner = random.choice(["VRM Owner 1", "VRM Owner 2", "Resilience Owner 1"])
        p.approver = "Executive Approver 1 (COO)"
        p.status = random.choice(["approved", "approved", "draft"]) if crit else random.choice(["approved", "draft", "draft"])
        p.one_off_cost = random.choice([150000, 400000, 900000])
        p.dual_running_cost = random.choice([50000, 120000, 300000])
        p.penalty_cost = random.choice([0, 25000, 80000])
        # alternatives
        add_alternative(s, v.vendor_id, random.choice(["Alternate Cloud Region", "Secondary Provider Ltd", "In-house Platform", "Multi-vendor Pool"]),
                        prequalified=crit or random.random() < 0.5,
                        lead_time_days=random.choice([30, 60, 90, 180]), viability=random.randint(3, 5),
                        note="Pre-qualified" if crit else "Identified")
        if crit and random.random() < 0.6:
            add_alternative(s, v.vendor_id, "Tertiary fallback", prequalified=False,
                            lead_time_days=random.choice([90, 180]), viability=random.randint(2, 4))
        # transition steps
        for i, desc in enumerate(["Trigger exit & stand up programme", "Provision alternative & migrate data",
                                  "Parallel-run & validate", "Cutover & decommission", "Certify data deletion"], start=1):
            add_step(s, v.vendor_id, desc, owner=p.owner, duration_days=random.choice([10, 20, 30, 45]),
                     rto=random.choice(["4h", "24h", "72h"]), rpo=random.choice(["1h", "4h", "24h"]), seq=i)
        # dependencies (important business services)
        for svc in random.sample(["Payments", "Customer onboarding", "Trade settlement", "Payroll",
                                   "Market data", "Client reporting", "Card processing"], k=random.randint(1, 3)):
            add_dependency(s, v.vendor_id, svc,
                           impact_tolerance=random.choice(["2 hours", "4 hours", "1 business day"]),
                           max_downtime=random.choice(["2h", "4h", "24h"]),
                           criticality="Critical" if crit else "Important")
        # tests: most criticals tested (some stale), some untested to populate gaps
        roll = random.random()
        if crit:
            if roll < 0.6:
                log_test(s, v.vendor_id, method=random.choice(["tabletop", "live"]),
                         outcome="Exit exercised within tolerance.", lessons="Tighten data-export runbook.",
                         test_date=_now() - timedelta(days=random.randint(30, 300)))
            elif roll < 0.8:
                log_test(s, v.vendor_id, method="tabletop", outcome="Stale test.", passed=True,
                         test_date=_now() - timedelta(days=random.randint(500, 800)))
            # else: untested -> appears in gap list
        elif roll < 0.4:
            log_test(s, v.vendor_id, method="tabletop", outcome="Walkthrough completed.",
                     test_date=_now() - timedelta(days=random.randint(60, 400)))
        attest(s, v.vendor_id, tier_days=365 if crit else 730)
        recompute(s, v.vendor_id)
        n += 1
    return n


# ---------------------------------------------------------------------------
# AI exit-plan draft (Viny). Org-data-grounded deterministic draft; the API
# layer optionally enriches with a live model + public web data.
# ---------------------------------------------------------------------------
def draft_context(s: Session, vendor_id: str) -> dict:
    """Collect the organisation data Viny drafts from."""
    from app.features.domain.registry_models import VendorRecord, EngagementRecord
    v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
    name = v.legal_name if v else vendor_id
    engs = s.scalars(select(EngagementRecord).where(
        EngagementRecord.vendor_id == vendor_id)).all() if v else []
    bands = [e.residual_band for e in engs if getattr(e, "residual_band", None)]
    order = {"HIGH": 4, "ELEVATED": 3, "MODERATE": 2, "LOW": 1}
    residual = max(bands, key=lambda b: order.get(b, 0)) if bands else "MODERATE"
    deps = s.scalars(select(ExitDependency).where(
        ExitDependency.vendor_id == vendor_id)).all()
    alts = s.scalars(select(ExitAlternative).where(
        ExitAlternative.vendor_id == vendor_id)).all()
    return {
        "vendor_id": vendor_id, "vendor_name": name,
        "is_critical": bool(getattr(v, "is_critical", False)),
        "tier": getattr(v, "tier", None), "hq_country": getattr(v, "hq_country", None),
        "services": [e.title for e in engs][:8],
        "engagement_count": len(engs), "residual_band": residual,
        "dependencies": [{"service": d.service_name, "tolerance": d.impact_tolerance,
                          "max_downtime": d.max_downtime, "criticality": d.criticality}
                         for d in deps],
        "existing_alternatives": [a.name for a in alts],
        "contract_exit_clause": _contract_has_exit_clause(s, vendor_id),
    }


def deterministic_draft(ctx: dict) -> dict:
    """A grounded exit-plan draft built purely from organisation data (no AI)."""
    name = ctx["vendor_name"]
    crit = ctx["is_critical"]
    svc = ", ".join(ctx["services"]) or "the contracted service"
    deps = ctx["dependencies"]
    has_alt = bool(ctx["existing_alternatives"])
    strategy = "alternative_provider" if has_alt else ("multi_source" if crit else "alternative_provider")
    window = ("6 months planned · 4–6 weeks stressed" if crit else "3 months planned")
    rationale = (
        f"{name} is a {'critical ' if crit else ''}third party providing {svc} "
        f"(residual exposure: {ctx['residual_band']}). This plan establishes a documented, "
        f"testable route to exit — both planned and stressed — to avoid lock-in, preserve "
        f"service continuity for dependent business services, and satisfy regulatory "
        f"stressed-exit expectations." +
        ("" if ctx["contract_exit_clause"] else
         " NOTE: no contractual exit/assistance clause is currently evidenced — confirm "
         "termination-for-convenience, transition-assistance and data-return obligations."))
    if deps:
        dep_txt = "; ".join(f"{d['service']} (tolerance {d['tolerance'] or '—'}, "
                            f"max downtime {d['max_downtime'] or '—'})" for d in deps[:6])
        impact = (f"Dependent business services: {dep_txt}. Sequencing must keep each within "
                  f"its impact tolerance; the stressed path prioritises the most time-critical "
                  f"service first.")
    else:
        impact = ("No dependent business services are mapped yet — map them and set impact "
                  "tolerances before approval, as sequencing and RTO/RPO depend on them.")
    data_plan = (
        "On exit: (1) inventory all data held by the supplier and its sub-processors; "
        "(2) extract in a portable, documented format with integrity validation; "
        "(3) obtain written certification of secure destruction (incl. backups) within an "
        "agreed window; (4) revoke all access and federated identities; (5) retain only what "
        "regulation requires, under the firm's control.")
    comms = (
        "Stakeholders: internal service/relationship owner and SteerCo; the supplier "
        "(formal notice per contract); impacted business units and, where relevant, customers; "
        + ("the lead regulator (notification expected for a critical/important outsourcing "
           "exit); " if crit else "") +
        "and second/third lines. Define holding statements and an escalation tree for the "
        "stressed scenario.")
    steps = [
        {"seq": 1, "description": "Invoke exit governance; confirm trigger, notify SteerCo and issue contractual notice.",
         "owner": "Exit owner / SteerCo", "duration_days": 5, "rto": "—", "rpo": "—"},
        {"seq": 2, "description": ("Confirm/stand up the target: " + (
            "transition to the pre-qualified alternative provider." if has_alt else
            "identify and pre-qualify ≥2 alternative providers (or insource design).")),
         "owner": "Sourcing", "duration_days": 20, "rto": "—", "rpo": "—"},
        {"seq": 3, "description": "Extract and validate all data; agree formats and reconciliation checks.",
         "owner": "Data / Engineering", "duration_days": 15, "rto": "4h", "rpo": "1h"},
        {"seq": 4, "description": "Parallel-run new and incumbent; verify against impact tolerances.",
         "owner": "Service owner", "duration_days": 20, "rto": "4h", "rpo": "1h"},
        {"seq": 5, "description": "Cutover to the new arrangement; monitor stability and rollback readiness.",
         "owner": "Service owner", "duration_days": 5, "rto": "2h", "rpo": "30m"},
        {"seq": 6, "description": "Decommission incumbent access; obtain certified data destruction; close out.",
         "owner": "Security / Vendor mgmt", "duration_days": 10, "rto": "—", "rpo": "—"},
    ]
    alternatives = []
    if not has_alt:
        alternatives = [
            {"name": "Pre-qualified alternative provider (to identify)", "prequalified": False,
             "lead_time_days": 60, "viability": 3,
             "note": "Run a short market scan; shortlist ≥2 viable providers with portability support."},
        ]
    return {"strategy_type": strategy, "target_window": window, "rationale": rationale,
            "impact_summary": impact, "data_plan": data_plan, "comms_plan": comms,
            "steps": steps, "alternatives": alternatives}
