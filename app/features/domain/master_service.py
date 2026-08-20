"""
Service layer for the extended data model (Req 1/2/3).

Thin upsert + read helpers over master_ext models, plus:
- rollup refreshers (risk profile, cyber certs, performance, concentration) that
  read from the existing registry records so cached rollups never drift
- a data-quality completeness scorer
- overdue-obligation surfacing into the issues/action view
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.domain import master_ext as MX
from app.features.domain.registry_models import (
    ArtefactRecord, AssessmentRecord, EngagementRecord, FindingRecord,
    FourthPartyRecord, RemediationRecord, VendorRecord,
)


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line.
    Never raises — observability must not change control flow."""
    try:
        from app.features.admin.security import log_json as _lj
    except Exception:
        return
    try:
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass


def _today() -> str:
    return date.today().isoformat()


# ---------- generic 1:1 upsert ----------
def _get_or_create(s: Session, model, vendor_id: str):
    row = s.scalars(select(model).where(model.vendor_id == vendor_id)).first()
    if not row:
        row = model(vendor_id=vendor_id)
        s.add(row)
        s.flush()
    return row


def _apply(row, data: dict, allowed: set):
    for k, v in (data or {}).items():
        if k in allowed and hasattr(row, k):
            setattr(row, k, v)


# ============================================================
# REQ 1 — Vendor master extension
# ============================================================
VENDOR_EXT_FIELDS = {
    "euid", "erp_id", "sourcing_id", "grc_id", "dba_names", "previous_names",
    "operating_status", "immediate_parent", "subsidiaries", "ownership_type",
    "exchange", "sic_code", "unspsc_code", "nace_naics", "supplier_category",
    "segmentation", "spend_band", "sole_source", "substitutability",
    "relationship_owner", "sponsoring_bu", "cost_centre", "strategic_importance",
    "business_dependency", "relationship_health", "billing_address",
    "remittance_address", "operating_address", "service_countries",
    "data_locations", "offshore_flag", "geopolitical_risk",
    "sanctions_jurisdiction_exposure", "currency", "payment_method",
    "credit_limit", "annual_spend", "spend_trend", "discount_terms",
    "credit_rating", "credit_rating_date", "financial_health_band",
    "going_concern_flag", "vat_number", "w_form_status", "tax_residency",
    "regulatory_licences", "regulated_entity",
}
# banking fields are sensitive — separated so they can be access-gated
VENDOR_BANK_FIELDS = {
    "bank_account_name", "iban", "swift_bic", "routing_number",
    "bank_verified", "bank_verified_date", "bank_change_locked",
}


def get_vendor_master(s: Session, vendor_id: str, include_bank: bool = False) -> dict:
    v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
    if not v:
        return {}
    ext = s.scalars(select(MX.VendorMasterExt).where(MX.VendorMasterExt.vendor_id == vendor_id)).first()
    out = {
        "vendor_id": v.vendor_id, "group_id": v.group_id, "legal_name": v.legal_name,
        "trading_name": v.trading_name, "registration_number": v.registration_number,
        "lei": v.lei, "duns": v.duns, "tax_id": v.tax_id, "website": v.website,
        "incorporation_country": v.incorporation_country, "incorporation_date": v.incorporation_date,
        "legal_form": v.legal_form, "listing_status": v.listing_status, "ticker": v.ticker,
        "ultimate_parent": v.ultimate_parent, "hq_address": v.hq_address, "hq_country": v.hq_country,
        "tier": v.tier, "is_critical": v.is_critical, "status": v.status,
    }
    if ext:
        for f in VENDOR_EXT_FIELDS:
            out[f] = getattr(ext, f, None)
        out["ubo"] = json.loads(ext.ubo_json or "[]")
        if include_bank:
            for f in VENDOR_BANK_FIELDS:
                out[f] = getattr(ext, f, None)
        else:
            out["banking"] = "restricted"
    return out


def update_vendor_master(s: Session, vendor_id: str, data: dict,
                         include_bank: bool = False) -> MX.VendorMasterExt:
    ext = _get_or_create(s, MX.VendorMasterExt, vendor_id)
    _apply(ext, data, VENDOR_EXT_FIELDS)
    if "ubo" in (data or {}):
        ext.ubo_json = json.dumps(data["ubo"])
    if include_bank:
        _apply(ext, data, VENDOR_BANK_FIELDS)
    ext.updated_at = datetime.now(timezone.utc)
    s.flush()
    return ext


# ============================================================
# REQ 2 — Vendor attribute domains
# ============================================================
SCREEN_TYPES = ["sanctions", "pep", "adverse_media", "abac", "debarment",
                "modern_slavery", "coi"]


def set_screening(s: Session, vendor_id: str, screen_type: str, *,
                  result: Optional[str] = None, detail: Optional[str] = None,
                  screened_date: Optional[str] = None,
                  next_due: Optional[str] = None) -> MX.VendorScreening:
    row = s.scalars(select(MX.VendorScreening).where(
        MX.VendorScreening.vendor_id == vendor_id,
        MX.VendorScreening.screen_type == screen_type)).first()
    if not row:
        row = MX.VendorScreening(vendor_id=vendor_id, screen_type=screen_type)
        s.add(row)
    if result is not None:
        row.result = result
    if detail is not None:
        row.detail = detail
    row.screened_date = screened_date or _today()
    if next_due is not None:
        row.next_due = next_due
    row.updated_at = datetime.now(timezone.utc)
    s.flush()
    return row


def list_screening(s: Session, vendor_id: str) -> list[dict]:
    rows = s.scalars(select(MX.VendorScreening).where(
        MX.VendorScreening.vendor_id == vendor_id)).all()
    by = {r.screen_type: r for r in rows}
    out = []
    for t in SCREEN_TYPES:
        r = by.get(t)
        out.append({"screen_type": t,
                    "result": r.result if r else None,
                    "detail": r.detail if r else None,
                    "screened_date": r.screened_date if r else None,
                    "next_due": r.next_due if r else None,
                    "overdue": bool(r and r.next_due and r.next_due < _today())})
    return out


PRIVACY_FIELDS = {"processes_personal_data", "role", "dpa_in_place",
                  "data_categories", "data_subject_types", "transfer_mechanism",
                  "subprocessor_list_maintained", "ropa_reference", "retention_terms"}
CYBER_FIELDS = {"assurance_status", "external_rating", "external_rating_date",
                "pentest_recency", "breach_history_flag", "security_contact"}
RESILIENCE_FIELDS = {"supports_critical_function", "shared_upstream_flags",
                     "spof_flag", "bcp_in_place", "bcp_last_tested", "bcp_test_result",
                     "exit_plan_documented", "exit_plan_tested", "exit_plan_tested_date",
                     "rto", "rpo", "alternative_provider", "portability_status",
                     "switching_cost"}
ESG_FIELDS = {"esg_rating", "esg_rating_source", "scope3_sbt_status",
              "environmental_certs", "labour_audit_findings",
              "diversity_classification", "conflict_minerals_exposure"}
GOV_FIELDS = {"source_of_truth", "match_confidence", "duplicate_cluster_id",
              "data_steward", "source_system", "consent_basis", "lifecycle_state",
              "approval_status", "approver", "offboarding_date", "offboarding_reason",
              "do_not_use_flag", "do_not_use_reason"}


def update_privacy(s, vendor_id, data):
    row = _get_or_create(s, MX.VendorPrivacy, vendor_id)
    _apply(row, data, PRIVACY_FIELDS); row.updated_at = datetime.now(timezone.utc); s.flush(); return row


def update_cyber(s, vendor_id, data):
    row = _get_or_create(s, MX.VendorCyber, vendor_id)
    _apply(row, data, CYBER_FIELDS); row.updated_at = datetime.now(timezone.utc); s.flush(); return row


def update_resilience(s, vendor_id, data):
    row = _get_or_create(s, MX.VendorResilience, vendor_id)
    _apply(row, data, RESILIENCE_FIELDS)
    if "nth_party" in (data or {}):
        row.nth_party_json = json.dumps(data["nth_party"])
    row.updated_at = datetime.now(timezone.utc); s.flush(); return row


def update_esg(s, vendor_id, data):
    row = _get_or_create(s, MX.VendorESG, vendor_id)
    _apply(row, data, ESG_FIELDS); row.updated_at = datetime.now(timezone.utc); s.flush(); return row


def update_governance(s, vendor_id, data):
    row = _get_or_create(s, MX.VendorGovernanceMeta, vendor_id)
    _apply(row, data, GOV_FIELDS); row.updated_at = datetime.now(timezone.utc)
    row.record_version = (row.record_version or 1) + 1
    s.flush(); return row


def add_insurance(s, vendor_id, data):
    row = MX.VendorInsurance(vendor_id=vendor_id, policy_type=data.get("policy_type", "other"))
    for f in ("coverage_limit", "currency", "insurer", "certificate_expiry", "named_insured_verified"):
        if f in data:
            setattr(row, f, data[f])
    s.add(row); s.flush(); return row


def add_monitor_signal(s, vendor_id, signal_type, value, source=None):
    row = MX.VendorMonitorSignal(vendor_id=vendor_id, signal_type=signal_type,
                                 value=value, source=source, captured_at=_today())
    s.add(row); s.flush(); return row


# ---------- rollup refreshers (read from existing records) ----------
def refresh_cyber_certs(s: Session, vendor_id: str):
    """Roll current artefacts into the cyber certifications cache."""
    arts = s.scalars(select(ArtefactRecord).where(
        ArtefactRecord.vendor_id == vendor_id,
        ArtefactRecord.is_current == True)).all()  # noqa: E712
    certs = [{"name": a.name, "expiry": getattr(a, "expiry_date", None),
              "status": getattr(a, "status", None)} for a in arts]
    row = _get_or_create(s, MX.VendorCyber, vendor_id)
    row.certifications_json = json.dumps(certs)
    s.flush()
    return certs


def _vendor_exists(s: Session, vendor_id: Optional[str]) -> bool:
    if not vendor_id:
        return False
    return s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first() is not None


def persist_fdd(s: Session, vendor_id: str, result: dict) -> bool:
    """R1: persist an FDD result against a registered vendor. Writes the health
    band to the vendor master and stamps the latest risk-profile fields on refresh.
    Returns True if persisted, False if the vendor is unregistered ('Other')."""
    if not _vendor_exists(s, vendor_id):
        return False
    ext = _get_or_create(s, MX.VendorMasterExt, vendor_id)
    ext.financial_health_band = result.get("banding")
    if (result.get("flags") or {}).get("goingConcern"):
        ext.going_concern_flag = True
    # capture as a monitoring signal too, so trajectory is visible
    add_monitor_signal(s, vendor_id, "financial_health",
                       value=str(result.get("banding")), source="FDD engine")
    s.flush()
    return True


