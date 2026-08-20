"""
Registry models — the exhaustive data model for the TPRM platform.

New entities (all with human-readable auto-IDs):
  IdCounter          per-entity sequence source
  IndustryMaster     SIC-based industry list (Industry ID = name)
  MaterialGroupMaster UNSPSC-based material groups
  VendorGroup        group/parent company (GRP-xxxxx)
  VendorRecord       exhaustive vendor (VEN-xxxxxx) — many per group
  VendorIndustry     vendor <-> industry tags (many-to-many)
  ContactRecord      contacts for vendor/engagement (primary + backups)
  EngagementRecord   exhaustive engagement (ENG-xxxxxx) — many per vendor
  AssessmentRecord   assessment (ASM-xxxxxx) — mapped to engagement
  FindingRecord      finding (FND-xxxxxx)
  RemediationRecord  remediation plan (RMD-xxxxxx)
  FourthPartyRecord  fourth party (F4P-xxxxxx) — mirrors vendor, many-vendor link
  FourthPartyVendor  fourth-party <-> vendor link (many-to-many)
  ArtefactRecord     dated evidence / certificate (ART-xxxxxx)
  IssueRecord        issues log (ISS-xxxxxx)

These complement the original lightweight Vendor/EngagementRow (kept for the
existing tested endpoints); new endpoints use these richer records.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.features.domain.models_db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IdCounter(Base):
    __tablename__ = "id_counters"
    entity: Mapped[str] = mapped_column(String, primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)


class IndustryMaster(Base):
    __tablename__ = "industry_master"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    industry_id: Mapped[str] = mapped_column(String, unique=True)  # the name
    sic_code: Mapped[str] = mapped_column(String)
    division: Mapped[Optional[str]] = mapped_column(String, default=None)


class MaterialGroupMaster(Base):
    __tablename__ = "material_group_master"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_group_id: Mapped[str] = mapped_column(String, unique=True)  # the name
    unspsc_code: Mapped[str] = mapped_column(String)


class VendorGroup(Base):
    __tablename__ = "vendor_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(String, unique=True)   # GRP-xxxxx
    name: Mapped[str] = mapped_column(String)
    parent_company: Mapped[Optional[str]] = mapped_column(String, default=None)
    ai_assigned: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorRecord(Base):
    __tablename__ = "vendor_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, unique=True)   # VEN-xxxxxx (PK semantics)
    group_id: Mapped[Optional[str]] = mapped_column(String, default=None)  # GRP-xxxxx
    # identity
    legal_name: Mapped[str] = mapped_column(String)
    trading_name: Mapped[Optional[str]] = mapped_column(String, default=None)
    registration_number: Mapped[Optional[str]] = mapped_column(String, default=None)
    tax_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    duns: Mapped[Optional[str]] = mapped_column(String, default=None)
    lei: Mapped[Optional[str]] = mapped_column(String, default=None)
    website: Mapped[Optional[str]] = mapped_column(String, default=None)
    # corporate
    incorporation_country: Mapped[Optional[str]] = mapped_column(String, default=None)
    incorporation_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    legal_form: Mapped[Optional[str]] = mapped_column(String, default=None)
    listing_status: Mapped[Optional[str]] = mapped_column(String, default=None)  # public/private
    ticker: Mapped[Optional[str]] = mapped_column(String, default=None)
    ultimate_parent: Mapped[Optional[str]] = mapped_column(String, default=None)
    employee_count: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    annual_revenue: Mapped[Optional[float]] = mapped_column(Float, default=None)
    revenue_currency: Mapped[Optional[str]] = mapped_column(String, default=None)
    # addresses
    hq_address: Mapped[Optional[str]] = mapped_column(Text, default=None)
    hq_country: Mapped[Optional[str]] = mapped_column(String, default=None)
    operating_countries: Mapped[Optional[str]] = mapped_column(Text, default=None)  # csv
    # classification / risk
    tier: Mapped[str] = mapped_column(String, default="Tier 3")
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    criticality_reason: Mapped[Optional[str]] = mapped_column(Text, default=None)
    # banking / tax
    bank_name: Mapped[Optional[str]] = mapped_column(String, default=None)
    bank_account: Mapped[Optional[str]] = mapped_column(String, default=None)
    payment_terms: Mapped[Optional[str]] = mapped_column(String, default=None)
    # lifecycle / status
    status: Mapped[str] = mapped_column(String, default="Active")  # Active/Inactive/Onboarding/Offboarded
    onboarded_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    # procurement link
    procurement_ref: Mapped[Optional[str]] = mapped_column(String, default=None)
    source_system: Mapped[Optional[str]] = mapped_column(String, default=None)
    # cross-link if this vendor is also catalogued as a fourth party
    fourth_party_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_via: Mapped[str] = mapped_column(String, default="button")  # button/chat/procurement
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorIndustry(Base):
    __tablename__ = "vendor_industries"
    __table_args__ = (UniqueConstraint("vendor_id", "industry_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    industry_id: Mapped[str] = mapped_column(String)  # name from IndustryMaster


class ContactRecord(Base):
    __tablename__ = "contact_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_type: Mapped[str] = mapped_column(String)   # vendor / engagement / fourth_party
    owner_id: Mapped[str] = mapped_column(String)     # VEN-/ENG-/F4P-
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[Optional[str]] = mapped_column(String, default=None)
    phone_country_code: Mapped[Optional[str]] = mapped_column(String, default=None)  # +44
    phone_number: Mapped[Optional[str]] = mapped_column(String, default=None)
    designation: Mapped[Optional[str]] = mapped_column(String, default=None)
    country: Mapped[Optional[str]] = mapped_column(String, default=None)
    mailing_address: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EngagementRecord(Base):
    __tablename__ = "engagement_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String, unique=True)  # ENG-xxxxxx
    vendor_id: Mapped[str] = mapped_column(String, index=True)                   # many per vendor
    title: Mapped[str] = mapped_column(String)
    service_description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    material_group_id: Mapped[Optional[str]] = mapped_column(String, default=None)  # UNSPSC name
    deployment_model: Mapped[Optional[str]] = mapped_column(String, default=None)
    business_unit: Mapped[Optional[str]] = mapped_column(String, default=None)
    contract_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)        # CON-xxxxxx
    assessment_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)      # ASM-xxxxxx (latest)
    annual_value: Mapped[Optional[float]] = mapped_column(Float, default=None)
    currency: Mapped[Optional[str]] = mapped_column(String, default=None)
    start_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    end_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    # risk rollups
    inherent_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    inherent_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    residual_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    residual_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    open_actions: Mapped[int] = mapped_column(Integer, default=0)  # derived rollup
    # status
    status: Mapped[str] = mapped_column(String, default="Active")  # Active/Inactive/Overdue
    stage: Mapped[str] = mapped_column(String, default="sourcing")
    owner_user: Mapped[Optional[str]] = mapped_column(String, default=None)  # engagement owner
    assigned_assessor: Mapped[Optional[str]] = mapped_column(String, default=None)  # Controller-assigned
    last_assessment_date: Mapped[Optional[str]] = mapped_column(String, default=None)   # ISO date of latest assessment
    next_assessment_due: Mapped[Optional[str]] = mapped_column(String, default=None)    # ISO date reassessment is due
    reassessment_reason: Mapped[Optional[str]] = mapped_column(String, default=None)    # why a reassessment was scheduled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AssessmentRecord(Base):
    __tablename__ = "assessment_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String, unique=True)  # ASM-xxxxxx
    engagement_id: Mapped[str] = mapped_column(String, index=True)               # mapped to engagement
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    session_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # chat session
    status: Mapped[str] = mapped_column(String, default="Drafted")  # Drafted/In-Progress/Completed/Approved/Recalled
    # structured capture
    inherent_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    residual_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    outcome: Mapped[Optional[str]] = mapped_column(String, default=None)  # Approved / Approved with findings
    structured_json: Mapped[str] = mapped_column(Text, default="{}")      # per-stage structured data
    # ownership / access
    engagement_owner: Mapped[Optional[str]] = mapped_column(String, default=None)
    spoc_name: Mapped[Optional[str]] = mapped_column(String, default=None)
    spoc_email: Mapped[Optional[str]] = mapped_column(String, default=None)
    spoc_office: Mapped[Optional[str]] = mapped_column(String, default=None)
    spoc_user: Mapped[Optional[str]] = mapped_column(String, default=None)  # username for access
    # assessor (high inherent)
    assessor_user: Mapped[Optional[str]] = mapped_column(String, default=None)
    assessor_signed_off: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # hard-lock on Approved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FindingRecord(Base):
    __tablename__ = "finding_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String, unique=True)  # FND-xxxxxx (Finding Number)
    assessment_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    engagement_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    title: Mapped[str] = mapped_column(String)                        # Heading
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)  # Details
    domain: Mapped[Optional[str]] = mapped_column(String, default=None)
    severity: Mapped[str] = mapped_column(String, default="Medium")  # Critical/High/Medium/Low
    source: Mapped[str] = mapped_column(String, default="Assessor")   # AI / Assessor
    # lifecycle: Draft/Published/Under Remediation/Remediated/Verified/Closed
    status: Mapped[str] = mapped_column(String, default="Draft")
    owner: Mapped[Optional[str]] = mapped_column(String, default=None)        # remediation owner
    assessor: Mapped[Optional[str]] = mapped_column(String, default=None)     # responsible assessor
    suggested_remediation: Mapped[Optional[str]] = mapped_column(Text, default=None)
    suggested_closure: Mapped[Optional[str]] = mapped_column(Text, default=None)
    progress_notes: Mapped[str] = mapped_column(Text, default="[]")           # JSON list of {ts,user,note}
    attachments: Mapped[str] = mapped_column(Text, default="[]")              # JSON list of {doc_id,name}
    # risk acceptance
    risk_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    acceptance_expiry: Mapped[Optional[str]] = mapped_column(String, default=None)
    acceptance_rationale: Mapped[Optional[str]] = mapped_column(Text, default=None)
    accepted_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    raised_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    due_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    remediation_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    closed_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RemediationRecord(Base):
    __tablename__ = "remediation_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    remediation_id: Mapped[str] = mapped_column(String, unique=True)  # RMD-xxxxxx
    finding_id: Mapped[str] = mapped_column(String, index=True)
    plan: Mapped[str] = mapped_column(Text)
    owner: Mapped[Optional[str]] = mapped_column(String, default=None)
    target_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    milestones_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String, default="Planned")  # Planned/In Progress/Complete/Verified
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[Optional[str]] = mapped_column(Text, default=None)
    completed_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    verified_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FourthPartyRecord(Base):
    __tablename__ = "fourth_party_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fourth_party_id: Mapped[str] = mapped_column(String, unique=True)  # F4P-xxxxxx
    legal_name: Mapped[str] = mapped_column(String)
    service_provided: Mapped[Optional[str]] = mapped_column(String, default=None)
    hq_country: Mapped[Optional[str]] = mapped_column(String, default=None)
    registration_number: Mapped[Optional[str]] = mapped_column(String, default=None)
    website: Mapped[Optional[str]] = mapped_column(String, default=None)
    listing_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    concentration_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    # if this fourth party is ALSO a vendor in our system:
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FourthPartyVendor(Base):
    __tablename__ = "fourth_party_vendors"
    __table_args__ = (UniqueConstraint("fourth_party_id", "vendor_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fourth_party_id: Mapped[str] = mapped_column(String)
    vendor_id: Mapped[str] = mapped_column(String, index=True)


class ArtefactRecord(Base):
    __tablename__ = "artefact_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artefact_id: Mapped[str] = mapped_column(String, unique=True)  # ART-xxxxxx
    vendor_id: Mapped[str] = mapped_column(String, index=True)                 # mapped to vendor
    engagement_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    name: Mapped[str] = mapped_column(String)
    artefact_type: Mapped[str] = mapped_column(String, default="certificate")  # soc2/iso/cert/other
    is_dated: Mapped[bool] = mapped_column(Boolean, default=True)  # carries validity
    issue_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    expiry_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    status: Mapped[str] = mapped_column(String, default="Valid")  # Valid/Expiring/Expired
    object_uri: Mapped[Optional[str]] = mapped_column(String, default=None)
    supersedes: Mapped[Optional[str]] = mapped_column(String, default=None)  # prior artefact_id
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    received_via: Mapped[str] = mapped_column(String, default="upload")  # upload/chat/email
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class IssueRecord(Base):
    __tablename__ = "issue_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[str] = mapped_column(String, unique=True)  # ISS-xxxxxx
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    vendor_name: Mapped[str] = mapped_column(String)
    artefact_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    kind: Mapped[str] = mapped_column(String, default="expired_certificate")
    detail: Mapped[Optional[str]] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String, default="Open")  # Open/Closed
    closed_reason: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)


class FinMonitorRecord(Base):
    """A vendor empanelled for periodic financial-health monitoring sweeps."""
    __tablename__ = "fin_monitor_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)  # VEN- or None for "Other"
    entity_name: Mapped[str] = mapped_column(String)
    last_result: Mapped[Optional[str]] = mapped_column(Text, default=None)
    last_signal: Mapped[Optional[str]] = mapped_column(String, default=None)  # ok/watch/distress
    last_swept: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class IncidentRecord(Base):
    __tablename__ = "incident_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[str] = mapped_column(String, unique=True)   # INC-xxxxxx
    date_of_incident: Mapped[Optional[str]] = mapped_column(String, default=None)   # ISO date
    reported_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    reported_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    # vendor
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    vendor_name: Mapped[Optional[str]] = mapped_column(String, default=None)
    engagement_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)   # primary tagged engagement
    active_engagements: Mapped[str] = mapped_column(Text, default="[]")   # auto-tagged JSON list
    # classification
    incident_type: Mapped[Optional[str]] = mapped_column(String, default=None)
    severity: Mapped[str] = mapped_column(String, default="Medium")        # Low/Medium/High/Critical
    customer_impacting: Mapped[bool] = mapped_column(Boolean, default=False)
    impacts_client_org: Mapped[bool] = mapped_column(Boolean, default=False)
    impact_description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    region: Mapped[str] = mapped_column(Text, default="[]")                # Global or country list (JSON)
    # investigation
    root_cause_assessment: Mapped[Optional[str]] = mapped_column(Text, default=None)
    risk_entry_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_entry_ref: Mapped[Optional[str]] = mapped_column(String, default=None)   # FND-xxxxxx if drafted
    notes_log: Mapped[str] = mapped_column(Text, default="[]")             # JSON [{ts,user,note}]
    attachments: Mapped[str] = mapped_column(Text, default="[]")          # JSON list
    status: Mapped[str] = mapped_column(String, default="Drafted")        # Drafted/Under investigation/Closed
    # vendor notification SLA / traffic light
    vendor_notified_at: Mapped[Optional[str]] = mapped_column(String, default=None)
    notification_sla_hours: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    notification_compliant: Mapped[Optional[str]] = mapped_column(String, default=None)  # green/amber/red
    contract_notification_summary: Mapped[Optional[str]] = mapped_column(Text, default=None)  # AI cache
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    created_by: Mapped[Optional[str]] = mapped_column(String, default=None)


class PestleProfile(Base):
    """150-dimension PESTLE risk vector for a vendor or engagement (refreshable)."""
    __tablename__ = "pestle_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String)        # vendor | engagement
    entity_id: Mapped[str] = mapped_column(String, index=True)
    label: Mapped[Optional[str]] = mapped_column(String, default=None)
    base_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    vector_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    cats_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    overall: Mapped[Optional[float]] = mapped_column(Float, default=None)
    top_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    movers_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    refreshed_at: Mapped[Optional[str]] = mapped_column(String, default=None)
    __table_args__ = (UniqueConstraint("entity_type", "entity_id"),)


class OssComponent(Base):
    """A deduplicated open-source component (purl/name@version) seen across SBOMs."""
    __tablename__ = "oss_component"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True, index=True)   # purl or name@version
    name: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[Optional[str]] = mapped_column(String, default=None)
    ecosystem: Mapped[Optional[str]] = mapped_column(String, default=None)
    purl: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    cpe: Mapped[Optional[str]] = mapped_column(String, default=None)
    hash: Mapped[Optional[str]] = mapped_column(String, default=None)
    licence: Mapped[Optional[str]] = mapped_column(String, default=None)
    licence_category: Mapped[Optional[str]] = mapped_column(String, default=None)  # allowed/restricted/prohibited/review
    supplier: Mapped[Optional[str]] = mapped_column(String, default=None)
    maintenance: Mapped[Optional[str]] = mapped_column(String, default="unknown")  # healthy/unmaintained/eol/unknown
    risk_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    risk_band: Mapped[Optional[str]] = mapped_column(String, default="LOW")
    usage_count: Mapped[int] = mapped_column(Integer, default=0)        # distinct engagements
    vendor_count: Mapped[int] = mapped_column(Integer, default=0)       # distinct vendors
    first_seen: Mapped[Optional[str]] = mapped_column(String, default=None)


class OssVuln(Base):
    __tablename__ = "oss_vuln"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(Integer, index=True)
    cve: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[Optional[str]] = mapped_column(String, default="OSV")  # OSV/NVD/GHSA
    cvss: Mapped[Optional[float]] = mapped_column(Float, default=None)
    severity: Mapped[Optional[str]] = mapped_column(String, default=None)
    epss: Mapped[Optional[float]] = mapped_column(Float, default=None)
    kev: Mapped[bool] = mapped_column(Boolean, default=False)
    vex_status: Mapped[Optional[str]] = mapped_column(String, default="affected")  # affected/not_affected/fixed/under_investigation
    summary: Mapped[Optional[str]] = mapped_column(Text, default=None)


class OssSbom(Base):
    __tablename__ = "oss_sbom"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String, index=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)
    product: Mapped[Optional[str]] = mapped_column(String, default=None)
    product_version: Mapped[Optional[str]] = mapped_column(String, default=None)
    fmt: Mapped[Optional[str]] = mapped_column(String, default=None)        # cyclonedx/spdx
    spec_version: Mapped[Optional[str]] = mapped_column(String, default=None)
    sbom_type: Mapped[Optional[str]] = mapped_column(String, default=None)  # CISA taxonomy
    component_count: Mapped[int] = mapped_column(Integer, default=0)
    ntia_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    quality_label: Mapped[Optional[str]] = mapped_column(String, default=None)
    source_channel: Mapped[Optional[str]] = mapped_column(String, default="seed")
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[Optional[str]] = mapped_column(String, default=None)


class OssUsage(Base):
    """Tags a component to a vendor engagement (component -> SBOM -> engagement -> vendor)."""
    __tablename__ = "oss_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(Integer, index=True)
    sbom_id: Mapped[int] = mapped_column(Integer, index=True)
    engagement_id: Mapped[str] = mapped_column(String, index=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)
    dep_type: Mapped[Optional[str]] = mapped_column(String, default="direct")   # direct/transitive
    scope: Mapped[Optional[str]] = mapped_column(String, default="runtime")     # runtime/build/test/optional
    depth: Mapped[int] = mapped_column(Integer, default=0)


class AiFeedback(Base):
    """User feedback on AI-generated answers — collected and fed back into prompts."""
    __tablename__ = "ai_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[Optional[str]] = mapped_column(String, default=None)
    username: Mapped[Optional[str]] = mapped_column(String, default=None)
    surface: Mapped[Optional[str]] = mapped_column(String, default=None)   # management/board/bro_chat/...
    query: Mapped[Optional[str]] = mapped_column(Text, default=None)
    answer: Mapped[Optional[str]] = mapped_column(Text, default=None)
    rating: Mapped[Optional[str]] = mapped_column(String, default="na")    # up/down/na
    comment: Mapped[Optional[str]] = mapped_column(Text, default=None)
    engine: Mapped[Optional[str]] = mapped_column(String, default=None)    # llm/deterministic
    used: Mapped[bool] = mapped_column(Boolean, default=False)             # incorporated into improvement
    used_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    used_at: Mapped[Optional[str]] = mapped_column(String, default=None)


class SanctionsScreening(Base):
    """Audit record of a sanctions / PEP / adverse-media screening run."""
    __tablename__ = "sanctions_screenings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    screening_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None, index=True)
    screened_name: Mapped[str] = mapped_column(String)
    country: Mapped[Optional[str]] = mapped_column(String, default=None)
    band: Mapped[str] = mapped_column(String, default="Clear")   # Clear / Review / Hit
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    hits: Mapped[str] = mapped_column(Text, default="[]")         # JSON
    sources_used: Mapped[str] = mapped_column(Text, default="[]") # JSON
    screened_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class VendorPerson(Base):
    """Beneficial owner / key person attached to a vendor — screened for sanctions/PEP."""
    __tablename__ = "vendor_persons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[Optional[str]] = mapped_column(String, default=None)  # UBO / Director / Officer
    dob: Mapped[Optional[str]] = mapped_column(String, default=None)
    nationality: Mapped[Optional[str]] = mapped_column(String, default=None)
    ownership_pct: Mapped[Optional[float]] = mapped_column(Float, default=None)
    is_ubo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class WatchlistEntry(Base):
    """Ingested watchlist entry from a live feed (e.g. OFSI). Screened alongside the
    built-in representative list; this is what makes screening 'live'."""
    __tablename__ = "watchlist_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ext_id: Mapped[str] = mapped_column(String, index=True)        # source-native id
    source: Mapped[str] = mapped_column(String, index=True)        # e.g. "OFSI (live)"
    name: Mapped[str] = mapped_column(String)
    aliases: Mapped[str] = mapped_column(Text, default="[]")       # JSON
    category: Mapped[str] = mapped_column(String, default="sanction")
    list_name: Mapped[Optional[str]] = mapped_column(String, default=None)
    program: Mapped[Optional[str]] = mapped_column(String, default=None)
    country: Mapped[Optional[str]] = mapped_column(String, default=None)
    nationality: Mapped[Optional[str]] = mapped_column(String, default=None)
    entity_type: Mapped[Optional[str]] = mapped_column(String, default=None)
    dob: Mapped[Optional[str]] = mapped_column(String, default=None)
    loaded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class MonitoringRun(Base):
    """Audit record of a scheduled/on-request monitoring sweep."""
    __tablename__ = "monitoring_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    trigger: Mapped[str] = mapped_column(String, default="manual")  # manual / scheduler / cron
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    tasks: Mapped[str] = mapped_column(Text, default="{}")  # JSON: per-task summary


# ============================================================================
# Watchlist module — supplier watchlist, criteria, sweep candidates, and notes
# ============================================================================

class WatchlistCriterion(Base):
    """A rule that flags a supplier onto the watchlist.

    rule_type governs how (or whether) the database sweep can auto-evaluate it:
      country  — rule_value is a comma-separated list matched against a vendor's
                 incorporation / HQ / operating countries (e.g. restricted countries).
      keyword  — rule_value keywords matched against adverse-media / reputation /
                 finding text for the vendor.
      flag     — rule_value names a boolean signal (e.g. government_owned).
      manual   — no auto-evaluation; entries under this criterion are added by hand.
    """
    __tablename__ = "watchlist_criteria"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    criterion_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, default="Single-Issue Trigger")
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    rule_type: Mapped[str] = mapped_column(String, default="manual")   # country/keyword/flag/manual
    rule_value: Mapped[Optional[str]] = mapped_column(Text, default=None)
    severity: Mapped[str] = mapped_column(String, default="High")      # High/Elevated/Moderate
    weight: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String, default=None)  # e.g. GI 3000.005 App. B
    created_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class SupplierWatchlistEntry(Base):
    """An active (or cleared) watchlist flag against a supplier."""
    __tablename__ = "supplier_watchlist_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    criterion_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    reason: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String, default="High")
    since_date: Mapped[str] = mapped_column(String)               # ISO date
    next_review_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    status: Mapped[str] = mapped_column(String, default="Active", index=True)  # Active/Cleared
    source: Mapped[str] = mapped_column(String, default="manual")  # manual/sweep
    added_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    cleared_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    cleared_at: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class WatchlistCandidate(Base):
    """A vendor/criterion match produced by a sweep, awaiting controller decision."""
    __tablename__ = "watchlist_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    criterion_id: Mapped[str] = mapped_column(String)
    evidence: Mapped[Optional[str]] = mapped_column(Text, default=None)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String, default="pending", index=True)  # pending/approved/rejected
    decided_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    decided_at: Mapped[Optional[str]] = mapped_column(String, default=None)


class SupplierNote(Base):
    """A free-text note against a supplier — visible to internal users, never to suppliers."""
    __tablename__ = "supplier_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    vendor_id: Mapped[str] = mapped_column(String, index=True)
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, default="General")
    author: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
