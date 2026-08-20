"""Performance Management service layer.

Deterministic-first, mirroring the platform's design: SLA met/breach is a pure
rule, the AI analysis summary and enquiry have deterministic implementations
that always work, and (when an LLM key is present) the gateway can enrich them.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.domain import registry_service as RS
from app.features.lifecycle.performance_models import PerformanceIssue, SLAMeasurement, SLARecord

# "Today" anchor — used for period generation and overdue calc. Uses real date.
def _today() -> date:
    return date.today()


# ----------------------------------------------------------------------------
# period helpers
# ----------------------------------------------------------------------------
def month_periods(n: int = 6, anchor: Optional[date] = None) -> List[str]:
    """Last n completed months as 'YYYY-MM', oldest first.
    Anchor's own month is treated as the latest complete month."""
    a = anchor or _today()
    y, m = a.year, a.month
    out = []
    for i in range(n - 1, -1, -1):
        yy, mm = y, m - i
        while mm < 1:
            mm += 12
            yy -= 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def quarter_periods(n: int = 4, anchor: Optional[date] = None) -> List[str]:
    """Last n quarters as 'YYYY-Qn', oldest first."""
    a = anchor or _today()
    q = (a.month - 1) // 3 + 1
    y = a.year
    seq = []
    for _ in range(n):
        seq.append(f"{y:04d}-Q{q}")
        q -= 1
        if q < 1:
            q = 4
            y -= 1
    return list(reversed(seq))


def periods_for(window: str, anchor: Optional[date] = None) -> List[str]:
    return quarter_periods(4, anchor) if window == "quarterly" else month_periods(6, anchor)


# ----------------------------------------------------------------------------
# met / breach logic (pure)
# ----------------------------------------------------------------------------
def verdict(threshold_type: str, threshold: float, value) -> Optional[bool]:
    """True = met, False = breach, None = no data."""
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v >= threshold if threshold_type == "min" else v <= threshold


def _measurements_map(s: Session, sla_id: str) -> dict:
    rows = s.scalars(select(SLAMeasurement).where(SLAMeasurement.sla_id == sla_id)).all()
    return {r.period: r.value for r in rows if r.value is not None}


def current_status(s: Session, sla: SLARecord) -> dict:
    """Latest period with data determines the SLA's current met/breach state."""
    mmap = _measurements_map(s, sla.sla_id)
    for p in reversed(periods_for(sla.window)):
        if p in mmap:
            v = mmap[p]
            ok = verdict(sla.threshold_type, sla.threshold, v)
            return {"state": "met" if ok else "breach", "period": p, "value": v}
    return {"state": "none", "period": None, "value": None}


# ----------------------------------------------------------------------------
# SLA CRUD
# ----------------------------------------------------------------------------
def create_sla(s: Session, *, engagement_id: str, vendor_id: Optional[str],
               description: str, threshold_type: str = "min", threshold: float = 0.0,
               unit: str = "", baseline: Optional[float] = None, window: str = "monthly",
               source: str = "manual", contract_id: Optional[str] = None,
               created_by: Optional[str] = None) -> SLARecord:
    sla = SLARecord(
        sla_id=RS.next_id(s, "sla"), engagement_id=engagement_id, vendor_id=vendor_id,
        contract_id=contract_id, description=description,
        threshold_type=(threshold_type if threshold_type in ("min", "max") else "min"),
        threshold=float(threshold or 0), unit=unit or "",
        baseline=(float(baseline) if baseline not in (None, "") else None),
        window=(window if window in ("monthly", "quarterly") else "monthly"),
        source=source or "manual", created_by=created_by)
    s.add(sla)
    s.flush()
    return sla


def update_sla(s: Session, sla: SLARecord, **fields) -> SLARecord:
    for k in ("description", "threshold_type", "threshold", "unit", "baseline",
              "window", "source", "active"):
        if k in fields and fields[k] is not None:
            setattr(sla, k, fields[k])
    sla.updated_at = datetime.utcnow()
    s.flush()
    return sla