def persist_reputation(s: Session, vendor_id: str, result: dict) -> bool:
    """R1: persist a reputation result against a registered vendor."""
    if not _vendor_exists(s, vendor_id):
        return False
    summary = f"{result.get('verdict', '?')} ({result.get('overall', '?')})"
    add_monitor_signal(s, vendor_id, "reputation", value=summary, source="Reputation engine")
    # stash on the next risk-profile snapshot via a lightweight cache row
    rp = MX.VendorRiskProfile(vendor_id=vendor_id, reputation_summary=summary)
    s.add(rp)
    s.flush()
    return True


def persist_monitor_result(s: Session, vendor_id: Optional[str], signal: str,
                           detail: Optional[str] = None) -> bool:
    """R1: reconcile FinMonitorRecord signal into the attribute time-series."""
    if not _vendor_exists(s, vendor_id):
        return False
    add_monitor_signal(s, vendor_id, "monitoring", value=signal,
                       source="Financial monitoring sweep")
    s.flush()
    return True


def _latest_signal(s: Session, vendor_id: str, signal_type: str) -> Optional[str]:
    row = s.scalars(select(MX.VendorMonitorSignal).where(
        MX.VendorMonitorSignal.vendor_id == vendor_id,
        MX.VendorMonitorSignal.signal_type == signal_type)
        .order_by(MX.VendorMonitorSignal.id.desc())).first()
    return row.value if row else None


def refresh_risk_profile(s: Session, vendor_id: str) -> MX.VendorRiskProfile:
    """Compute a fresh, time-stamped risk-profile snapshot from engagements,
    findings and assessments, AND the persisted intelligence signals (R1)."""
    engs = s.scalars(select(EngagementRecord).where(
        EngagementRecord.vendor_id == vendor_id)).all()
    findings = s.scalars(select(FindingRecord).where(
        FindingRecord.vendor_id == vendor_id, FindingRecord.status != "Closed")).all()
    asms = s.scalars(select(AssessmentRecord).where(
        AssessmentRecord.vendor_id == vendor_id)).all()
    rank = {"HIGH": 3, "ELEVATED": 2, "MODERATE": 1, "LOW": 0}
    sev_rank = {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}

    def _worst(bands):
        bands = [b for b in bands if b]
        return max(bands, key=lambda b: rank.get(b, -1)) if bands else None

    inherent = _worst([e.inherent_band for e in engs])
    residual = _worst([e.residual_band for e in engs])
    # fall back to assessment-derived bands where engagements carry none
    if inherent is None:
        inherent = _worst([a.inherent_band for a in asms])
    if residual is None:
        residual = _worst([a.residual_band for a in asms])
    max_sev = None
    if findings:
        max_sev = max((f.severity for f in findings), key=lambda x: sev_rank.get(x, -1))
    fourth = s.scalars(select(FourthPartyRecord)).all()
    concentration = sum(1 for f in fourth if getattr(f, "concentration_flag", False))

    # R1: read persisted intelligence signals
    ext = s.scalars(select(MX.VendorMasterExt).where(
        MX.VendorMasterExt.vendor_id == vendor_id)).first()
    fin_band = ext.financial_health_band if ext else None
    monitoring_signal = _latest_signal(s, vendor_id, "monitoring")
    # carry forward the most recent reputation summary already snapshotted
    prior_rep = s.scalars(select(MX.VendorRiskProfile).where(
        MX.VendorRiskProfile.vendor_id == vendor_id,
        MX.VendorRiskProfile.reputation_summary != None)  # noqa: E711
        .order_by(MX.VendorRiskProfile.id.desc())).first()
    reputation_summary = prior_rep.reputation_summary if prior_rep else None
    # carry forward the most recent performance rollup so each snapshot is self-complete
    prior_perf = s.scalars(select(MX.VendorRiskProfile).where(
        MX.VendorRiskProfile.vendor_id == vendor_id,
        MX.VendorRiskProfile.performance_score != None)  # noqa: E711
        .order_by(MX.VendorRiskProfile.id.desc())).first()

    row = MX.VendorRiskProfile(
        vendor_id=vendor_id, inherent_band=inherent, residual_band=residual,
        open_findings=len(findings), max_severity=max_sev,
        monitoring_signal=monitoring_signal, reputation_summary=reputation_summary,
        last_assessment=(sorted([a for a in asms], key=lambda a: a.id)[-1].assessment_id
                         if asms else None),
    )
    # carry forward performance fields (refresh must not blank an existing rollup)
    if prior_perf:
        row.sla_summary = prior_perf.sla_summary
        row.incident_count = prior_perf.incident_count
        row.performance_score = prior_perf.performance_score
        row.review_cadence = prior_perf.review_cadence
        row.last_review = prior_perf.last_review
    s.add(row)
    res = _get_or_create(s, MX.VendorResilience, vendor_id)
    res.concentration_indicator = concentration
    s.flush()
    # bound history: keep only the most recent N snapshots per vendor (time-series cap)
    _prune_risk_profiles(s, vendor_id, keep=20)
    return row


def _prune_risk_profiles(s: Session, vendor_id: str, keep: int = 20) -> int:
    """Cap the risk-profile snapshot history per vendor to prevent unbounded growth
    from frequent refreshes (each 360-view refreshes). Keeps the newest `keep` rows."""
    ids = list(s.scalars(select(MX.VendorRiskProfile.id).where(
        MX.VendorRiskProfile.vendor_id == vendor_id)
        .order_by(MX.VendorRiskProfile.id.desc())).all())
    stale = ids[keep:]
    if not stale:
        return 0
    for old in s.scalars(select(MX.VendorRiskProfile).where(
            MX.VendorRiskProfile.id.in_(stale))).all():
        s.delete(old)
    s.flush()
    return len(stale)


def latest_risk_profile(s: Session, vendor_id: str) -> Optional[dict]:
    # Coalesce the most recent non-null value of each field across recent snapshots,
    # so the consolidated view is resilient regardless of which engine wrote last
    # (refresh writes risk fields; publish writes performance fields; reputation writes its summary).
    rows = s.scalars(select(MX.VendorRiskProfile).where(
        MX.VendorRiskProfile.vendor_id == vendor_id)
        .order_by(MX.VendorRiskProfile.id.desc())).all()
    if not rows:
        return None
    fields = ["inherent_band", "residual_band", "open_findings", "max_severity",
              "overall_score", "last_assessment", "next_assessment_due",
              "monitoring_signal", "reputation_summary", "sla_summary",
              "incident_count", "performance_score", "review_cadence", "last_review"]
    out = {f: None for f in fields}
    # iterate newest-first; take the first non-null for each field
    # (open_findings/incident_count default 0, so treat the newest snapshot from
    #  refresh as authoritative for those counts)
    count_set = {"open_findings": False, "incident_count": False}
    for r in rows:
        for f in fields:
            if out[f] is None:
                v = getattr(r, f)
                if f in count_set:
                    # take from the first (newest) row that explicitly carries a risk/perf context
                    if not count_set[f]:
                        out[f] = v
                        count_set[f] = True
                elif v is not None:
                    out[f] = v
    newest = rows[0]
    out["snapshot_at"] = newest.snapshot_at.isoformat() if newest.snapshot_at else None
    return out


def vendor_attributes(s: Session, vendor_id: str) -> dict:
    """Assemble the full attribute view for a vendor."""
    def _one(model):
        r = s.scalars(select(model).where(model.vendor_id == vendor_id)).first()
        if not r:
            return None
        return {c.name: getattr(r, c.name) for c in r.__table__.columns}

    refresh_cyber_certs(s, vendor_id)
    return {
        "vendor_id": vendor_id,
        "screening": list_screening(s, vendor_id),
        "privacy": _one(MX.VendorPrivacy),
        "cyber": _one(MX.VendorCyber),
        "resilience": _one(MX.VendorResilience),
        "esg": _one(MX.VendorESG),
        "insurance": [{c.name: getattr(r, c.name) for c in r.__table__.columns}
                      for r in s.scalars(select(MX.VendorInsurance).where(
                          MX.VendorInsurance.vendor_id == vendor_id)).all()],
        "risk_profile": latest_risk_profile(s, vendor_id),
        "monitor_signals": [{"signal_type": r.signal_type, "value": r.value,
                             "source": r.source, "captured_at": r.captured_at}
                            for r in s.scalars(select(MX.VendorMonitorSignal).where(
                                MX.VendorMonitorSignal.vendor_id == vendor_id)
                                .order_by(MX.VendorMonitorSignal.id.desc())).all()],
        "governance": _one(MX.VendorGovernanceMeta),
    }


# ============================================================
# REQ 3 — Engagement register extension + child tables
# ============================================================
ENG_EXT_FIELDS = {c.name for c in MX.EngagementExt.__table__.columns
                  if c.name not in ("id", "engagement_id", "updated_at", "record_version")}


def get_or_create_eng_ext(s: Session, engagement_id: str) -> MX.EngagementExt:
    row = s.scalars(select(MX.EngagementExt).where(
        MX.EngagementExt.engagement_id == engagement_id)).first()
    if not row:
        row = MX.EngagementExt(engagement_id=engagement_id)
        s.add(row); s.flush()
    return row


def update_eng_ext(s: Session, engagement_id: str, data: dict) -> MX.EngagementExt:
    row = get_or_create_eng_ext(s, engagement_id)
    _apply(row, data, ENG_EXT_FIELDS)
    row.record_version = (row.record_version or 1) + 1
    row.updated_at = datetime.now(timezone.utc)
    s.flush()
    return row


_CHILD = {
    "deliverable": MX.EngagementDeliverable,
    "milestone": MX.EngagementMilestone,
    "sla": MX.EngagementSLA,
    "obligation": MX.EngagementObligation,
    "personnel": MX.EngagementPersonnel,
}


def add_eng_child(s: Session, engagement_id: str, kind: str, data: dict):
    model = _CHILD[kind]
    cols = {c.name for c in model.__table__.columns}
    row = model(engagement_id=engagement_id)
    for k, v in (data or {}).items():
        if k in cols and k not in ("id", "engagement_id"):
            setattr(row, k, v)
    s.add(row); s.flush()
    return row


def list_eng_children(s: Session, engagement_id: str, kind: str) -> list[dict]:
    model = _CHILD[kind]
    rows = s.scalars(select(model).where(model.engagement_id == engagement_id)
                     .order_by(model.id)).all()
    return [{c.name: getattr(r, c.name) for c in r.__table__.columns
             if c.name != "created_at"} for r in rows]


def _engagement_is_critical(s: Session, engagement_id: str) -> bool:
    """Latest criticality designation for an engagement (manual override or auto)."""
    d = s.scalars(select(MX.CriticalityDesignation).where(
        MX.CriticalityDesignation.subject_type == "engagement",
        MX.CriticalityDesignation.subject_id == engagement_id)
        .order_by(MX.CriticalityDesignation.id.desc())).first()
    return bool(d and d.is_critical)


