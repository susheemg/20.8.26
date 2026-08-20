"""
Registry service layer — business logic over the registry models.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.domain import master_data as MD
from app.features.domain.registry_models import (
    ArtefactRecord, AssessmentRecord, ContactRecord, EngagementRecord,
    FindingRecord, FourthPartyRecord, FourthPartyVendor, IdCounter,
    IndustryMaster, IssueRecord, MaterialGroupMaster, RemediationRecord,
    VendorGroup, VendorIndustry, VendorRecord,
)


# ---- ID minting ----
def next_id(s: Session, entity: str) -> str:
    """Allocate the next display identifier for an entity.

    DB-06: this is a read-modify-write on a shared counter. Without a lock, two
    concurrent transactions can read the same sequence and mint the same identifier —
    invisible on SQLite (one global writer) but real on PostgreSQL under concurrent
    workers, which is exactly where CSV import and autonomous assessment run. The row
    is therefore locked for update where the backend supports it; the unique
    constraints on the identity columns remain the final backstop.
    """
    try:
        if s.bind is not None and s.bind.dialect.name != "sqlite":
            row = s.execute(
                select(IdCounter).where(IdCounter.entity == entity).with_for_update()
            ).scalar_one_or_none()
        else:
            row = s.get(IdCounter, entity)
    except Exception:
        row = s.get(IdCounter, entity)
    if not row:
        row = IdCounter(entity=entity, last_seq=0)
        s.add(row)
        s.flush()
    row.last_seq += 1
    s.flush()
    return MD.format_id(entity, row.last_seq)


# ---- seeding ----
def seed_masters(s: Session) -> None:
    if not s.scalar(select(func.count()).select_from(IndustryMaster)):
        for it in MD.SIC_INDUSTRIES:
            s.add(IndustryMaster(industry_id=it["name"], sic_code=it["code"],
                                 division=it["division"]))
    if not s.scalar(select(func.count()).select_from(MaterialGroupMaster)):
        for mg in MD.UNSPSC_SEGMENTS:
            s.add(MaterialGroupMaster(material_group_id=mg["name"], unspsc_code=mg["code"]))
    s.flush()


# ---- vendor group: AI-proposed assignment (overridable) ----
def propose_group(s: Session, legal_name: str,
                  parent: Optional[str] = None) -> tuple[str, bool]:
    """Return (group_id, ai_assigned). Heuristic: match on parent company or a
    shared significant name token to an existing group; else mint a new one.
    A live-LLM refinement can override this when a key is set."""
    key = (parent or legal_name or "").strip().lower()
    if key:
        # token-overlap match against existing groups
        token = key.split()[0] if key.split() else key
        for g in s.scalars(select(VendorGroup)).all():
            gkey = (g.parent_company or g.name or "").lower()
            if token and token in gkey:
                return g.group_id, True
    gid = next_id(s, "group")
    s.add(VendorGroup(group_id=gid, name=parent or legal_name,
                      parent_company=parent, ai_assigned=True))
    s.flush()
    return gid, True


def create_vendor(s: Session, *, legal_name: str, created_via: str = "button",
                  group_id: Optional[str] = None, parent: Optional[str] = None,
                  industries: Optional[list[str]] = None,
                  tier: str = "Tier 3", **fields) -> VendorRecord:
    vid = next_id(s, "vendor")
    if not group_id:
        group_id, _ = propose_group(s, legal_name, parent)
    v = VendorRecord(vendor_id=vid, group_id=group_id, legal_name=legal_name,
                     tier=tier, created_via=created_via, **fields)
    s.add(v)
    s.flush()
    for ind in (industries or []):
        if s.get(IndustryMaster, ind) or s.scalars(
                select(IndustryMaster).where(IndustryMaster.industry_id == ind)).first():
            s.add(VendorIndustry(vendor_id=vid, industry_id=ind))
    return v


def add_contact(s: Session, *, owner_type: str, owner_id: str, name: str,
                is_primary: bool = False, **fields) -> ContactRecord:
    # only one primary per owner
    if is_primary:
        for c in s.scalars(select(ContactRecord).where(
                ContactRecord.owner_type == owner_type,
                ContactRecord.owner_id == owner_id,
                ContactRecord.is_primary == True)).all():  # noqa: E712
            c.is_primary = False
    c = ContactRecord(owner_type=owner_type, owner_id=owner_id, name=name,
                      is_primary=is_primary, **fields)
    s.add(c)
    s.flush()
    return c


def create_engagement(s: Session, *, vendor_id: str, title: str,
                      owner_user: Optional[str] = None, **fields) -> EngagementRecord:
    eid = next_id(s, "engagement")
    e = EngagementRecord(engagement_id=eid, vendor_id=vendor_id, title=title,
                         owner_user=owner_user, **fields)
    s.add(e)
    s.flush()
    return e


# ---- assessor load-balancing ----
def assign_assessor(s: Session, assessor_pool: list[str]) -> Optional[str]:
    """Return the assessor with the fewest currently-open assigned assessments."""
    if not assessor_pool:
        return None
    counts = {a: 0 for a in assessor_pool}
    for r in s.scalars(select(AssessmentRecord).where(
            AssessmentRecord.assessor_user.in_(assessor_pool),
            AssessmentRecord.status != "Approved")).all():
        if r.assessor_user in counts:
            counts[r.assessor_user] += 1
    return min(counts, key=counts.get)


def create_assessment(s: Session, *, engagement_id: str, vendor_id: Optional[str],
                      engagement_owner: Optional[str], session_id: Optional[int] = None,
                      inherent_band: Optional[str] = None,
                      residual_band: Optional[str] = None,
                      assessor_pool: Optional[list[str]] = None) -> AssessmentRecord:
    aid = next_id(s, "assessment")
    # engagement owner is the default SPOC
    rec = AssessmentRecord(assessment_id=aid, engagement_id=engagement_id,
                           vendor_id=vendor_id, session_id=session_id,
                           status="Drafted", inherent_band=inherent_band,
                           residual_band=residual_band,
                           engagement_owner=engagement_owner, spoc_user=engagement_owner)
    # HIGH inherent must be assigned to an assessor (min load) + signed off
    if inherent_band == "HIGH":
        rec.assessor_user = assign_assessor(s, assessor_pool or [])
    s.add(rec)
    s.flush()
    # link latest assessment onto the engagement; propagate bands to the engagement
    eng = s.scalars(select(EngagementRecord).where(
        EngagementRecord.engagement_id == engagement_id)).first()
    if eng:
        eng.assessment_id = aid
        if inherent_band:
            eng.inherent_band = inherent_band
        if residual_band:
            eng.residual_band = residual_band
    return rec


def approve_assessment(s: Session, assessment_id: str) -> AssessmentRecord:
    rec = s.scalars(select(AssessmentRecord).where(
        AssessmentRecord.assessment_id == assessment_id)).first()
    if not rec:
        raise ValueError("assessment not found")
    if rec.inherent_band == "HIGH" and not rec.assessor_signed_off:
        raise ValueError("HIGH inherent risk requires assessor sign-off before approval")
    rec.status = "Approved"
    rec.locked = True   # hard-lock: immutable hereafter
    return rec


# ---- findings + remediation; open-actions rollup ----
def create_finding(s: Session, *, title: str, severity: str = "Medium",
                   source: str = "Assessor", **fields) -> FindingRecord:
    fid = next_id(s, "finding")
    f = FindingRecord(finding_id=fid, title=title, severity=severity,
                      source=source, **fields)
    s.add(f)
    s.flush()
    _recompute_open_actions(s, fields.get("engagement_id"))
    return f


def create_remediation(s: Session, *, finding_id: str, plan: str,
                       **fields) -> RemediationRecord:
    rid = next_id(s, "remediation")
    r = RemediationRecord(remediation_id=rid, finding_id=finding_id, plan=plan, **fields)
    s.add(r)
    s.flush()
    f = s.scalars(select(FindingRecord).where(
        FindingRecord.finding_id == finding_id)).first()
    if f:
        f.remediation_id = rid
        f.status = "In Remediation"
    return r


def _recompute_open_actions(s: Session, engagement_id: Optional[str]) -> None:
    if not engagement_id:
        return
    n = s.scalar(select(func.count()).select_from(FindingRecord).where(
        FindingRecord.engagement_id == engagement_id,
        FindingRecord.status != "Closed"))
    eng = s.scalars(select(EngagementRecord).where(
        EngagementRecord.engagement_id == engagement_id)).first()
    if eng:
        eng.open_actions = int(n or 0)


# ---- fourth parties ----
def create_fourth_party(s: Session, *, legal_name: str,
                        vendor_ids: Optional[list[str]] = None,
                        also_vendor_id: Optional[str] = None,
                        **fields) -> FourthPartyRecord:
    fid = next_id(s, "fourth_party")
    fp = FourthPartyRecord(fourth_party_id=fid, legal_name=legal_name,
                           vendor_id=also_vendor_id, **fields)
    s.add(fp)
    s.flush()
    for vid in (vendor_ids or []):
        s.add(FourthPartyVendor(fourth_party_id=fid, vendor_id=vid))
    s.flush()
    # concentration: same 4th party behind >= 3 vendors
    cnt = s.scalar(select(func.count()).select_from(FourthPartyVendor).where(
        FourthPartyVendor.fourth_party_id == fid))
    if (cnt or 0) >= 3:
        fp.concentration_flag = True
    return fp


# ---- artefacts + revalidation engine ----
def create_artefact(s: Session, *, vendor_id: str, name: str,
                    artefact_type: str = "certificate", expiry_date: Optional[str] = None,
                    received_via: str = "upload", supersedes: Optional[str] = None,
                    **fields) -> ArtefactRecord:
    aid = next_id(s, "artefact")
    art = ArtefactRecord(artefact_id=aid, vendor_id=vendor_id, name=name,
                         artefact_type=artefact_type, expiry_date=expiry_date,
                         received_via=received_via, supersedes=supersedes, **fields)
    s.add(art)
    s.flush()
    if supersedes:
        prior = s.scalars(select(ArtefactRecord).where(
            ArtefactRecord.artefact_id == supersedes)).first()
        if prior:
            prior.is_current = False
        # refreshing a cert auto-closes any open expired-cert issue for it
        _close_issues_for_artefact(s, supersedes, "certificate refreshed")
        _close_issues_for_vendor_cert(s, vendor_id, name, "certificate refreshed")
    _refresh_artefact_status(art)
    return art


def _refresh_artefact_status(art: ArtefactRecord) -> None:
    if not art.expiry_date:
        return
    try:
        exp = date.fromisoformat(art.expiry_date[:10])
    except Exception:
        return
    today = date.today()
    if exp < today:
        art.status = "Expired"
    elif exp <= today + timedelta(days=7):
        art.status = "Expiring"
    else:
        art.status = "Valid"


def revalidation_run(s: Session) -> dict:
    """Weekend/on-request sweep. Updates statuses, returns the items needing a
    7-day expiry notice and the >30-day-expired items that became Issues."""
    notify_7day: list[dict] = []
    new_issues: list[dict] = []
    today = date.today()
    arts = s.scalars(select(ArtefactRecord).where(
        ArtefactRecord.is_current == True,  # noqa: E712
        ArtefactRecord.is_dated == True)).all()  # noqa: E712
    for art in arts:
        _refresh_artefact_status(art)
        if not art.expiry_date:
            continue
        try:
            exp = date.fromisoformat(art.expiry_date[:10])
        except Exception:
            continue
        # expiring within 7 days -> notify
        if today <= exp <= today + timedelta(days=7):
            notify_7day.append({"artefact_id": art.artefact_id, "vendor_id": art.vendor_id,
                                "name": art.name, "expiry": art.expiry_date})
        # expired > 30 days -> log Issue (once)
        if exp < today - timedelta(days=30):
            existing = s.scalars(select(IssueRecord).where(
                IssueRecord.artefact_id == art.artefact_id,
                IssueRecord.status == "Open")).first()
            if not existing:
                v = s.scalars(select(VendorRecord).where(
                    VendorRecord.vendor_id == art.vendor_id)).first()
                iid = next_id(s, "issue")
                s.add(IssueRecord(issue_id=iid, vendor_id=art.vendor_id,
                                  vendor_name=v.legal_name if v else art.vendor_id,
                                  artefact_id=art.artefact_id, kind="expired_certificate",
                                  detail=f"{art.name} expired {art.expiry_date} (>30 days)."))
                new_issues.append({"issue_id": iid, "artefact_id": art.artefact_id,
                                   "vendor_id": art.vendor_id})
    s.flush()
    return {"checked": len(arts), "notify_7day": notify_7day, "new_issues": new_issues}


def _close_issues_for_artefact(s: Session, artefact_id: str, reason: str) -> None:
    for iss in s.scalars(select(IssueRecord).where(
            IssueRecord.artefact_id == artefact_id, IssueRecord.status == "Open")).all():
        iss.status = "Closed"; iss.closed_reason = reason; iss.closed_at = datetime.now(timezone.utc)


def _close_issues_for_vendor_cert(s: Session, vendor_id: str, name: str, reason: str) -> None:
    for iss in s.scalars(select(IssueRecord).where(
            IssueRecord.vendor_id == vendor_id, IssueRecord.status == "Open")).all():
        if iss.detail and name.split()[0].lower() in iss.detail.lower():
            iss.status = "Closed"; iss.closed_reason = reason
            iss.closed_at = datetime.now(timezone.utc)


def close_issues_for_engagement(s: Session, vendor_id: str) -> int:
    """Auto-close cert issues when an engagement closes (and no active engagement
    for the vendor remains relying on it)."""
    active = s.scalar(select(func.count()).select_from(EngagementRecord).where(
        EngagementRecord.vendor_id == vendor_id,
        EngagementRecord.status == "Active"))
    if active and active > 0:
        return 0
    n = 0
    for iss in s.scalars(select(IssueRecord).where(
            IssueRecord.vendor_id == vendor_id, IssueRecord.status == "Open")).all():
        iss.status = "Closed"; iss.closed_reason = "engagement closed"
        iss.closed_at = datetime.now(timezone.utc); n += 1
    return n


def schedule_reassessment(s: Session, *, vendor_id: Optional[str] = None,
                          engagement_id: Optional[str] = None,
                          reason: str = "Data updated", when: Optional[str] = None) -> int:
    """Flag engagement(s) for reassessment when underlying data changes.
    Sets next_assessment_due (defaults to today = due now) and records the reason.
    Returns the number of engagements scheduled."""
    due = when or date.today().isoformat()
    q = select(EngagementRecord)
    if engagement_id:
        q = q.where(EngagementRecord.engagement_id == engagement_id)
    elif vendor_id:
        q = q.where(EngagementRecord.vendor_id == vendor_id)
    else:
        return 0
    n = 0
    for e in s.scalars(q).all():
        e.next_assessment_due = due
        e.reassessment_reason = reason
        n += 1
    s.flush()
    return n


def _cadence_months(e) -> int:
    band = (e.inherent_band or "").upper()
    if getattr(e, "is_critical", False) or band in ("HIGH", "CRITICAL"):
        return 6
    if band == "ELEVATED":
        return 12
    return 24


_CADENCE_DEFAULTS = {"LOW": 36, "MODERATE": 24, "ELEVATED": 12, "HIGH": 12, "CRITICAL": 12}


def cadence_months_for(s: Session, band: Optional[str], is_critical: bool = False) -> int:
    """Reassessment interval (months) by inherent severity, read from config.
    Default logic: Low=36 (3y), Medium/MODERATE=24 (2y), Elevated/High/Critical=12 (annual)."""
    from app.features.domain.config_store import get_config
    b = (band or "MODERATE").upper().replace("MEDIUM", "MODERATE")
    if is_critical:
        b = "CRITICAL"
    if b not in _CADENCE_DEFAULTS:
        b = "MODERATE"
    try:
        return int(get_config(s, f"reassessment.months.{b}", _CADENCE_DEFAULTS[b]))
    except Exception:
        return _CADENCE_DEFAULTS[b]


def add_months_iso(iso_date: str, months: int) -> Optional[str]:
    """Add N months to an ISO date string, clamping day to 28 for safety."""
    try:
        y, m, dd = (int(x) for x in iso_date.split("-"))
        total = (m - 1) + int(months)
        ny, nm = y + total // 12, total % 12 + 1
        return date(ny, nm, min(dd, 28)).isoformat()
    except Exception:
        return None


def record_last_assessment(s: Session, engagement_id: str, when: Optional[str] = None) -> None:
    """Record that an assessment completed on an engagement: stamps last_assessment_date,
    computes next_assessment_due from the configured cadence, clears any reassessment flag."""
    e = s.scalars(select(EngagementRecord).where(
        EngagementRecord.engagement_id == engagement_id)).first()
    if not e:
        return
    d = when or date.today().isoformat()
    e.last_assessment_date = d
    months = cadence_months_for(s, e.inherent_band, getattr(e, "is_critical", False))
    nd = add_months_iso(d, months)
    if nd:
        e.next_assessment_due = nd
    e.reassessment_reason = None
    s.flush()


def apply_screening_outcome(s: Session, vendor_id, vendor_name, band, detail, by,
                            audit_fn=None) -> dict:
    """Wire a sanctions screening result into risk: maintain a single open sanctions
    Issue per vendor (kind sanctions_hit / sanctions_review) and conservatively escalate
    the vendor to Critical on a confirmed Hit. Re-screening Clear auto-closes the Issue.
    Shared by the screening endpoints and the scheduled monitoring sweep."""
    if not vendor_id:
        return {}
    openi = [i for i in s.scalars(select(IssueRecord).where(
        IssueRecord.vendor_id == vendor_id, IssueRecord.status == "Open")).all()
        if (i.kind or "").startswith("sanctions_")]
    if band == "Clear":
        for i in openi:
            i.status = "Closed"; i.closed_reason = "re-screened clear"
            i.closed_at = datetime.now(timezone.utc)
        return {"issue": None, "escalated": False, "closed": len(openi)}
    kind = "sanctions_hit" if band == "Hit" else "sanctions_review"
    issue = openi[0] if openi else None
    if issue:
        issue.kind = kind; issue.detail = detail
    else:
        iid = next_id(s, "issue")
        issue = IssueRecord(issue_id=iid, vendor_id=vendor_id, vendor_name=vendor_name,
                            kind=kind, detail=detail, status="Open")
        s.add(issue)
    escalated = False
    if band == "Hit":
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
        if v and not v.is_critical:
            v.is_critical = True
            v.criticality_reason = f"Sanctions screening hit — {detail}"[:300]
            escalated = True
            if audit_fn:
                audit_fn(s, "sanctions.criticality_escalation", by,
                         {"vendor_id": vendor_id, "detail": detail})
    return {"issue": issue.issue_id, "kind": kind, "escalated": escalated}