def record_measurement(s: Session, sla_id: str, period: str, value,
                       recorded_by: Optional[str] = None) -> SLAMeasurement:
    row = s.scalar(select(SLAMeasurement).where(
        SLAMeasurement.sla_id == sla_id, SLAMeasurement.period == period))
    if row is None:
        row = SLAMeasurement(sla_id=sla_id, period=period)
        s.add(row)
    row.value = (float(value) if value not in (None, "") else None)
    row.recorded_by = recorded_by
    row.recorded_at = datetime.utcnow()
    s.flush()
    return row


def sla_row(s: Session, sla: SLARecord) -> dict:
    st = current_status(s, sla)
    return {
        "sla_id": sla.sla_id, "engagement_id": sla.engagement_id, "vendor_id": sla.vendor_id,
        "contract_id": sla.contract_id, "description": sla.description,
        "threshold_type": sla.threshold_type, "threshold": sla.threshold, "unit": sla.unit,
        "baseline": sla.baseline, "window": sla.window, "source": sla.source,
        "active": sla.active, "status": st["state"], "latest_period": st["period"],
        "latest_value": st["value"], "periods": periods_for(sla.window),
        "measurements": _measurements_map(s, sla.sla_id),
    }


def list_slas(s: Session, engagement_id: Optional[str] = None,
              vendor_id: Optional[str] = None) -> List[SLARecord]:
    stmt = select(SLARecord).where(SLARecord.active == True)  # noqa: E712
    if engagement_id:
        stmt = stmt.where(SLARecord.engagement_id == engagement_id)
    if vendor_id:
        stmt = stmt.where(SLARecord.vendor_id == vendor_id)
    return s.scalars(stmt.order_by(SLARecord.id.asc())).all()


# ----------------------------------------------------------------------------
# SLA extraction (deterministic template; AI gateway enriches when keyed)
# ----------------------------------------------------------------------------
_TEMPLATE_SLAS = [
    ("System availability (uptime)", "min", 99.9, "%", 99.95, "monthly"),
    ("P1 incident response time", "max", 30, "min", 15, "monthly"),
    ("Transaction success rate", "min", 99.5, "%", 99.8, "monthly"),
    ("Disaster-recovery test completed", "min", 1, "count", 1, "quarterly"),
]
_TEMPLATE_UPLOAD = [
    ("Support ticket resolution", "max", 24, "hrs", 12, "monthly"),
    ("Data processing accuracy", "min", 99.99, "%", 99.995, "quarterly"),
]


def extract_slas(s: Session, *, engagement_id: str, vendor_id: Optional[str],
                 mode: str, contract_id: Optional[str] = None,
                 created_by: Optional[str] = None) -> List[SLARecord]:
    """Extract measurable SLAs from a contract or uploaded doc.

    Deterministic baseline returns a standard service-level template; with an
    LLM key the gateway parses the actual document. Extracted SLAs are created
    with source='contract'/'upload' and remain fully editable.
    """
    template = _TEMPLATE_UPLOAD if mode == "upload" else _TEMPLATE_SLAS
    existing = {x.description for x in list_slas(s, engagement_id=engagement_id)}
    created = []
    for desc, ttype, thr, unit, base, win in template:
        if desc in existing:
            continue
        created.append(create_sla(
            s, engagement_id=engagement_id, vendor_id=vendor_id, description=desc,
            threshold_type=ttype, threshold=thr, unit=unit, baseline=base, window=win,
            source=("upload" if mode == "upload" else "contract"),
            contract_id=contract_id, created_by=created_by))
    return created


# ----------------------------------------------------------------------------
# AI analysis summary + enquiry (deterministic, data-grounded)
# ----------------------------------------------------------------------------
def _fmt(n) -> str:
    try:
        x = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(x)) if x == int(x) else f"{round(x, 3)}"