def engagement_full(s: Session, engagement_id: str) -> dict:
    eng = s.scalars(select(EngagementRecord).where(
        EngagementRecord.engagement_id == engagement_id)).first()
    if not eng:
        return {}
    ext = s.scalars(select(MX.EngagementExt).where(
        MX.EngagementExt.engagement_id == engagement_id)).first()
    base = {"engagement_id": eng.engagement_id, "vendor_id": eng.vendor_id,
            "title": eng.title, "service_description": eng.service_description,
            "annual_value": eng.annual_value, "currency": eng.currency,
            "start_date": eng.start_date, "end_date": eng.end_date,
            "inherent_band": eng.inherent_band, "residual_band": eng.residual_band,
            "status": eng.status, "stage": eng.stage, "owner_user": eng.owner_user,
            "is_critical": _engagement_is_critical(s, engagement_id)}
    ext_d = ({c.name: getattr(ext, c.name) for c in ext.__table__.columns
              if c.name not in ("id",)} if ext else {})
    return {"base": base, "ext": ext_d,
            "deliverables": list_eng_children(s, engagement_id, "deliverable"),
            "milestones": list_eng_children(s, engagement_id, "milestone"),
            "slas": list_eng_children(s, engagement_id, "sla"),
            "obligations": list_eng_children(s, engagement_id, "obligation"),
            "personnel": list_eng_children(s, engagement_id, "personnel")}


def overdue_obligations(s: Session) -> list[dict]:
    """Surface obligations past due (for the Action Plan / governance view)."""
    today = _today()
    rows = s.scalars(select(MX.EngagementObligation).where(
        MX.EngagementObligation.status != "done",
        MX.EngagementObligation.due_date != None,  # noqa: E711
        MX.EngagementObligation.due_date < today)).all()
    return [{"engagement_id": r.engagement_id, "description": r.description,
             "obl_type": r.obl_type, "due_date": r.due_date,
             "accountable_owner": r.accountable_owner, "consequence": r.consequence}
            for r in rows]


# ---------- data-quality completeness ----------
def dq_completeness(record: dict, fields: list[str]) -> float:
    if not fields:
        return 0.0
    filled = sum(1 for f in fields if record.get(f) not in (None, "", [], {}))
    return round(100.0 * filled / len(fields), 1)


# ============================================================
# REQ 2 — Contract entity service
# ============================================================
# type -> primary link rule (master vs call-off)
MASTER_TYPES = {"MSA", "Framework", "Master"}
CALLOFF_TYPES = {"Contract", "PO", "SOW", "Order", "NDA", "DPA", "Amendment"}


def _next_contract_id(s: Session) -> str:
    from app.features.domain.registry_service import next_id
    return next_id(s, "contract")


def create_contract(s: Session, *, contract_type: str = "Contract",
                    vendor_id: Optional[str] = None, engagement_id: Optional[str] = None,
                    parent_msa: Optional[str] = None, data: Optional[dict] = None,
                    source: str = "manual") -> MX.ContractRecord:
    """Create a contract, applying the type-driven primary-link rule:
    MSA/Framework -> vendor is primary; Contract/PO/SOW/etc -> engagement is primary.
    Both keys are recorded where known. For a call-off, if the engagement is known
    and no vendor given, the vendor is resolved from the engagement."""
    data = data or {}
    is_master = contract_type in MASTER_TYPES
    # resolve vendor from engagement for call-offs when not supplied
    if engagement_id and not vendor_id:
        eng = s.scalars(select(EngagementRecord).where(
            EngagementRecord.engagement_id == engagement_id)).first()
        if eng:
            vendor_id = eng.vendor_id
    primary = "vendor" if is_master else "engagement"
    row = MX.ContractRecord(
        contract_id=_next_contract_id(s), contract_type=contract_type,
        vendor_id=vendor_id, engagement_id=(None if is_master else engagement_id),
        parent_msa=parent_msa, primary_link=primary, source=source)
    # MSA links to vendor only (entity-level); never pins a single engagement
    if is_master:
        row.engagement_id = None
    for k in ("title", "counterparty", "status", "tier", "governing_law",
              "effective_date", "start_date", "end_date", "renewal_type",
              "notice_period", "value", "currency", "terms_json", "gap_review",
              "clause_flags", "doc_link", "version"):
        if k in data and data[k] is not None:
            setattr(row, k, data[k])
    s.add(row); s.flush()
    return row


def list_contracts(s: Session, *, vendor_id: Optional[str] = None,
                   engagement_id: Optional[str] = None) -> list[dict]:
    q = select(MX.ContractRecord)
    if vendor_id:
        q = q.where(MX.ContractRecord.vendor_id == vendor_id)
    if engagement_id:
        q = q.where(MX.ContractRecord.engagement_id == engagement_id)
    rows = s.scalars(q.order_by(MX.ContractRecord.id)).all()
    return [{c.name: getattr(r, c.name) for c in r.__table__.columns
             if c.name not in ("created_at", "updated_at")} for r in rows]


def update_contract(s: Session, contract_id: str, data: dict) -> Optional[MX.ContractRecord]:
    row = s.scalars(select(MX.ContractRecord).where(
        MX.ContractRecord.contract_id == contract_id)).first()
    if not row:
        return None
    cols = {c.name for c in row.__table__.columns}
    for k, v in (data or {}).items():
        if k in cols and k not in ("id", "contract_id", "created_at"):
            setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    s.flush()
    return row


def contract_from_engine(s: Session, *, vendor_id: Optional[str], engagement_id: Optional[str],
                         inherent_band: str, required_terms: list, gap_review: Optional[str] = None,
                         contract_type: str = "Contract") -> MX.ContractRecord:
    """Write a contract engine result into a first-class ContractRecord (source of truth)."""
    return create_contract(
        s, contract_type=contract_type, vendor_id=vendor_id, engagement_id=engagement_id,
        source="engine",
        data={"tier": inherent_band, "terms_json": json.dumps(required_terms),
              "gap_review": gap_review, "status": "draft"})


def sync_engagement_contract(s: Session, engagement_id: str) -> Optional[MX.ContractRecord]:
    """Consolidate the inline EngagementExt contract fields into a ContractRecord
    (call-off linked to the engagement). One record per engagement is maintained."""
    ext = s.scalars(select(MX.EngagementExt).where(
        MX.EngagementExt.engagement_id == engagement_id)).first()
    if not ext or not ext.contract_reference:
        return None
    existing = s.scalars(select(MX.ContractRecord).where(
        MX.ContractRecord.engagement_id == engagement_id,
        MX.ContractRecord.source == "engagement-sync")).first()
    eng = s.scalars(select(EngagementRecord).where(
        EngagementRecord.engagement_id == engagement_id)).first()
    vendor_id = eng.vendor_id if eng else None
    data = {"title": ext.contract_reference, "governing_law": ext.governing_law,
            "effective_date": ext.effective_date, "renewal_type": ext.renewal_type,
            "notice_period": ext.notice_period, "clause_flags": ext.clause_flags,
            "status": ext.contract_status, "doc_link": ext.contract_doc_link,
            "version": ext.contract_version}
    ctype = ext.agreement_type or "Contract"
    if existing:
        for k, v in data.items():
            if v is not None:
                setattr(existing, k, v)
        existing.contract_type = ctype
        existing.updated_at = datetime.now(timezone.utc)
        s.flush()
        return existing
    row = create_contract(s, contract_type=ctype, vendor_id=vendor_id,
                          engagement_id=engagement_id, data=data, source="engagement-sync")
    return row


def migrate_v1_contracts(s: Session) -> int:
    """Migrate legacy v1 Contract rows (keyed to the integer engagements table)
    into first-class ContractRecord rows. Idempotent: skips already-migrated."""
    from app.features.domain.models_feature import Contract as V1Contract
    try:
        v1s = s.scalars(select(V1Contract)).all()
    except Exception:
        return 0
    migrated = 0
    for c in v1s:
        marker = f"v1:{c.id}"
        exists = s.scalars(select(MX.ContractRecord).where(
            MX.ContractRecord.source == "migrated-v1",
            MX.ContractRecord.doc_link == marker)).first()
        if exists:
            continue
        row = MX.ContractRecord(
            contract_id=_next_contract_id(s), contract_type="Contract",
            engagement_id=None, vendor_id=None, primary_link="engagement",
            tier=c.tier, terms_json=c.terms_json or "{}", gap_review=c.gap_review,
            status="migrated", source="migrated-v1", doc_link=marker)
        s.add(row)
        migrated += 1
    s.flush()
    return migrated


def mark_contracts_critical(s: Session, *, vendor_id: Optional[str] = None,
                            engagement_id: Optional[str] = None) -> int:
    """R3 hook: mark contracts supporting a critical engagement/vendor as critical."""
    q = select(MX.ContractRecord)
    if engagement_id:
        q = q.where(MX.ContractRecord.engagement_id == engagement_id)
    elif vendor_id:
        q = q.where(MX.ContractRecord.vendor_id == vendor_id)
    else:
        return 0
    n = 0
    for row in s.scalars(q).all():
        row.is_critical = True
        n += 1
    s.flush()
    return n


# ============================================================
# REQ 3 — Critical Vendors engine + designation chain
# ============================================================
CRIT_PARAMS = ["customer_impact", "downtime_tolerance",
               "alternative_availability", "substitution_complexity"]
# default weights (sum 1.0); each parameter scored 1-5
CRIT_WEIGHTS = {"customer_impact": 0.35, "downtime_tolerance": 0.25,
                "alternative_availability": 0.20, "substitution_complexity": 0.20}
CRIT_THRESHOLD = 3.5  # weighted score (1-5) at or above which an engagement is critical


def set_criticality_inputs(s: Session, engagement_id: str, data: dict) -> MX.EngagementCriticalityInput:
    row = s.scalars(select(MX.EngagementCriticalityInput).where(
        MX.EngagementCriticalityInput.engagement_id == engagement_id)).first()
    if not row:
        row = MX.EngagementCriticalityInput(engagement_id=engagement_id)
        s.add(row)
    for p in CRIT_PARAMS:
        if p in data and data[p] is not None:
            setattr(row, p, int(data[p]))
    row.updated_at = datetime.now(timezone.utc)
    s.flush()
    return row


