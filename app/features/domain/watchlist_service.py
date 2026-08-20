"""Watchlist module service layer.

Watchlist entries flag suppliers; criteria drive a database sweep that proposes
candidates for controller approval; supplier notes are internal-only annotations.

Seed criteria are derived from the AOC due-diligence configuration (GI 3000.005
Appendix B single-issue triggers & factors, and GI 3000.017 trade-compliance).
Where a criterion maps to data the platform actually holds it carries a machine
rule (country / keyword / flag) so the sweep can evaluate it; the rest are
`manual` and are added by hand — the sweep never pretends to evaluate them.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .registry_models import (
    WatchlistCriterion, SupplierWatchlistEntry, WatchlistCandidate, SupplierNote,
    VendorRecord, EngagementRecord, FindingRecord, ArtefactRecord)
from .registry_service import next_id

RESTRICTED_COUNTRIES = ["Cuba", "Iran", "Syria", "North Korea", "Crimea", "Russia"]

# (name, category, description, rule_type, rule_value, severity, weight, source_ref)
SEED_CRITERIA = [
    ("Restricted country / sanctions exposure", "Trade Compliance",
     "Third party is directly or indirectly involved with a Restricted Country or Restricted Person "
     "(current: Cuba, Iran, Syria, North Korea, Crimea) or involves Russia / Russian parties.",
     "country", ",".join(RESTRICTED_COUNTRIES), "High", 100, "GI 3000.017 §1.2"),
    ("Adverse media — bribery / fraud / money laundering", "Single-Issue Trigger",
     "Subject of media reports or allegations related to paying bribes or other illegal / improper conduct.",
     "keyword", "bribery,fraud,money laundering,corruption,sanction,adverse media,investigation",
     "High", 100, "GI 3000.005 App. B §1.a.viii"),
    ("Under investigation by a government authority", "Single-Issue Trigger",
     "Known to be, or to have been, the subject of an investigation relating to bribery, money "
     "laundering, fraud or other unethical conduct.",
     "keyword", "investigation,enforcement,indictment,charged,prosecution",
     "High", 100, "GI 3000.005 App. B §1.a.vii"),
    ("Government-owned / government entity", "Factor for Consideration",
     "Third party is a government entity or is owned in whole or part by a government official.",
     "flag", "government_owned", "Elevated", 25, "GI 3000.005 App. B §2.d.i"),
    ("Unusual corporate structure (shell / holding)", "Factor for Consideration",
     "Unexplained holding or shell company structure that obscures ownership.",
     "keyword", "shell company,holding company,unexplained ownership,offshore",
     "Elevated", 25, "GI 3000.005 App. B §2.d.viii"),
    ("Critical supplier under stress", "Internal Trigger",
     "Critical supplier carrying elevated risk signals (concentration, expired evidence, open high findings) "
     "warranting heightened watch.",
     "flag", "critical_stress", "Elevated", 50, "AOC internal dependency"),
    ("Requests payment in cash (atypical)", "Single-Issue Trigger",
     "Requests payment in cash under circumstances in which that is not a typical course of dealing. "
     "RED flag for Procurement/Finance to raise to SRM.",
     "manual", None, "High", 100, "GI 3000.005 App. B §1.a.i"),
    ("Requests unusual financial arrangements", "Factor for Consideration",
     "Requests payment to another company or to a bank account opened in a country other than where the "
     "third party operates.",
     "manual", None, "High", 25, "GI 3000.005 App. B §2.d.vii"),
    ("Discontinued by other companies for improper conduct", "Factor for Consideration",
     "Has been discontinued as a representative or business partner by other companies for improper conduct.",
     "keyword", "debarred,blacklisted,terminated for cause,discontinued",
     "Elevated", 25, "GI 3000.005 App. B §2.d.xiii"),
]


# ---------------------------------------------------------------- criteria
def seed_criteria(s: Session) -> int:
    """Idempotent — seeds the AOC-derived criteria if none exist."""
    if s.scalar(select(func.count()).select_from(WatchlistCriterion)):
        return 0
    n = 0
    for name, cat, desc, rt, rv, sev, wt, ref in SEED_CRITERIA:
        s.add(WatchlistCriterion(
            criterion_id=next_id(s, "watchlist_criterion"), name=name, category=cat,
            description=desc, rule_type=rt, rule_value=rv, severity=sev, weight=wt,
            source_ref=ref, created_by="system"))
        n += 1
    s.commit()
    return n


def list_criteria(s: Session) -> list[dict]:
    rows = s.scalars(select(WatchlistCriterion).order_by(WatchlistCriterion.category,
                                                         WatchlistCriterion.criterion_id)).all()
    return [_crit_dict(c) for c in rows]


def _crit_dict(c: WatchlistCriterion) -> dict:
    return {"criterion_id": c.criterion_id, "name": c.name, "category": c.category,
            "description": c.description, "rule_type": c.rule_type, "rule_value": c.rule_value,
            "severity": c.severity, "weight": c.weight, "enabled": c.enabled,
            "source_ref": c.source_ref, "created_by": c.created_by}


def add_criterion(s: Session, b: dict, actor: str) -> dict:
    c = WatchlistCriterion(
        criterion_id=next_id(s, "watchlist_criterion"),
        name=b["name"], category=b.get("category", "Manual"),
        description=b.get("description"), rule_type=b.get("rule_type", "manual"),
        rule_value=b.get("rule_value"), severity=b.get("severity", "High"),
        weight=int(b.get("weight", 100)), source_ref=b.get("source_ref"), created_by=actor)
    s.add(c); s.commit()
    return _crit_dict(c)


def update_criterion(s: Session, cid: str, b: dict) -> dict:
    c = s.scalars(select(WatchlistCriterion).where(WatchlistCriterion.criterion_id == cid)).first()
    if not c:
        raise ValueError("criterion not found")
    for k in ("name", "category", "description", "rule_type", "rule_value", "severity", "source_ref"):
        if k in b and b[k] is not None:
            setattr(c, k, b[k])
    if "weight" in b and b["weight"] is not None:
        c.weight = int(b["weight"])
    if "enabled" in b and b["enabled"] is not None:
        c.enabled = bool(b["enabled"])
    c.updated_at = datetime.now(timezone.utc)
    s.commit()
    return _crit_dict(c)


def delete_criterion(s: Session, cid: str) -> None:
    c = s.scalars(select(WatchlistCriterion).where(WatchlistCriterion.criterion_id == cid)).first()
    if c:
        s.delete(c); s.commit()


# ---------------------------------------------------------------- entries
def _entry_dict(e: SupplierWatchlistEntry, vendor_name: Optional[str] = None) -> dict:
    return {"entry_id": e.entry_id, "vendor_id": e.vendor_id, "vendor_name": vendor_name,
            "criterion_id": e.criterion_id, "reason": e.reason, "severity": e.severity,
            "since_date": e.since_date, "next_review_date": e.next_review_date,
            "status": e.status, "source": e.source, "added_by": e.added_by,
            "cleared_by": e.cleared_by, "cleared_at": e.cleared_at}


def list_entries(s: Session, status: str = "Active") -> list[dict]:
    q = select(SupplierWatchlistEntry)
    if status and status != "all":
        q = q.where(SupplierWatchlistEntry.status == status)
    q = q.order_by(SupplierWatchlistEntry.created_at.desc())
    rows = s.scalars(q).all()
    names = {v.vendor_id: v.legal_name for v in s.scalars(select(VendorRecord)).all()}
    return [_entry_dict(e, names.get(e.vendor_id)) for e in rows]


def entries_for_vendor(s: Session, vendor_id: str, status: str = "Active") -> list[dict]:
    q = select(SupplierWatchlistEntry).where(SupplierWatchlistEntry.vendor_id == vendor_id)
    if status and status != "all":
        q = q.where(SupplierWatchlistEntry.status == status)
    return [_entry_dict(e) for e in s.scalars(q.order_by(SupplierWatchlistEntry.created_at.desc())).all()]


def is_watchlisted(s: Session, vendor_id: str) -> bool:
    return bool(s.scalar(select(func.count()).select_from(SupplierWatchlistEntry).where(
        SupplierWatchlistEntry.vendor_id == vendor_id, SupplierWatchlistEntry.status == "Active")))


def watchlisted_vendor_ids(s: Session) -> set[str]:
    return set(s.scalars(select(SupplierWatchlistEntry.vendor_id).where(
        SupplierWatchlistEntry.status == "Active")).all())


def add_entry(s: Session, b: dict, actor: str, source: str = "manual") -> dict:
    since = b.get("since_date") or date.today().isoformat()
    nxt = b.get("next_review_date")
    if not nxt:
        nxt = (date.today() + timedelta(days=90)).isoformat()
    e = SupplierWatchlistEntry(
        entry_id=next_id(s, "watchlist_entry"), vendor_id=b["vendor_id"],
        criterion_id=b.get("criterion_id"), reason=b["reason"],
        severity=b.get("severity", "High"), since_date=since, next_review_date=nxt,
        status="Active", source=source, added_by=actor)
    s.add(e); s.commit()
    return _entry_dict(e)


def update_entry(s: Session, eid: str, b: dict, actor: str) -> dict:
    e = s.scalars(select(SupplierWatchlistEntry).where(SupplierWatchlistEntry.entry_id == eid)).first()
    if not e:
        raise ValueError("entry not found")
    for k in ("reason", "severity", "since_date", "next_review_date"):
        if k in b and b[k] is not None:
            setattr(e, k, b[k])
    if b.get("status") == "Cleared" and e.status != "Cleared":
        e.status = "Cleared"; e.cleared_by = actor
        e.cleared_at = datetime.now(timezone.utc).isoformat()
    elif b.get("status") == "Active":
        e.status = "Active"; e.cleared_by = None; e.cleared_at = None
    s.commit()
    return _entry_dict(e)


def delete_entry(s: Session, eid: str) -> None:
    e = s.scalars(select(SupplierWatchlistEntry).where(SupplierWatchlistEntry.entry_id == eid)).first()
    if e:
        s.delete(e); s.commit()


# ---------------------------------------------------------------- sweep
def _vendor_countries(v: VendorRecord) -> str:
    return " ".join(str(x or "") for x in
                    (v.incorporation_country, v.hq_country, v.operating_countries)).lower()


def _vendor_text(s: Session, vendor_id: str) -> str:
    """Adverse-media-ish text corpus: finding titles/descriptions for the vendor."""
    parts = []
    for f in s.scalars(select(FindingRecord).where(FindingRecord.vendor_id == vendor_id)).all():
        parts.append(str(f.title or "")); parts.append(str(f.description or ""))
    return " ".join(parts).lower()


def _eval_flag(s: Session, v: VendorRecord, flag: str) -> Optional[str]:
    if flag == "government_owned":
        blob = " ".join(str(x or "") for x in (v.legal_name, v.ultimate_parent, v.legal_form)).lower()
        if any(w in blob for w in ("government", "ministry", "state-owned", "public authority")):
            return "Ownership/name indicates a government / state entity"
        return None
    if flag == "critical_stress":
        if not v.is_critical:
            return None
        expired = s.scalar(select(func.count()).select_from(ArtefactRecord).where(
            ArtefactRecord.vendor_id == v.vendor_id, ArtefactRecord.status == "Expired"))
        highf = s.scalar(select(func.count()).select_from(FindingRecord).where(
            FindingRecord.vendor_id == v.vendor_id, FindingRecord.severity.in_(["High", "Critical"]),
            FindingRecord.status != "Closed"))
        drivers = []
        if expired: drivers.append(f"{expired} expired certificate(s)")
        if highf: drivers.append(f"{highf} open high/critical finding(s)")
        if drivers:
            return "Critical supplier with " + " and ".join(drivers)
        return None
    return None


def run_sweep(s: Session, actor: str) -> dict:
    """Evaluate enabled, machine-evaluable criteria across the vendor estate and
    create pending candidates (deduped against existing active entries + pending
    candidates). Manual criteria are skipped. Returns a summary."""
    crits = s.scalars(select(WatchlistCriterion).where(
        WatchlistCriterion.enabled == True,  # noqa: E712
        WatchlistCriterion.rule_type != "manual")).all()
    vendors = s.scalars(select(VendorRecord)).all()
    already_active = {(e.vendor_id, e.criterion_id) for e in s.scalars(
        select(SupplierWatchlistEntry).where(SupplierWatchlistEntry.status == "Active")).all()}
    already_pending = {(c.vendor_id, c.criterion_id) for c in s.scalars(
        select(WatchlistCandidate).where(WatchlistCandidate.status == "pending")).all()}
    created = 0
    by_criterion: dict = {}
    for v in vendors:
        ctext = None
        for c in crits:
            key = (v.vendor_id, c.criterion_id)
            if key in already_active or key in already_pending:
                continue
            evidence = None
            if c.rule_type == "country" and c.rule_value:
                cc = _vendor_countries(v)
                for token in [t.strip().lower() for t in c.rule_value.split(",") if t.strip()]:
                    if token and token in cc:
                        evidence = f"Country exposure: {token.title()}"; break
            elif c.rule_type == "keyword" and c.rule_value:
                if ctext is None:
                    ctext = _vendor_text(s, v.vendor_id)
                for token in [t.strip().lower() for t in c.rule_value.split(",") if t.strip()]:
                    if token and token in ctext:
                        evidence = f"Adverse signal matched: '{token}'"; break
            elif c.rule_type == "flag" and c.rule_value:
                evidence = _eval_flag(s, v, c.rule_value.strip())
            if evidence:
                s.add(WatchlistCandidate(
                    candidate_id=next_id(s, "watchlist_candidate"), vendor_id=v.vendor_id,
                    criterion_id=c.criterion_id, evidence=evidence, status="pending"))
                created += 1
                by_criterion[c.name] = by_criterion.get(c.name, 0) + 1
    s.commit()
    return {"created": created, "vendors_scanned": len(vendors),
            "criteria_evaluated": len(crits), "by_criterion": by_criterion,
            "run_by": actor, "run_at": datetime.now(timezone.utc).isoformat()}


def list_candidates(s: Session, status: str = "pending") -> list[dict]:
    q = select(WatchlistCandidate)
    if status and status != "all":
        q = q.where(WatchlistCandidate.status == status)
    rows = s.scalars(q.order_by(WatchlistCandidate.detected_at.desc())).all()
    names = {v.vendor_id: v.legal_name for v in s.scalars(select(VendorRecord)).all()}
    crit = {c.criterion_id: c for c in s.scalars(select(WatchlistCriterion)).all()}
    out = []
    for c in rows:
        cr = crit.get(c.criterion_id)
        out.append({"candidate_id": c.candidate_id, "vendor_id": c.vendor_id,
                    "vendor_name": names.get(c.vendor_id), "criterion_id": c.criterion_id,
                    "criterion_name": cr.name if cr else c.criterion_id,
                    "severity": cr.severity if cr else "High",
                    "evidence": c.evidence, "status": c.status,
                    "detected_at": c.detected_at.isoformat() if c.detected_at else None,
                    "decided_by": c.decided_by})
    return out


def decide_candidate(s: Session, cand_id: str, decision: str, actor: str) -> dict:
    c = s.scalars(select(WatchlistCandidate).where(WatchlistCandidate.candidate_id == cand_id)).first()
    if not c:
        raise ValueError("candidate not found")
    if c.status != "pending":
        raise ValueError(f"candidate already {c.status}")
    c.status = "approved" if decision == "approve" else "rejected"
    c.decided_by = actor
    c.decided_at = datetime.now(timezone.utc).isoformat()
    entry = None
    if decision == "approve":
        cr = s.scalars(select(WatchlistCriterion).where(
            WatchlistCriterion.criterion_id == c.criterion_id)).first()
        entry = add_entry(s, {
            "vendor_id": c.vendor_id, "criterion_id": c.criterion_id,
            "reason": (f"{cr.name}: {c.evidence}" if cr else c.evidence) or "Sweep match",
            "severity": cr.severity if cr else "High"}, actor, source="sweep")
    s.commit()
    return {"candidate_id": cand_id, "status": c.status, "entry": entry}


# ---------------------------------------------------------------- summary
def summary(s: Session) -> dict:
    active = s.scalars(select(SupplierWatchlistEntry).where(SupplierWatchlistEntry.status == "Active")).all()
    by_sev: dict = {}
    for e in active:
        by_sev[e.severity] = by_sev.get(e.severity, 0) + 1
    today = date.today().isoformat()
    overdue = sum(1 for e in active if e.next_review_date and e.next_review_date < today)
    pending = s.scalar(select(func.count()).select_from(WatchlistCandidate).where(
        WatchlistCandidate.status == "pending")) or 0
    return {"active": len(active), "by_severity": by_sev, "reviews_overdue": overdue,
            "pending_candidates": int(pending),
            "watchlisted_vendors": len(set(e.vendor_id for e in active))}


# ---------------------------------------------------------------- notes
def _note_dict(n: SupplierNote) -> dict:
    return {"note_id": n.note_id, "vendor_id": n.vendor_id, "body": n.body,
            "category": n.category, "author": n.author,
            "created_at": n.created_at.isoformat() if n.created_at else None}


def list_notes(s: Session, vendor_id: str) -> list[dict]:
    rows = s.scalars(select(SupplierNote).where(SupplierNote.vendor_id == vendor_id)
                     .order_by(SupplierNote.created_at.desc())).all()
    return [_note_dict(n) for n in rows]


def add_note(s: Session, vendor_id: str, body: str, author: str, category: str = "General") -> dict:
    n = SupplierNote(note_id=next_id(s, "supplier_note"), vendor_id=vendor_id,
                     body=body, category=category or "General", author=author)
    s.add(n); s.commit()
    return _note_dict(n)


def delete_note(s: Session, note_id: str) -> None:
    n = s.scalars(select(SupplierNote).where(SupplierNote.note_id == note_id)).first()
    if n:
        s.delete(n); s.commit()