def analyse(s: Session, engagement_id: str) -> dict:
    slas = list_slas(s, engagement_id=engagement_id)
    rows = [sla_row(s, x) for x in slas]
    with_data = [r for r in rows if r["status"] != "none"]
    met = [r for r in with_data if r["status"] == "met"]
    breached = [r for r in with_data if r["status"] == "breach"]
    rate = round(len(met) / len(with_data) * 100) if with_data else 0

    # worst performer = largest relative miss
    worst = None
    worst_gap = -1.0
    for r in breached:
        thr = r["threshold"] or 0
        if not thr:
            continue
        gap = (thr - r["latest_value"]) / thr if r["threshold_type"] == "min" \
            else (r["latest_value"] - thr) / thr
        if gap > worst_gap:
            worst_gap, worst = gap, r

    # declining trend count
    declining = 0
    for r in with_data:
        ps = [p for p in r["periods"] if p in r["measurements"]]
        if len(ps) >= 2:
            a, b = r["measurements"][ps[-2]], r["measurements"][ps[-1]]
            worse = b < a if r["threshold_type"] == "min" else b > a
            if worse:
                declining += 1

    # narrative
    parts = [f"Across {len(slas)} tracked service levels, {len(met)} are meeting "
             f"target and {len(breached)} are in breach in their latest measurement window"]
    if breached:
        parts.append(f", a {rate}% compliance rate.")
        if worst:
            kind = "floor" if worst["threshold_type"] == "min" else "ceiling"
            parts.append(f" The most material breach is {worst['description']} — "
                         f"latest {_fmt(worst['latest_value'])}{worst['unit']} against a "
                         f"{kind} of {_fmt(worst['threshold'])}{worst['unit']}.")
    else:
        parts.append(" — a clean 100% compliance position this window.")
    if declining:
        parts.append(f" {declining} SLA(s) show a worsening trend versus the prior period.")
    parts.append(" Recommended action: " + (
        f"open a remediation against {worst['description']} and request a corrective-action plan."
        if breached and worst else "maintain monitoring; no escalations required this cycle."))

    return {
        "engagement_id": engagement_id, "total": len(slas), "with_data": len(with_data),
        "met": len(met), "breached": len(breached), "compliance_rate": rate,
        "declining": declining,
        "worst_performer": (worst["description"] if worst else None),
        "summary": "".join(parts),
        "ai_mode": "deterministic",
    }


def enquire(s: Session, engagement_id: str, question: str) -> dict:
    """Answer a natural-language question from the engagement's SLA data."""
    q = (question or "").lower()
    slas = list_slas(s, engagement_id=engagement_id)
    rows = [sla_row(s, x) for x in slas]
    with_data = [r for r in rows if r["status"] != "none"]
    met = [r for r in with_data if r["status"] == "met"]
    breached = [r for r in with_data if r["status"] == "breach"]

    def stat(r):
        op = "≥" if r["threshold_type"] == "min" else "≤"
        base = (f"latest {_fmt(r['latest_value'])}{r['unit']} vs {op} "
                f"{_fmt(r['threshold'])}{r['unit']} in {r['latest_period']}")
        return ("meeting target (" + base + ")") if r["status"] == "met" \
            else ("in breach (" + base + ")")

    # specific SLA name match
    named = None
    for r in rows:
        first = r["description"].lower().split()[0]
        if first in q or (("uptime" in q or "availab" in q) and "avail" in r["description"].lower()) \
           or ("incident" in q and "incident" in r["description"].lower()) \
           or ("transaction" in q and "transaction" in r["description"].lower()) \
           or ("support" in q and "support" in r["description"].lower()) \
           or ("accuracy" in q and "accuracy" in r["description"].lower()):
            named = r
            break

    if any(k in q for k in ("breach", "failing", "miss")):
        if not breached:
            ans = f"No SLAs are currently in breach — all {len(with_data)} with data are meeting target."
        else:
            ans = (f"{len(breached)} SLA(s) in breach: "
                   + "; ".join(f"{r['description']} ({stat(r)})" for r in breached) + ".")
    elif any(k in q for k in ("worst", "biggest", "priority")):
        if not breached:
            ans = "Nothing is in breach, so there is no worst performer this window."
        else:
            a = analyse(s, engagement_id)
            ans = (f"The worst performer is {a['worst_performer']}. "
                   "That is the one to open a remediation against first.")
    elif any(k in q for k in ("trend", "worsen", "declin", "improv")):
        worse = []
        for r in with_data:
            ps = [p for p in r["periods"] if p in r["measurements"]]
            if len(ps) >= 2:
                a, b = r["measurements"][ps[-2]], r["measurements"][ps[-1]]
                if (b < a if r["threshold_type"] == "min" else b > a):
                    worse.append(f"{r['description']} ({_fmt(a)}→{_fmt(b)}{r['unit']})")
        ans = ("No SLA is trending worse period-on-period." if not worse
               else f"{len(worse)} SLA(s) trending worse: " + "; ".join(worse) + ".")
    elif named and any(k in q for k in ("how", "doing", "status", "?")):
        ans = (f"{named['description']} is {stat(named)}. Baseline target is "
               f"{_fmt(named['baseline'])}{named['unit']}, measured {named['window']}.")
    elif any(k in q for k in ("summary", "board", "overall", "overview")):
        ans = analyse(s, engagement_id)["summary"]
    else:
        ans = (f"I can analyse this engagement's SLA data. {len(met)} meeting, "
               f"{len(breached)} in breach across {len(with_data)} measured SLAs. "
               "Ask about breaches, the worst performer, a specific SLA, or trends.")
    return {"question": question, "answer": ans, "ai_mode": "deterministic"}