def score_engagement_criticality(s: Session, engagement_id: str) -> dict:
    """Deterministic criticality score from the four parameters, blended with the
    engagement's inherent-risk data. Returns score (1-5), critical flag, rationale,
    and a list of gaps where a parameter is unscored (resolved risk-averse).
    Returns {"exists": False} when the engagement does not exist, so callers can 404."""
    eng = s.scalars(select(EngagementRecord).where(
        EngagementRecord.engagement_id == engagement_id)).first()
    if not eng:
        return {"exists": False, "engagement_id": engagement_id}
    inp = s.scalars(select(MX.EngagementCriticalityInput).where(
        MX.EngagementCriticalityInput.engagement_id == engagement_id)).first()
    ext = s.scalars(select(MX.EngagementExt).where(
        MX.EngagementExt.engagement_id == engagement_id)).first()

    scores, gaps = {}, []
    for p in CRIT_PARAMS:
        v = getattr(inp, p, None) if inp else None
        if v is None:
            # gap: resolve risk-averse — assume worst (5) so missing data cannot hide criticality
            gaps.append(p)
            v = 5
        scores[p] = max(1, min(5, v))
    weighted = sum(scores[p] * CRIT_WEIGHTS[p] for p in CRIT_PARAMS)

    # inherent-risk reinforcement: a HIGH inherent engagement floors criticality upward
    inherent = (eng.inherent_band if eng and eng.inherent_band else None)
    mission_critical = bool(ext and ext.mission_critical)
    floor_applied = False
    if inherent == "HIGH" or mission_critical:
        weighted = max(weighted, CRIT_THRESHOLD)
        floor_applied = True

    is_critical = weighted >= CRIT_THRESHOLD
    rationale_parts = [f"{p}={scores[p]}" for p in CRIT_PARAMS]
    rationale = (f"Weighted criticality {round(weighted,2)}/5 ("
                 + ", ".join(rationale_parts) + ")"
                 + (f"; inherent={inherent}" if inherent else "")
                 + ("; mission-critical floor applied" if floor_applied else "")
                 + (f"; GAPS resolved risk-averse: {', '.join(gaps)}" if gaps else ""))
    return {"engagement_id": engagement_id, "score": round(weighted, 2),
            "is_critical": is_critical, "rationale": rationale,
            "gaps": gaps, "parameters": scores}


def designate_engagement(s: Session, engagement_id: str) -> dict:
    """Score and designate one engagement; record a designation row."""
    res = score_engagement_criticality(s, engagement_id)
    s.add(MX.CriticalityDesignation(
        subject_type="engagement", subject_id=engagement_id,
        is_critical=res["is_critical"], score=res["score"],
        rationale=res["rationale"], auto=True))
    # mark supporting contracts critical when the engagement is critical
    if res["is_critical"]:
        mark_contracts_critical(s, engagement_id=engagement_id)
    s.flush()
    return res


def designate_vendor_from_engagements(s: Session, vendor_id: str,
                                      llm_rationale: Optional[str] = None) -> dict:
    """Escalate: a vendor is critical if any of its engagements is critical.
    Sets the authoritative VendorRecord.is_critical flag and records designation."""
    engs = s.scalars(select(EngagementRecord).where(
        EngagementRecord.vendor_id == vendor_id)).all()
    eng_results = [score_engagement_criticality(s, e.engagement_id) for e in engs]
    critical_engs = [r for r in eng_results if r["is_critical"]]
    is_critical = len(critical_engs) > 0
    top = max((r["score"] for r in eng_results), default=0)
    rationale = (f"{len(critical_engs)} of {len(eng_results)} engagement(s) critical; "
                 f"max engagement criticality {top}/5")
    if llm_rationale:
        rationale += f". {llm_rationale}"

    # check for a manual override before auto-setting
    override = s.scalars(select(MX.CriticalityDesignation).where(
        MX.CriticalityDesignation.subject_type == "vendor",
        MX.CriticalityDesignation.subject_id == vendor_id,
        MX.CriticalityDesignation.auto == False)  # noqa: E712
        .order_by(MX.CriticalityDesignation.id.desc())).first()

    v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
    if v and not override:
        v.is_critical = is_critical
        v.criticality_reason = rationale
    if not override:
        s.add(MX.CriticalityDesignation(
            subject_type="vendor", subject_id=vendor_id, is_critical=is_critical,
            score=top, rationale=rationale, auto=True))
    # propagate critical mark to vendor-level (MSA) contracts
    if is_critical:
        mark_contracts_critical(s, vendor_id=vendor_id)
    s.flush()
    return {"vendor_id": vendor_id, "is_critical": (override.is_critical if override else is_critical),
            "score": top, "rationale": rationale,
            "critical_engagements": [r["engagement_id"] for r in critical_engs],
            "override_in_effect": bool(override)}


def override_vendor_criticality(s: Session, vendor_id: str, is_critical: bool,
                                reason: str, user: str) -> dict:
    """Manual override of the authoritative flag, recorded and respected by the engine."""
    v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
    if v:
        v.is_critical = is_critical
        v.criticality_reason = f"[manual override by {user}] {reason}"
    s.add(MX.CriticalityDesignation(
        subject_type="vendor", subject_id=vendor_id, is_critical=is_critical,
        rationale=f"[override] {reason}", auto=False, overridden_by=user))
    s.flush()
    return {"vendor_id": vendor_id, "is_critical": is_critical, "override": True}


def override_engagement_criticality(s: Session, engagement_id: str, is_critical: bool,
                                    reason: str, user: str) -> dict:
    """CR-9: manual override of an engagement's criticality, recorded as a designation.
    Escalates to the vendor so the authoritative vendor flag stays consistent."""
    eng = s.scalars(select(EngagementRecord).where(
        EngagementRecord.engagement_id == engagement_id)).first()
    if not eng:
        return {"exists": False}
    s.add(MX.CriticalityDesignation(
        subject_type="engagement", subject_id=engagement_id, is_critical=is_critical,
        rationale=f"[override by {user}] {reason}", auto=False, overridden_by=user))
    s.flush()
    designate_vendor_from_engagements(s, eng.vendor_id)
    if is_critical:
        mark_contracts_critical(s, engagement_id=engagement_id)
    s.flush()
    return {"engagement_id": engagement_id, "is_critical": is_critical, "override": True}


def run_critical_analysis(s: Session, vendor_id: Optional[str] = None) -> dict:
    """Run the full chain. If vendor_id given, scope to that vendor; else all vendors
    that have engagements. Designates engagements -> vendors -> contracts."""
    if vendor_id:
        vendors = [vendor_id]
    else:
        vendors = list({e.vendor_id for e in s.scalars(select(EngagementRecord)).all()})
    out = []
    for vid in vendors:
        engs = s.scalars(select(EngagementRecord).where(
            EngagementRecord.vendor_id == vid)).all()
        for e in engs:
            designate_engagement(s, e.engagement_id)
        res = designate_vendor_from_engagements(s, vid)
        out.append(res)
    s.flush()
    return {"analysed": len(vendors),
            "critical_vendors": [r["vendor_id"] for r in out if r["is_critical"]],
            "results": out}


def list_critical(s: Session) -> dict:
    """Current critical engagements and vendors (latest designation each)."""
    desigs = s.scalars(select(MX.CriticalityDesignation)
                       .order_by(MX.CriticalityDesignation.id.desc())).all()
    seen, eng_crit, ven_crit = set(), [], []
    for d in desigs:
        key = (d.subject_type, d.subject_id)
        if key in seen:
            continue
        seen.add(key)
        if d.is_critical:
            (eng_crit if d.subject_type == "engagement" else ven_crit).append(
                {"id": d.subject_id, "score": d.score, "rationale": d.rationale,
                 "auto": d.auto})
    return {"critical_engagements": eng_crit, "critical_vendors": ven_crit}


def _is_critical_vendor(s: Session, vendor_id: str) -> bool:
    v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
    return bool(v and v.is_critical)


# ============================================================
# REQ 4 — Vendor Performance Management service
# ============================================================
# default dimension weights (percent, sum 100) and KPI library
PERF_DIMENSIONS = {
    "operational": 30.0,
    "financial_value": 20.0,
    "relationship": 15.0,
    "compliance_risk": 15.0,
    "financial_stability": 15.0,
    "esg": 5.0,
}
DEFAULT_KPIS = {
    "operational": [("On-time delivery", "auto"), ("SLA attainment", "auto"),
                    ("Quality / defect rate", "manual"), ("Responsiveness", "manual")],
    "financial_value": [("Cost savings", "manual"), ("Billing accuracy", "manual"),
                        ("Pricing adherence", "manual")],
    "relationship": [("Responsiveness", "manual"), ("Proactivity", "manual"),
                     ("Governance participation", "manual")],
    "compliance_risk": [("Contractual adherence", "auto"), ("Certification status", "auto"),
                        ("Audit findings", "auto")],
    "financial_stability": [("Financial health band", "auto"), ("Credit rating", "auto")],
    "esg": [("ESG rating", "auto"), ("Environmental certification", "manual")],
}
PERF_BANDS = [(4.0, "Strong"), (3.0, "Adequate"), (2.0, "Watch"), (0.0, "Underperforming")]


def _band_for(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    for threshold, label in PERF_BANDS:
        if score >= threshold:
            return label
    return "Underperforming"


def enrol_vendor(s: Session, vendor_id: str, *, source: str = "manual",
                 user: Optional[str] = None) -> MX.PerfEnrolment:
    """Enrol a vendor into performance management (idempotent)."""
    row = s.scalars(select(MX.PerfEnrolment).where(
        MX.PerfEnrolment.vendor_id == vendor_id)).first()
    if row:
        if not row.enrolled:
            row.enrolled = True
            row.source = source
            row.enrolled_by = user
        return row
    row = MX.PerfEnrolment(vendor_id=vendor_id, enrolled=True, source=source,
                           enrolled_by=user)
    s.add(row); s.flush()
    return row


def unenrol_vendor(s: Session, vendor_id: str) -> bool:
    row = s.scalars(select(MX.PerfEnrolment).where(
        MX.PerfEnrolment.vendor_id == vendor_id)).first()
    if not row:
        return False
    row.enrolled = False
    s.flush()
    return True


def list_perf_enrolment(s: Session) -> list[dict]:
    """Enrolled vendors, auto-including any critical vendor not yet enrolled."""
    for v in s.scalars(select(VendorRecord).where(VendorRecord.is_critical == True)).all():  # noqa: E712
        existing = s.scalars(select(MX.PerfEnrolment).where(
            MX.PerfEnrolment.vendor_id == v.vendor_id)).first()
        if not existing:
            s.add(MX.PerfEnrolment(vendor_id=v.vendor_id, enrolled=True, source="auto-critical"))
    s.flush()
    rows = s.scalars(select(MX.PerfEnrolment).where(
        MX.PerfEnrolment.enrolled == True)).all()  # noqa: E712
    out = []
    for r in rows:
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == r.vendor_id)).first()
        if not v:
            continue
        scs = list_scorecards(s, r.vendor_id)
        out.append({"vendor_id": r.vendor_id, "legal_name": v.legal_name,
                    "tier": v.tier, "is_critical": bool(v.is_critical),
                    "source": r.source, "scorecards": len(scs),
                    "latest_band": scs[0]["band"] if scs else None})
    out.sort(key=lambda x: (not x["is_critical"], x["legal_name"] or ""))
    return out


def create_scorecard(s: Session, vendor_id: str, period_label: str, *,
                     period_start: Optional[str] = None, period_end: Optional[str] = None,
                     cadence: str = "quarterly") -> MX.VendorScorecard:
    """Create a scorecard for any enrolled vendor (CR-11: no longer restricted to
    critical vendors), seeded with the default dimension/KPI library."""
    from app.features.domain.registry_service import next_id
    # ensure the vendor is enrolled in performance management (idempotent)
    enrol_vendor(s, vendor_id, source="auto-scorecard")
    # link the contributing critical engagements where any exist (informational)
    crit = list_critical(s)
    engs = s.scalars(select(EngagementRecord).where(
        EngagementRecord.vendor_id == vendor_id)).all()
    crit_eng_ids = {x["id"] for x in crit["critical_engagements"]}
    contributing = [e.engagement_id for e in engs if e.engagement_id in crit_eng_ids]

    sc = MX.VendorScorecard(
        scorecard_id=next_id(s, "scorecard"), vendor_id=vendor_id,
        period_label=period_label, period_start=period_start, period_end=period_end,
        review_cadence=cadence, status="draft",
        critical_engagements=",".join(contributing))
    s.add(sc); s.flush()
    # seed dimensions + KPIs
    for dim, weight in PERF_DIMENSIONS.items():
        s.add(MX.ScorecardDimension(scorecard_id=sc.scorecard_id, name=dim, weight=weight))
        for metric, src in DEFAULT_KPIS.get(dim, []):
            s.add(MX.ScorecardKPI(scorecard_id=sc.scorecard_id, dimension=dim,
                                  metric=metric, data_source=src, weight=1.0))
    s.flush()
    return sc


def set_kpi_score(s: Session, kpi_id: int, *, actual: Optional[str] = None,
                  score: Optional[int] = None, excluded: Optional[bool] = None,
                  exclude_reason: Optional[str] = None) -> Optional[MX.ScorecardKPI]:
    row = s.get(MX.ScorecardKPI, kpi_id)
    if not row:
        return None
    if actual is not None:
        row.actual = actual
    if score is not None:
        row.score = max(1, min(5, int(score)))
    if excluded is not None:
        row.excluded = excluded
        row.exclude_reason = exclude_reason
    s.flush()
    return row


def auto_source_kpis(s: Session, scorecard_id: str) -> int:
    """Populate auto-sourced KPI values from existing platform data (FR-VPM-041/042/043)."""
    sc = s.scalars(select(MX.VendorScorecard).where(
        MX.VendorScorecard.scorecard_id == scorecard_id)).first()
    if not sc:
        return 0
    vid = sc.vendor_id
    ext = s.scalars(select(MX.VendorMasterExt).where(MX.VendorMasterExt.vendor_id == vid)).first()
    # operational: SLA attainment from engagement SLAs
    slas = []
    for e in s.scalars(select(EngagementRecord).where(EngagementRecord.vendor_id == vid)).all():
        slas += s.scalars(select(MX.EngagementSLA).where(
            MX.EngagementSLA.engagement_id == e.engagement_id)).all()
    sla_breaches = sum(1 for x in slas if x.breach_flag)
    findings = s.scalars(select(FindingRecord).where(
        FindingRecord.vendor_id == vid, FindingRecord.status != "Closed")).all()
    band_to_score = {"Strong": 5, "Healthy": 5, "Stable": 4, "Adequate": 4,
                     "Watch": 3, "Caution": 3, "Weak": 2, "Distress": 1, "Critical": 1}
    n = 0
    for kpi in s.scalars(select(MX.ScorecardKPI).where(
            MX.ScorecardKPI.scorecard_id == scorecard_id,
            MX.ScorecardKPI.data_source == "auto")).all():
        # non-destructive: never overwrite a value already set (manual or prior auto)
        if kpi.score is not None:
            continue
        val, score = None, None
        if kpi.metric == "SLA attainment":
            val = f"{sla_breaches} breach(es)"
            score = 5 if sla_breaches == 0 else 3 if sla_breaches <= 2 else 1
        elif kpi.metric == "Audit findings":
            val = f"{len(findings)} open"
            score = 5 if not findings else 3 if len(findings) <= 2 else 1
        elif kpi.metric == "Financial health band":
            val = ext.financial_health_band if ext else None
            score = band_to_score.get(val or "", None)
        elif kpi.metric == "Certification status":
            cyber = s.scalars(select(MX.VendorCyber).where(MX.VendorCyber.vendor_id == vid)).first()
            certs = json.loads(cyber.certifications_json) if cyber else []
            val = f"{len(certs)} on file"
            score = 5 if certs else 3
        if val is not None:
            kpi.auto_value = str(val)
            kpi.actual = str(val)
            if score is not None:
                kpi.score = score
            n += 1
    s.flush()
    return n


def compute_scorecard(s: Session, scorecard_id: str) -> dict:
    """Deterministic weighted composite with KPI-exclusion re-normalisation (BR-VPM-02)."""
    sc = s.scalars(select(MX.VendorScorecard).where(
        MX.VendorScorecard.scorecard_id == scorecard_id)).first()
    if not sc:
        return {}
    dims = s.scalars(select(MX.ScorecardDimension).where(
        MX.ScorecardDimension.scorecard_id == scorecard_id,
        MX.ScorecardDimension.active == True)).all()  # noqa: E712
    dim_scores = {}
    for d in dims:
        kpis = s.scalars(select(MX.ScorecardKPI).where(
            MX.ScorecardKPI.scorecard_id == scorecard_id,
            MX.ScorecardKPI.dimension == d.name,
            MX.ScorecardKPI.excluded == False)).all()  # noqa: E712
        scored = [(k.score, k.weight) for k in kpis if k.score is not None]
        if scored:
            wsum = sum(w for _, w in scored)
            d.score = round(sum(sc_ * w for sc_, w in scored) / wsum, 2) if wsum else None
        else:
            d.score = None
        dim_scores[d.name] = (d.score, d.weight)
    # composite: re-normalise weights over dimensions that have a score
    scored_dims = {k: v for k, v in dim_scores.items() if v[0] is not None}
    wsum = sum(w for _, w in scored_dims.values())
    composite = (round(sum(sc_ * w for sc_, w in scored_dims.values()) / wsum, 2)
                 if wsum else None)
    sc.composite_score = composite
    sc.band = _band_for(composite)
    sc.updated_at = datetime.now(timezone.utc)
    s.flush()
    return {"scorecard_id": scorecard_id, "composite_score": composite, "band": sc.band,
            "dimensions": {k: v[0] for k, v in dim_scores.items()}}


def agree_scorecard(s: Session, scorecard_id: str, party: str) -> Optional[MX.VendorScorecard]:
    sc = s.scalars(select(MX.VendorScorecard).where(
        MX.VendorScorecard.scorecard_id == scorecard_id)).first()
    if not sc:
        return None
    sc.agreed_with_vendor = True
    sc.agreed_party = party
    sc.agreed_date = _today()
    sc.status = "agreed"
    s.flush()
    return sc


def publish_scorecard(s: Session, scorecard_id: str, user: str) -> dict:
    """Publish: compute, then roll the result into the consolidated risk profile
    WITHOUT altering inherent/residual (FR-VPM-080/081, BR-VPM-06)."""
    res = compute_scorecard(s, scorecard_id)
    sc = s.scalars(select(MX.VendorScorecard).where(
        MX.VendorScorecard.scorecard_id == scorecard_id)).first()
    if not sc:
        return {}
    sc.published = True
    sc.published_by = user
    sc.published_at = _today()
    sc.status = "published"
    # ensure the authoritative risk snapshot is current before layering performance on top
    refresh_risk_profile(s, sc.vendor_id)
    # rollup into the latest risk profile snapshot (performance fields only)
    slas = []
    for e in s.scalars(select(EngagementRecord).where(
            EngagementRecord.vendor_id == sc.vendor_id)).all():
        slas += s.scalars(select(MX.EngagementSLA).where(
            MX.EngagementSLA.engagement_id == e.engagement_id)).all()
    breaches = sum(1 for x in slas if x.breach_flag)
    rp = MX.VendorRiskProfile(
        vendor_id=sc.vendor_id,
        sla_summary=f"{len(slas)-breaches}/{len(slas)} SLAs met" if slas else "no SLAs tracked",
        incident_count=breaches,
        performance_score=sc.composite_score,
        review_cadence=sc.review_cadence,
        last_review=_today())
    s.add(rp)
    s.flush()
    return {"scorecard_id": scorecard_id, "published": True,
            "composite_score": sc.composite_score, "band": sc.band,
            "rolled_into_profile": True}


def get_scorecard(s: Session, scorecard_id: str) -> dict:
    sc = s.scalars(select(MX.VendorScorecard).where(
        MX.VendorScorecard.scorecard_id == scorecard_id)).first()
    if not sc:
        return {}
    dims = s.scalars(select(MX.ScorecardDimension).where(
        MX.ScorecardDimension.scorecard_id == scorecard_id)).all()
    kpis = s.scalars(select(MX.ScorecardKPI).where(
        MX.ScorecardKPI.scorecard_id == scorecard_id)).all()
    return {
        "scorecard_id": sc.scorecard_id, "vendor_id": sc.vendor_id,
        "period_label": sc.period_label, "status": sc.status,
        "composite_score": sc.composite_score, "band": sc.band,
        "review_cadence": sc.review_cadence, "agreed_with_vendor": sc.agreed_with_vendor,
        "published": sc.published, "critical_engagements": sc.critical_engagements,
        "dimensions": [{"name": d.name, "weight": d.weight, "score": d.score} for d in dims],
        "kpis": [{"id": k.id, "dimension": k.dimension, "metric": k.metric,
                  "target": k.target, "data_source": k.data_source, "actual": k.actual,
                  "auto_value": k.auto_value, "score": k.score, "excluded": k.excluded}
                 for k in kpis],
    }


def list_scorecards(s: Session, vendor_id: str) -> list[dict]:
    rows = s.scalars(select(MX.VendorScorecard).where(
        MX.VendorScorecard.vendor_id == vendor_id)
        .order_by(MX.VendorScorecard.id.desc())).all()
    return [{"scorecard_id": r.scorecard_id, "period_label": r.period_label,
             "status": r.status, "composite_score": r.composite_score, "band": r.band,
             "published": r.published} for r in rows]


def create_review(s: Session, vendor_id: str, data: dict) -> MX.PerformanceReview:
    from app.features.domain.registry_service import next_id
    row = MX.PerformanceReview(review_id=next_id(s, "review"), vendor_id=vendor_id)
    for k in ("scorecard_id", "review_date", "cadence", "attendees", "summary",
              "outcomes", "next_review_date"):
        if k in data and data[k] is not None:
            setattr(row, k, data[k])
    row.review_date = row.review_date or _today()
    s.add(row); s.flush()
    return row


def acknowledge_review(s: Session, review_id: str) -> Optional[MX.PerformanceReview]:
    row = s.scalars(select(MX.PerformanceReview).where(
        MX.PerformanceReview.review_id == review_id)).first()
    if not row:
        return None
    row.vendor_acknowledged = True
    row.vendor_ack_date = _today()
    s.flush()
    return row