# ----------------------------------------------------------------------------
# Performance Issues register
# ----------------------------------------------------------------------------
def _notes(issue: PerformanceIssue) -> list:
    try:
        return json.loads(issue.progress_notes or "[]")
    except Exception:
        return []


def _add_note(issue: PerformanceIssue, user: str, note: str) -> None:
    notes = _notes(issue)
    notes.append({"ts": _today().isoformat(), "user": user, "note": note})
    issue.progress_notes = json.dumps(notes)


def create_issue(s: Session, *, engagement_id: str, vendor_id: Optional[str],
                 title: str, description: Optional[str] = None, category: Optional[str] = None,
                 severity: str = "Medium", source: str = "Manual", status: str = "Open",
                 owner: Optional[str] = None, due_date: Optional[str] = None,
                 linked_ref: Optional[str] = None, sla_id: Optional[str] = None,
                 suggested_remediation: Optional[str] = None,
                 raised_by: Optional[str] = None, note: Optional[str] = None) -> PerformanceIssue:
    issue = PerformanceIssue(
        pis_id=RS.next_id(s, "perf_issue"), engagement_id=engagement_id, vendor_id=vendor_id,
        title=title, description=description, category=category,
        severity=severity if severity in ("Critical", "High", "Medium", "Low") else "Medium",
        source=source, status=status, owner=owner, raised_by=raised_by,
        raised_date=_today().isoformat(), due_date=due_date, linked_ref=linked_ref,
        sla_id=sla_id, suggested_remediation=suggested_remediation)
    _add_note(issue, raised_by or "system", note or "Issue raised.")
    s.add(issue)
    s.flush()
    return issue


def update_issue(s: Session, issue: PerformanceIssue, *, actor: str, **fields) -> PerformanceIssue:
    for k in ("title", "description", "category", "severity", "source", "status",
              "owner", "due_date", "linked_ref", "suggested_remediation",
              "risk_accepted", "acceptance_rationale"):
        if k in fields and fields[k] is not None:
            setattr(issue, k, fields[k])
    if fields.get("status") == "Closed" and not issue.closed_date:
        issue.closed_date = _today().isoformat()
    issue.updated_at = datetime.utcnow()
    _add_note(issue, actor, fields.get("_note") or "Issue updated.")
    s.flush()
    return issue


_FLOW = ["Open", "In Progress", "In Review", "Closed"]


def advance_issue(s: Session, issue: PerformanceIssue, actor: str) -> PerformanceIssue:
    idx = _FLOW.index(issue.status) if issue.status in _FLOW else 0
    issue.status = _FLOW[min(idx + 1, len(_FLOW) - 1)]
    if issue.status == "Closed":
        issue.closed_date = _today().isoformat()
    _add_note(issue, actor, f"Status moved to {issue.status}.")
    issue.updated_at = datetime.utcnow()
    s.flush()
    return issue