def raise_performance_capa(s: Session, vendor_id: str, scorecard_id: str,
                           gap: str, owner: str, due_date: Optional[str] = None) -> dict:
    """Closed-loop corrective action on the existing RemediationRecord (FR-VPM-064),
    tagged to the scorecard, requiring verification of effectiveness before closure.
    A performance finding is raised first so the remediation has a parent finding."""
    from app.features.domain.registry_service import next_id
    fid = next_id(s, "finding")
    s.add(FindingRecord(
        finding_id=fid, vendor_id=vendor_id,
        title=f"[PERF {scorecard_id}] {gap}", severity="Medium",
        status="Open", source="performance", domain="performance"))
    rid = next_id(s, "remediation")
    rec = RemediationRecord(
        remediation_id=rid, finding_id=fid,
        plan=f"[PERF {scorecard_id}] Address: {gap}", owner=owner,
        target_date=due_date, status="Planned")
    s.add(rec); s.flush()
    return {"remediation_id": rid, "finding_id": fid, "status": "Planned",
            "note": "verification of sustained effectiveness required before closure (status->Verified)"}


def verify_performance_capa(s: Session, remediation_id: str, user: str,
                            evidence: str) -> Optional[dict]:
    """Close the loop: a CAPA cannot be closed without verification of effectiveness
    (BR-VPM-05). Sets status to Verified with evidence and verifier."""
    rec = s.scalars(select(RemediationRecord).where(
        RemediationRecord.remediation_id == remediation_id)).first()
    if not rec:
        return None
    rec.status = "Verified"
    rec.verified_by = user
    rec.evidence = evidence
    rec.completed_date = _today()
    rec.progress_pct = 100
    s.flush()
    return {"remediation_id": remediation_id, "status": "Verified", "verified_by": user}


# ============================================================
# REQ 5 — ProAssess: autonomous end-to-end assessment
# ============================================================
# Domain coverage proportionate to inherent rating (FR: minimal relevant info per IRR).
# Each tier lists the domains ProAssess will assess; domains NOT listed at a tier are
# "correctly omitted" (not gaps). Missing data WITHIN an in-scope domain IS a gap.
PROASSESS_SCOPE = {
    "LOW":      ["infosec", "compliance"],
    "MODERATE": ["infosec", "privacy", "compliance", "resilience"],
    "ELEVATED": ["infosec", "privacy", "compliance", "resilience", "financial", "reputation"],
    "HIGH":     ["infosec", "privacy", "compliance", "resilience", "financial",
                 "reputation", "esg", "physical", "org", "fourth_party"],
}
# monitoring cadence calibrated to inherent rating
MONITOR_CADENCE = {"LOW": "annual", "MODERATE": "semi-annual",
                   "ELEVATED": "quarterly", "HIGH": "monthly"}


def _proassess_inherent(irq: dict) -> dict:
    """Deterministic inherent computation via the existing engine."""
    from app.features.assessment.bro_engine import compute_inherent
    return compute_inherent(irq or {})


def run_proassess(s: Session, *, vendor_id: Optional[str], engagement_id: Optional[str],
                  irq: Optional[dict] = None, documents: Optional[list] = None,
                  ddq: Optional[dict] = None, extracted: Optional[dict] = None,
                  deep: bool = False) -> dict:
    """Autonomous assessment. Deterministic engines are authoritative; any LLM
    extraction is passed in via `extracted`/`irq`/`ddq` (two-layer design).
    No questions, no assumptions: unestablished facts become GAPS resolved in the
    most risk-averse direction. Processing is proportionate to the inherent rating."""
    documents = documents or []
    irq = dict(irq or {})
    gaps = []

    # ---------- Layer 1: inherent (authoritative, deterministic) ----------
    inh = _proassess_inherent(irq)
    inherent_band = inh.get("band", "MODERATE")
    in_scope = PROASSESS_SCOPE.get(inherent_band, PROASSESS_SCOPE["HIGH"])

    # ---------- proportionate domain processing ----------
    domain_findings = {}
    risk_items = []
    inh_domains = inh.get("domains", {})
    for dom in in_scope:
        if dom in inh_domains:
            score = inh_domains[dom]
            domain_findings[dom] = {"inherent_score": score}
            if score >= 3:
                risk_items.append({"domain": dom, "severity": "High",
                                   "note": f"Elevated inherent exposure in {dom} (score {score}/4)"})
        elif dom in ("financial", "reputation", "fourth_party"):
            # these are assessed by dedicated engines, handled below
            pass
        else:
            # in-scope domain with no inherent data = GAP, resolved risk-averse (treat as worst)
            gaps.append({"domain": dom, "issue": "no inherent data supplied",
                         "resolution": "scored worst-case (4/4) pending evidence"})
            domain_findings[dom] = {"inherent_score": 4, "gap": True}
            risk_items.append({"domain": dom, "severity": "High",
                               "note": f"GAP in {dom}: absent evidence treated as worst-case"})

    # ---------- financial (if in scope) ----------
    financial_result = None
    if "financial" in in_scope:
        figs = (extracted or {}).get("financials")
        if figs:
            from app.features.intelligence.financial import assess_financials
            financial_result = assess_financials(figs, (extracted or {}).get("flags") or {})
            domain_findings["financial"] = {"banding": financial_result["banding"],
                                            "altman_zone": financial_result["altman"]["zone"]}
            if financial_result["banding"] in ("Weak", "Distress", "Caution"):
                risk_items.append({"domain": "financial", "severity": "High",
                                   "note": f"Financial health: {financial_result['banding']}"})
        else:
            gaps.append({"domain": "financial", "issue": "no financial statements supplied",
                         "resolution": "financial health treated as adverse pending evidence"})
            domain_findings["financial"] = {"banding": "Unknown (worst-case)", "gap": True}
            risk_items.append({"domain": "financial", "severity": "High",
                               "note": "GAP: no financials; treated as adverse"})

    # ---------- reputation (if in scope) ----------
    reputation_result = None
    if "reputation" in in_scope:
        events = (extracted or {}).get("reputation_events")
        if events is not None:
            from app.features.intelligence.reputation import assess_reputation
            reputation_result = assess_reputation(events, True)
            domain_findings["reputation"] = {"verdict": reputation_result["verdict"],
                                             "overall": reputation_result["overall"]}
        else:
            gaps.append({"domain": "reputation", "issue": "no reputation/adverse-media data supplied",
                         "resolution": "reputation treated as adverse pending screening"})
            domain_findings["reputation"] = {"verdict": "Unknown (worst-case)", "gap": True}
            risk_items.append({"domain": "reputation", "severity": "Medium",
                               "note": "GAP: no reputation data; treated as adverse"})

    # ---------- Layer 1: residual (authoritative, deterministic) ----------
    if ddq:
        from app.features.assessment.bro_engine import compute_residual
        residual = compute_residual(inherent_band, ddq)
        residual_band = residual["band"]
    else:
        # no control evidence = cannot mitigate inherent: residual defaults to inherent (risk-averse)
        residual_band = inherent_band
        gaps.append({"domain": "controls", "issue": "no DDQ / control evidence supplied",
                     "resolution": "residual set equal to inherent (no mitigation credited)"})

    # ---------- approval recommendation (conservative) ----------
    if gaps or residual_band == "HIGH":
        recommendation = "Approve with conditions" if residual_band != "HIGH" else "Do not approve pending evidence"
    else:
        recommendation = "Approve"

    # Watchlist: captured and explained in the assessment output. A watchlisted
    # supplier forces human sign-off irrespective of the computed band.
    watchlist_info = {"watchlisted": False, "entries": []}
    if vendor_id:
        try:
            from app.features.domain import watchlist_service as _WL
            if _WL.is_watchlisted(s, vendor_id):
                watchlist_info = {
                    "watchlisted": True,
                    "entries": _WL.entries_for_vendor(s, vendor_id, status="Active"),
                    "explanation": ("This supplier is on the watchlist. Per policy, any engagement "
                                    "with a watchlisted supplier requires human sign-off irrespective "
                                    "of the assessed risk level; the AI assessment is advisory only "
                                    "and cannot auto-approve."),
                }
        except Exception:
            pass
    return {
        "vendor_id": vendor_id, "engagement_id": engagement_id,
        "inherent_band": inherent_band, "residual_band": residual_band,
        "inherent_detail": inh, "domains_in_scope": in_scope,
        "domain_findings": domain_findings,
        "financial": financial_result, "reputation": reputation_result,
        "risks": risk_items, "gaps": gaps,
        "gap_count": len(gaps), "recommendation": recommendation,
        "documents_considered": len(documents),
        "watchlist": watchlist_info,
        "monitoring_cadence": MONITOR_CADENCE.get(inherent_band, "quarterly"),
        "proportionality_note": (f"Inherent {inherent_band}: {len(in_scope)} domain(s) in scope; "
                                 "domains outside scope correctly omitted (not gaps)."),
    }


def _find_duplicate_vendor(s: Session, name: str):
    """CR-4: detect a likely-existing vendor by normalised legal name to avoid
    minting phantom duplicates from free-text input."""
    if not name:
        return None
    norm = re.sub(r"[^a-z0-9]", "", name.lower())
    norm = re.sub(r"(ltd|limited|inc|llc|plc|gmbh|sa|bv|corp|co)$", "", norm)
    for v in s.scalars(select(VendorRecord)).all():
        vn = re.sub(r"[^a-z0-9]", "", (v.legal_name or "").lower())
        vn = re.sub(r"(ltd|limited|inc|llc|plc|gmbh|sa|bv|corp|co)$", "", vn)
        if vn and norm and (vn == norm or vn in norm or norm in vn):
            return v
    return None