def raise_from_breach(s: Session, sla: SLARecord, actor: str) -> Optional[PerformanceIssue]:
    """Open a performance issue from a breached SLA (idempotent per SLA+open)."""
    existing = s.scalar(select(PerformanceIssue).where(
        PerformanceIssue.sla_id == sla.sla_id,
        PerformanceIssue.status.notin_(["Closed"])))
    if existing:
        return None
    st = current_status(s, sla)
    if st["state"] != "breach":
        return None
    op = "≥" if sla.threshold_type == "min" else "≤"
    sev = "Critical" if sla.threshold_type == "min" and sla.threshold >= 99.99 else "High"
    return create_issue(
        s, engagement_id=sla.engagement_id, vendor_id=sla.vendor_id,
        title=f"SLA breach — {sla.description}",
        description=(f"{sla.description} measured {_fmt(st['value'])}{sla.unit} in "
                     f"{st['period']} against a target of {op} {_fmt(sla.threshold)}{sla.unit}."),
        category="Service quality", severity=sev, source="SLA breach", status="Open",
        linked_ref=f"{sla.description} · {sla.engagement_id}", sla_id=sla.sla_id,
        suggested_remediation="Request a root-cause analysis and a corrective-action plan "
                              "from the vendor before the next service review.",
        raised_by="system",
        note=f"Auto-raised from SLA breach ({st['period']}, "
             f"{_fmt(st['value'])}{sla.unit} vs {op} {_fmt(sla.threshold)}{sla.unit}).")


def issue_row(issue: PerformanceIssue) -> dict:
    overdue = False
    if issue.due_date and issue.status not in ("Closed", "Risk Accepted"):
        try:
            overdue = date.fromisoformat(issue.due_date) < _today()
        except ValueError:
            overdue = False
    return {
        "pis_id": issue.pis_id, "engagement_id": issue.engagement_id, "vendor_id": issue.vendor_id,
        "title": issue.title, "description": issue.description, "category": issue.category,
        "severity": issue.severity, "source": issue.source, "status": issue.status,
        "owner": issue.owner, "raised_by": issue.raised_by, "raised_date": issue.raised_date,
        "due_date": issue.due_date, "closed_date": issue.closed_date, "overdue": overdue,
        "linked_ref": issue.linked_ref, "sla_id": issue.sla_id,
        "suggested_remediation": issue.suggested_remediation,
        "risk_accepted": issue.risk_accepted, "progress_notes": _notes(issue),
    }


_SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def list_issues(s: Session, engagement_id: Optional[str] = None,
                vendor_id: Optional[str] = None, status: Optional[str] = None,
                severity: Optional[str] = None, source: Optional[str] = None,
                category: Optional[str] = None) -> List[PerformanceIssue]:
    stmt = select(PerformanceIssue)
    if engagement_id:
        stmt = stmt.where(PerformanceIssue.engagement_id == engagement_id)
    if vendor_id:
        stmt = stmt.where(PerformanceIssue.vendor_id == vendor_id)
    if status:
        stmt = stmt.where(PerformanceIssue.status == status)
    if severity:
        stmt = stmt.where(PerformanceIssue.severity == severity)
    if source:
        stmt = stmt.where(PerformanceIssue.source == source)
    if category:
        stmt = stmt.where(PerformanceIssue.category == category)
    rows = s.scalars(stmt).all()
    return sorted(rows, key=lambda i: (_SEV_RANK.get(i.severity, 9), i.due_date or "9999"))


def issue_severity_counts(s: Session, engagement_id: str) -> dict:
    open_issues = [i for i in list_issues(s, engagement_id=engagement_id)
                   if i.status not in ("Closed", "Risk Accepted")]
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for i in open_issues:
        counts[i.severity] = counts.get(i.severity, 0) + 1
    counts["open_total"] = len(open_issues)
    return counts