def _proassess_ai(free_text: str, doc_texts: list, methodology: str,
                  rubric_override: Optional[str] = None, deep: bool = False) -> Optional[dict]:
    """Totally AI-managed analysis: Claude follows the methodology strictly, reads the
    engagement description + document text, and returns the full structured assessment.
    Returns None if the live model is unavailable or the output can't be parsed."""
    from app.agents import llm_config
    import json as _json
    if not llm_config.status().get("live_ready"):
        return None
    from app.features.assessment.ai_json import wrap_untrusted, UNTRUSTED_PREAMBLE, parse_json_strict
    corpus = "\n\n".join(
        [t for t in [free_text or ""] if t]
        + [wrap_untrusted(t) for t in (doc_texts or []) if t]).strip()
    corpus = corpus[:24000] if corpus else "(no description or documents supplied)"
    rubric = rubric_override or (
        "You are BRO ProAssess — an autonomous third-party risk assessor. Conduct the FULL "
        "inherent-then-residual assessment from the supplied engagement description and document "
        "text, COMPLYING STRICTLY with the methodology above; where the methodology is silent, "
        "follow recognised industry best practice. Score inherent exposure across the eight "
        "domains (infosec, privacy, resilience, compliance, physical, org, reputation, esg) each "
        "0-4; weights InfoSec 30 / Privacy 20 / Resilience 15 / Compliance 10 / Physical 10 / "
        "Org 5 / Reputation 5 / ESG 5; bands HIGH/ELEVATED/MODERATE/LOW. Residual = inherent "
        "reduced only by EVIDENCED controls; a marginal critical control floors residual at HIGH. "
        "Make NO unjustified assumptions: any material fact you cannot establish becomes a GAP, "
        "resolved in the most risk-averse direction. Decision maps residual: HIGH=DO NOT PROCEED, "
        "ELEVATED=ESCALATE, MODERATE=APPROVE WITH CONDITIONS, LOW=APPROVE. "
        "Return ONLY a JSON object (no prose, no code fences) with this exact shape: "
        '{"irq":{"service":str,"data":[str],"criticality":str,"cross_border":bool,"regulated":bool},'
        '"inherent_band":"HIGH|ELEVATED|MODERATE|LOW","domains":{"infosec":0,"privacy":0,'
        '"resilience":0,"compliance":0,"physical":0,"org":0,"reputation":0,"esg":0},'
        '"residual_band":"HIGH|ELEVATED|MODERATE|LOW","risks":[{"domain":str,"severity":'
        '"High|Medium|Low","note":str}],"gaps":[{"domain":str,"issue":str,"resolution":str}],'
        '"recommendation":str,"decision":str,"rationale":str}.')
    system = (methodology + "\n\n" + rubric) if methodology else rubric
    system = UNTRUSTED_PREAMBLE + "\n\n" + system
    text = llm_config.complete(system, "ENGAGEMENT & EVIDENCE:\n" + corpus,
                               domain="bro", max_tokens=4096,
                               review=bool(deep), timeout_s=(180 if deep else 90))
    if not text:
        return None  # llm_config.last_error() already set with the reason
    ai = parse_json_strict(
        text, required_keys=("inherent_band", "residual_band"),
        retry_fn=lambda fix: llm_config.complete(
            system, fix + "\n\nORIGINAL REPLY:\n" + text[:6000],
            domain="bro", max_tokens=4096))
    if ai is None:
        llm_config._LAST_ERROR = (
            "model did not return valid JSON with the required keys (after one repair "
            f"attempt); received {len(text)} chars. First 160: {text.strip()[:160]!r}")
        return None
    bands = {"HIGH", "ELEVATED", "MODERATE", "LOW"}
    inh = str(ai.get("inherent_band", "")).upper()
    res = str(ai.get("residual_band", "")).upper()
    if inh not in bands:
        inh = "MODERATE"
    if res not in bands:
        res = inh
    gaps = ai.get("gaps") or []
    risks = ai.get("risks") or []
    return {
        "engine": "ai", "inherent_band": inh, "residual_band": res,
        "domains": ai.get("domains") or {}, "risks": risks, "gaps": gaps,
        "gap_count": len(gaps),
        "recommendation": ai.get("recommendation") or ai.get("decision") or "Review required",
        "decision": ai.get("decision") or ai.get("recommendation") or "",
        "rationale": ai.get("rationale") or "",
        "extracted_irq": ai.get("irq") or {},
        "scope_summary": f"{inh} inherent → {res} residual (AI-managed, methodology-bound).",
    }


def run_proassess_autonomous(s: Session, *, free_text: str = "", documents: Optional[list] = None,
                             vendor_id: Optional[str] = None, new_vendor_name: Optional[str] = None,
                             engagement_title: Optional[str] = None, ddq: Optional[dict] = None,
                             user: str = "system", create_records: bool = True, deep: bool = False) -> dict:
    """CR-4: end-to-end ProAssess from a SINGLE free-text box + uploaded documents,
    for NEW or existing vendors. Extracts IRQ signals from text + documents (deterministic
    layer), runs the authoritative assessment (existing run_proassess logic, unchanged),
    and — when create_records — autonomously creates vendor / engagement / assessment /
    artefact records across the databases, audited, assigning `user` as owner so the
    access-control rule (CR-3) applies. New-vendor creation is guarded by a duplicate check."""
    from app.features.lifecycle import documents as DOC
    from app.features.domain.registry_service import create_vendor, create_engagement
    documents = documents or []
    tables_written = []
    notes = []

    created_vendor = False
    dup = None
    if not vendor_id:
        if not new_vendor_name:
            return {"error": "provide either vendor_id or new_vendor_name"}
        dup = _find_duplicate_vendor(s, new_vendor_name)
        if dup:
            vendor_id = dup.vendor_id
            notes.append(f"matched existing vendor {vendor_id} (no duplicate created)")
        elif create_records:
            v = create_vendor(s, legal_name=new_vendor_name)
            vendor_id = v.vendor_id
            created_vendor = True
            tables_written.append(f"vendor:{vendor_id}")

    doc_texts = [free_text or ""]
    stored_docs = []
    for d in documents:
        try:
            row = DOC.store_document(s, filename=d.get("filename", "document"),
                                     content_type=d.get("content_type", ""),
                                     data_b64=d.get("data_b64", ""), vendor_id=vendor_id,
                                     uploaded_by=user, purpose="proassess")
            stored_docs.append(row)
            doc_texts.append(DOC._decode_text(row))
            tables_written.append(f"document:{row.doc_id}")
        except ValueError:
            notes.append(f"document '{d.get('filename')}' rejected (size/type)")
    irq = DOC.extract_proassess_signals(s, doc_texts)

    engagement_id = None
    if vendor_id and create_records:
        eng = create_engagement(s, vendor_id=vendor_id,
                                 title=engagement_title or "ProAssess engagement")
        engagement_id = eng.engagement_id
        tables_written.append(f"engagement:{engagement_id}")

    # ---- TOTALLY AI-MANAGED: Claude conducts the assessment per the methodology ----
    from app.features.assessment import methodology as _M
    from app.agents import llm_config as _LLM
    from app.features.assessment import prompts as _PROMPTS
    ai = _proassess_ai(free_text, doc_texts, _M.methodology_directive(s),
                       _PROMPTS.resolve(s, "assessment_rubric"), deep=deep)
    if ai:
        report = ai
        report["vendor_id"] = vendor_id
        report["engagement_id"] = engagement_id
        notes.append("assessment conducted by AI engine under the methodology")
    elif _LLM.status().get("live_ready"):
        # AI is connected but the call FAILED — be honest; do NOT substitute a
        # deterministic result (ProAssess is AI-managed). Surface the reason.
        return {"available": False, "holding": True, "engine": "ai_failed",
                "vendor_id": vendor_id, "engagement_id": engagement_id,
                "ai_error": _LLM.last_error(),
                "message": ("ProAssess is AI-managed and the AI engine is connected, but the "
                            "assessment call did not complete: "
                            + (_LLM.last_error() or "unknown error")
                            + ". No deterministic result has been substituted. Check the AI "
                              "provider/key/model in Settings → AI and retry.")}
    else:
        # AI not configured (internal/test callers) — deterministic engine.
        report = run_proassess(s, vendor_id=vendor_id, engagement_id=engagement_id,
                               irq=irq, ddq=ddq, documents=documents, deep=deep)
    report["free_text_considered"] = bool(free_text)
    report["extracted_irq"] = report.get("extracted_irq") or irq
    report["created_vendor"] = created_vendor
    report["duplicate_matched"] = bool(dup)

    if create_records and vendor_id and engagement_id:
        from app.features.domain.registry_service import create_assessment, create_artefact
        import json as _json
        rec = create_assessment(s, engagement_id=engagement_id, vendor_id=vendor_id,
                                engagement_owner=user,
                                inherent_band=report.get("inherent_band"),
                                residual_band=report.get("residual_band"))
        rec.status = "Completed"
        rec.structured_json = _json.dumps({"source": "proassess", "extracted_irq": irq,
                                           "risks": report.get("risks", []),
                                           "gaps": report.get("gaps", []),
                                           "recommendation": report.get("recommendation"),
                                           "verdict": report.get("recommendation")})
        tables_written.append(f"assessment:{rec.assessment_id}")
        report["assessment_id"] = rec.assessment_id
        eng = s.scalars(select(EngagementRecord).where(
            EngagementRecord.engagement_id == engagement_id)).first()
        if eng:
            eng.inherent_band = report.get("inherent_band")
            eng.residual_band = report.get("residual_band")
        for row in stored_docs:
            ext = DOC.extract_certificate(s, row)
            art = create_artefact(s, vendor_id=vendor_id, name=ext["name"],
                                  artefact_type=ext["artefact_type"],
                                  expiry_date=ext.get("expiry_date"), received_via="proassess",
                                  issue_date=ext.get("issue_date"), engagement_id=engagement_id,
                                  object_uri=f"/api/v2/documents/{row.doc_id}")
            tables_written.append(f"artefact:{art.artefact_id}")
        register_proassess(s, report, user)
        tables_written.append("risk_profile")
        # File the AI assessment as a retrievable report in the AI Reports folder,
        # tagged to the vendor (so it surfaces in AI Reports, Documents and Vendor 360).
        if report.get("engine") == "ai":
            try:
                import base64 as _b64
                payload = _b64.b64encode(_json.dumps({
                    "type": "ProAssess", "vendor_id": vendor_id, "engagement_id": engagement_id,
                    "inherent_band": report.get("inherent_band"), "residual_band": report.get("residual_band"),
                    "recommendation": report.get("recommendation"), "decision": report.get("decision"),
                    "rationale": report.get("rationale"), "risks": report.get("risks", []),
                    "gaps": report.get("gaps", []), "extracted_irq": report.get("extracted_irq", {}),
                    "summary": report.get("rationale") or report.get("recommendation"),
                }, indent=2).encode()).decode()
                doc = DOC.store_document(
                    s, filename=f"proassess_report_{(report.get('legal_name') or vendor_id or 'entity')}.json"[:80],
                    content_type="application/json", data_b64=payload,
                    vendor_id=vendor_id, engagement_id=engagement_id,
                    uploaded_by=user, purpose="proassess_report")
                report["filed_report"] = doc.doc_id
                tables_written.append(f"proassess_report:{doc.doc_id}")
            except Exception as _e:
                _obs_swallow('master_service.py', _e)
        # AI auto-creates findings from the assessment's risks and gaps,
        # linked to the assessment, engagement and vendor.
        try:
            from app.features.domain.registry_service import create_finding as _mk_finding
            _sevmap = {"high": "High", "medium": "Medium", "low": "Low",
                       "critical": "Critical"}
            made = []
            for r in (report.get("risks") or []):
                sev = _sevmap.get(str(r.get("severity", "")).lower(), "Medium")
                ttl = (r.get("note") or r.get("detail") or
                       f"{(r.get('domain') or 'Risk').title()} risk").strip()[:140]
                fr = _mk_finding(s, title=ttl, severity=sev, source="AI",
                                 description=r.get("note") or r.get("detail"),
                                 domain=r.get("domain"), engagement_id=engagement_id,
                                 vendor_id=vendor_id, assessment_id=rec.assessment_id,
                                 raised_by="ProAssess", status="Draft")
                made.append(fr.finding_id)
            for g in (report.get("gaps") or []):
                ttl = (g.get("issue") or f"{(g.get('domain') or 'Control').title()} gap").strip()[:140]
                fr = _mk_finding(s, title=ttl, severity="Medium", source="AI",
                                 description=g.get("issue"), domain=g.get("domain"),
                                 engagement_id=engagement_id, vendor_id=vendor_id,
                                 assessment_id=rec.assessment_id, raised_by="ProAssess",
                                 status="Draft", suggested_remediation=g.get("resolution"))
                made.append(fr.finding_id)
            if made:
                report["findings_created"] = made
                tables_written.append(f"findings:{len(made)}")
        except Exception as _e:
            _obs_swallow('master_service.py', _e)
        s.flush()

    report["tables_written"] = tables_written
    report["notes"] = notes
    report["registered"] = bool(create_records and vendor_id and engagement_id)
    return report


def register_proassess(s: Session, report: dict, user: str) -> dict:
    """Register action: non-destructive merge across all tables that exist, advisory
    (not self-executing), permission-gated, audited. Empanels for monitoring on completion."""
    vid = report.get("vendor_id")
    eid = report.get("engagement_id")
    written = []
    if not _vendor_exists(s, vid):
        return {"registered": False, "reason": "vendor must be registered before ProAssess can register results"}

    # 1) assessment record (authoritative bands)
    from app.features.domain.registry_service import create_assessment
    if eid:
        rec = create_assessment(s, engagement_id=eid, vendor_id=vid,
                                engagement_owner=user,
                                inherent_band=report.get("inherent_band"),
                                residual_band=report.get("residual_band"))
        written.append(f"assessment:{rec.assessment_id}")

    # 2) FDD band -> vendor master (non-destructive: only if engine produced one)
    if report.get("financial") and report["financial"].get("banding"):
        ext = _get_or_create(s, MX.VendorMasterExt, vid)
        if not ext.financial_health_band:
            ext.financial_health_band = report["financial"]["banding"]
            written.append("vendor_master.financial_health_band")

    # 3) reputation -> monitor signal + profile
    if report.get("reputation"):
        _rep = report["reputation"] if isinstance(report["reputation"], dict) else {}
        persist_reputation(s, vid, {"verdict": _rep.get("verdict", "Unknown"),
                                    "overall": _rep.get("overall", _rep.get("verdict", ""))})
        written.append("reputation_signal")

    # 4) risks -> findings (only those not already present by title)
    for r in report.get("risks", []):
        from app.features.domain.registry_service import next_id
        # AI output shape can drift ('note' vs 'detail'/'issue'); never crash the run.
        if not isinstance(r, dict):
            r = {"note": str(r)}
        _note = (r.get("note") or r.get("detail") or r.get("issue")
                 or r.get("summary") or "Risk identified")
        title = f"[ProAssess] {_note}"
        exists = s.scalars(select(FindingRecord).where(
            FindingRecord.vendor_id == vid, FindingRecord.title == title)).first()
        if not exists:
            s.add(FindingRecord(finding_id=next_id(s, "finding"), vendor_id=vid,
                                engagement_id=eid, title=title, severity=r.get("severity", "Medium"),
                                status="Open", source="ProAssess", domain=r.get("domain")))
            written.append("finding")

    # 5) refresh consolidated risk profile
    refresh_risk_profile(s, vid)
    written.append("risk_profile")

    # 6) empanel for automated monitoring if not already (FR: empanel on completion)
    from app.features.domain.registry_models import FinMonitorRecord
    mon = s.scalars(select(FinMonitorRecord).where(
        FinMonitorRecord.vendor_id == vid)).first()
    empanelled = False
    if not mon:
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vid)).first()
        s.add(FinMonitorRecord(vendor_id=vid, entity_name=v.legal_name if v else vid))
        empanelled = True
        written.append("monitoring_empanelment")

    s.flush()
    return {"registered": True, "tables_written": written,
            "empanelled_for_monitoring": empanelled or bool(mon),
            "newly_empanelled": empanelled,
            "monitoring_cadence": report.get("monitoring_cadence")}


# ============================================================
# REQ 6 — Vendor 360 Dashboard: compile + correlate (deterministic)
# ============================================================
_BAND_RANK = {"HIGH": 3, "ELEVATED": 2, "MODERATE": 1, "LOW": 0}


def _posture_verdict(inherent, residual, open_findings, max_sev, fin_band, monitoring):
    """Single composite posture verdict, consistent with (never contradicting) the
    authoritative residual band. Deterministic."""
    base = residual or inherent or "MODERATE"
    score = _BAND_RANK.get(base, 1)
    # adverse intelligence can only RAISE concern, never lower it below residual
    if fin_band in ("Distress", "Weak", "Caution"):
        score = max(score, 2)
    if monitoring == "distress":
        score = max(score, 3)
    if max_sev == "Critical":
        score = max(score, 3)
    label = {3: "High concern", 2: "Elevated concern",
             1: "Moderate", 0: "Stable"}[min(3, score)]
    return {"band": base, "label": label, "level": min(3, score)}


def vendor360(s: Session, vendor_id: str) -> dict:
    """Compile ALL internal data for a vendor and correlate into derived insights.
    Deterministic; reconciles with the consolidated risk profile (one version of truth)."""
    v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
    if not v:
        return {}
    refresh_risk_profile(s, vendor_id)
    rp = latest_risk_profile(s, vendor_id) or {}
    ext = s.scalars(select(MX.VendorMasterExt).where(
        MX.VendorMasterExt.vendor_id == vendor_id)).first()
    engs = s.scalars(select(EngagementRecord).where(
        EngagementRecord.vendor_id == vendor_id)).all()
    contracts = list_contracts(s, vendor_id=vendor_id)
    # include engagement-linked contracts too
    for e in engs:
        for cc in list_contracts(s, engagement_id=e.engagement_id):
            if cc["contract_id"] not in {c["contract_id"] for c in contracts}:
                contracts.append(cc)
    findings = s.scalars(select(FindingRecord).where(
        FindingRecord.vendor_id == vendor_id, FindingRecord.status != "Closed")).all()
    scorecards = list_scorecards(s, vendor_id)
    crit = list_critical(s)
    is_critical = bool(v.is_critical)

    # ---------- correlation layer ----------
    eng_value = sum((e.annual_value or 0) for e in engs)
    concentration = {
        "engagement_count": len(engs),
        "total_annual_value": eng_value,
        "critical_engagements": [x["id"] for x in crit["critical_engagements"]
                                 if x["id"] in {e.engagement_id for e in engs}],
        "contract_count": len(contracts),
        "critical_contracts": sum(1 for c in contracts if c.get("is_critical")),
    }
    exposure_vs_control = {
        "inherent": rp.get("inherent_band"), "residual": rp.get("residual_band"),
        "open_findings": rp.get("open_findings", 0), "max_severity": rp.get("max_severity"),
        "gap": (_BAND_RANK.get(rp.get("inherent_band"), 0)
                - _BAND_RANK.get(rp.get("residual_band"), 0)),
    }
    # ranked exceptions
    exceptions = []
    for f in findings:
        exceptions.append({"type": "finding", "severity": f.severity,
                           "detail": f.title, "rank": {"Critical": 0, "High": 1,
                           "Medium": 2, "Low": 3}.get(f.severity, 4)})
    for sc in s.scalars(select(MX.VendorScreening).where(
            MX.VendorScreening.vendor_id == vendor_id)).all():
        if sc.next_due and sc.next_due < _today():
            exceptions.append({"type": "overdue_screening", "severity": "High",
                               "detail": f"{sc.screen_type} screening overdue", "rank": 1})
    if rp.get("monitoring_signal") == "distress":
        exceptions.append({"type": "monitoring", "severity": "High",
                           "detail": "Financial distress signal", "rank": 0})
    if ext and ext.financial_health_band in ("Distress", "Weak"):
        exceptions.append({"type": "financial", "severity": "High",
                           "detail": f"Financial health: {ext.financial_health_band}", "rank": 1})
    exceptions.sort(key=lambda x: x["rank"])

    verdict = _posture_verdict(rp.get("inherent_band"), rp.get("residual_band"),
                               rp.get("open_findings", 0), rp.get("max_severity"),
                               ext.financial_health_band if ext else None,
                               rp.get("monitoring_signal"))

    return {
        "vendor_id": vendor_id, "legal_name": v.legal_name, "tier": v.tier,
        "is_critical": is_critical, "criticality_reason": v.criticality_reason,
        "ultimate_parent": v.ultimate_parent,
        "posture": verdict,
        "dimensions": {
            "risk": {"inherent": rp.get("inherent_band"), "residual": rp.get("residual_band"),
                     "open_findings": rp.get("open_findings", 0),
                     "max_severity": rp.get("max_severity")},
            "financial": {"band": ext.financial_health_band if ext else None,
                          "going_concern_flag": ext.going_concern_flag if ext else None},
            "reputation": {"summary": rp.get("reputation_summary")},
            "monitoring": {"signal": rp.get("monitoring_signal")},
            "performance": {"score": rp.get("performance_score"),
                            "cadence": rp.get("review_cadence"),
                            "last_review": rp.get("last_review"),
                            "scorecards": len(scorecards)},
            "compliance": {"open_findings": rp.get("open_findings", 0)},
        },
        "concentration": concentration,
        "exposure_vs_control": exposure_vs_control,
        "exceptions": exceptions[:10],
        "exception_count": len(exceptions),
        "contracts": contracts,
        "engagements": [{"engagement_id": e.engagement_id, "title": e.title,
                         "inherent_band": e.inherent_band, "residual_band": e.residual_band,
                         "annual_value": e.annual_value} for e in engs],
        "provenance": {"risk_profile_snapshot": rp.get("snapshot_at"),
                       "source": "internal", "reconciled_with_risk_profile": True},
    }


def vendor360_portfolio(s: Session) -> list[dict]:
    """Portfolio entry: rankable by posture, criticality, exceptions."""
    vendors = s.scalars(select(VendorRecord)).all()
    out = []
    for v in vendors:
        rp = latest_risk_profile(s, v.vendor_id) or {}
        ext = s.scalars(select(MX.VendorMasterExt).where(
            MX.VendorMasterExt.vendor_id == v.vendor_id)).first()
        verdict = _posture_verdict(rp.get("inherent_band"), rp.get("residual_band"),
                                   rp.get("open_findings", 0), rp.get("max_severity"),
                                   ext.financial_health_band if ext else None,
                                   rp.get("monitoring_signal"))
        out.append({"vendor_id": v.vendor_id, "legal_name": v.legal_name,
                    "tier": v.tier, "is_critical": bool(v.is_critical),
                    "posture": verdict["label"], "posture_level": verdict["level"],
                    "residual": rp.get("residual_band"),
                    "open_findings": rp.get("open_findings", 0)})
    out.sort(key=lambda x: (not x["is_critical"], -x["posture_level"], -x["open_findings"]))
    return out
