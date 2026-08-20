"""
Extended data model for Requirements 1, 2, 3.

Req 1 — Vendor Master: richer identity/structure/classification/financial/tax/
        banking captured as an extension row (VendorMasterExt) keyed 1:1 to the
        existing VendorRecord by vendor_id, so the existing model is preserved
        and migration is additive.

Req 2 — Vendor Attribute Database: one row per vendor per domain, linked by
        VEN-. Screening items are typed records (result + date + next_due);
        monitoring signals are typed records (value + source + freshness).
        Rollup domains (risk profile, performance) are stored as a cache row
        refreshed from the existing child records.

Req 3 — Engagement Register: extension row (EngagementExt) keyed 1:1 to
        EngagementRecord, plus five one-to-many child tables (deliverables,
        milestones, SLAs, obligations, assigned personnel).

All tables are additive; nothing in registry_models.py changes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.features.domain.models_db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# REQ 1 — VENDOR MASTER (extension, 1:1 with VendorRecord by vendor_id)
# ============================================================
class VendorMasterExt(Base):
    __tablename__ = "vendor_master_ext"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, unique=True)  # VEN- (FK to VendorRecord)

    # --- identifiers & keys ---
    euid: Mapped[Optional[str]] = mapped_column(String, default=None)
    erp_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    sourcing_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    grc_id: Mapped[Optional[str]] = mapped_column(String, default=None)

    # --- legal identity ---
    dba_names: Mapped[Optional[str]] = mapped_column(Text, default=None)        # csv
    previous_names: Mapped[Optional[str]] = mapped_column(Text, default=None)   # csv
    operating_status: Mapped[Optional[str]] = mapped_column(String, default=None)  # active/dissolved/administration

    # --- corporate structure & ownership ---
    immediate_parent: Mapped[Optional[str]] = mapped_column(String, default=None)
    subsidiaries: Mapped[Optional[str]] = mapped_column(Text, default=None)     # csv / json
    ubo_json: Mapped[str] = mapped_column(Text, default="[]")                   # [{name, pct}]
    ownership_type: Mapped[Optional[str]] = mapped_column(String, default=None) # private/listed/PE/state
    exchange: Mapped[Optional[str]] = mapped_column(String, default=None)

    # --- classification & segmentation ---
    sic_code: Mapped[Optional[str]] = mapped_column(String, default=None)
    unspsc_code: Mapped[Optional[str]] = mapped_column(String, default=None)
    nace_naics: Mapped[Optional[str]] = mapped_column(String, default=None)
    supplier_category: Mapped[Optional[str]] = mapped_column(String, default=None)
    segmentation: Mapped[Optional[str]] = mapped_column(String, default=None)  # strategic/critical/transactional
    spend_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    sole_source: Mapped[bool] = mapped_column(Boolean, default=False)
    substitutability: Mapped[Optional[str]] = mapped_column(String, default=None)  # easy/moderate/hard

    # --- relationship & internal ownership ---
    relationship_owner: Mapped[Optional[str]] = mapped_column(String, default=None)
    sponsoring_bu: Mapped[Optional[str]] = mapped_column(String, default=None)
    cost_centre: Mapped[Optional[str]] = mapped_column(String, default=None)
    strategic_importance: Mapped[Optional[str]] = mapped_column(String, default=None)
    business_dependency: Mapped[Optional[str]] = mapped_column(Text, default=None)
    relationship_health: Mapped[Optional[str]] = mapped_column(String, default=None)

    # --- addresses & geography ---
    billing_address: Mapped[Optional[str]] = mapped_column(Text, default=None)
    remittance_address: Mapped[Optional[str]] = mapped_column(Text, default=None)
    operating_address: Mapped[Optional[str]] = mapped_column(Text, default=None)
    service_countries: Mapped[Optional[str]] = mapped_column(Text, default=None)   # csv
    data_locations: Mapped[Optional[str]] = mapped_column(Text, default=None)      # csv country|onprem/cloud
    offshore_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    geopolitical_risk: Mapped[Optional[str]] = mapped_column(String, default=None)
    sanctions_jurisdiction_exposure: Mapped[Optional[str]] = mapped_column(String, default=None)

    # --- financial & commercial ---
    currency: Mapped[Optional[str]] = mapped_column(String, default=None)
    payment_method: Mapped[Optional[str]] = mapped_column(String, default=None)
    credit_limit: Mapped[Optional[float]] = mapped_column(Float, default=None)
    annual_spend: Mapped[Optional[float]] = mapped_column(Float, default=None)
    spend_trend: Mapped[Optional[str]] = mapped_column(String, default=None)  # up/flat/down
    discount_terms: Mapped[Optional[str]] = mapped_column(String, default=None)
    credit_rating: Mapped[Optional[str]] = mapped_column(String, default=None)
    credit_rating_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    financial_health_band: Mapped[Optional[str]] = mapped_column(String, default=None)  # rollup from FDD
    going_concern_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- tax & regulatory registration ---
    vat_number: Mapped[Optional[str]] = mapped_column(String, default=None)
    w_form_status: Mapped[Optional[str]] = mapped_column(String, default=None)  # W-8/W-9
    tax_residency: Mapped[Optional[str]] = mapped_column(String, default=None)
    regulatory_licences: Mapped[Optional[str]] = mapped_column(Text, default=None)  # csv name:status
    regulated_entity: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- banking & payment (SENSITIVE) ---
    bank_account_name: Mapped[Optional[str]] = mapped_column(String, default=None)
    iban: Mapped[Optional[str]] = mapped_column(String, default=None)
    swift_bic: Mapped[Optional[str]] = mapped_column(String, default=None)
    routing_number: Mapped[Optional[str]] = mapped_column(String, default=None)
    bank_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    bank_verified_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    bank_change_locked: Mapped[bool] = mapped_column(Boolean, default=True)  # fraud control: dual-approve

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ============================================================
# REQ 2 — VENDOR ATTRIBUTE DATABASE (linked by VEN-)
# ============================================================
class VendorScreening(Base):
    """Integrity screening — one row per screening type per vendor.
    result + date + next_due triplet."""
    __tablename__ = "vendor_screening"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String)
    screen_type: Mapped[str] = mapped_column(String)   # sanctions/pep/adverse_media/abac/debarment/modern_slavery/coi
    result: Mapped[Optional[str]] = mapped_column(String, default=None)   # clear/hit/review/on-file/not-checked
    detail: Mapped[Optional[str]] = mapped_column(Text, default=None)     # lists checked, notes
    screened_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    next_due: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorPrivacy(Base):
    """Data protection & privacy — 1:1 per vendor."""
    __tablename__ = "vendor_privacy"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, unique=True)
    processes_personal_data: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[Optional[str]] = mapped_column(String, default=None)  # controller/processor/sub-processor
    dpa_in_place: Mapped[bool] = mapped_column(Boolean, default=False)
    data_categories: Mapped[Optional[str]] = mapped_column(Text, default=None)
    data_subject_types: Mapped[Optional[str]] = mapped_column(Text, default=None)
    transfer_mechanism: Mapped[Optional[str]] = mapped_column(String, default=None)  # SCCs/IDTA/adequacy
    subprocessor_list_maintained: Mapped[bool] = mapped_column(Boolean, default=False)
    ropa_reference: Mapped[Optional[str]] = mapped_column(String, default=None)  # Art.30
    retention_terms: Mapped[Optional[str]] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorCyber(Base):
    """Cyber & security posture — 1:1 per vendor (certs are a rollup from artefacts)."""
    __tablename__ = "vendor_cyber"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, unique=True)
    certifications_json: Mapped[str] = mapped_column(Text, default="[]")  # rollup [{name, expiry, status}]
    assurance_status: Mapped[Optional[str]] = mapped_column(String, default=None)  # SOC2/ISO/none
    external_rating: Mapped[Optional[str]] = mapped_column(String, default=None)
    external_rating_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    pentest_recency: Mapped[Optional[str]] = mapped_column(String, default=None)
    breach_history_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    security_contact: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorResilience(Base):
    """Operational resilience & supply chain — 1:1 per vendor."""
    __tablename__ = "vendor_resilience"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, unique=True)
    supports_critical_function: Mapped[bool] = mapped_column(Boolean, default=False)
    nth_party_json: Mapped[str] = mapped_column(Text, default="[]")  # [{name, rank, parent}] dependency tree
    shared_upstream_flags: Mapped[Optional[str]] = mapped_column(Text, default=None)  # csv cloud/cdn/identity
    spof_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    concentration_indicator: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # rollup
    bcp_in_place: Mapped[bool] = mapped_column(Boolean, default=False)
    bcp_last_tested: Mapped[Optional[str]] = mapped_column(String, default=None)
    bcp_test_result: Mapped[Optional[str]] = mapped_column(String, default=None)
    exit_plan_documented: Mapped[bool] = mapped_column(Boolean, default=False)
    exit_plan_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    exit_plan_tested_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    rto: Mapped[Optional[str]] = mapped_column(String, default=None)
    rpo: Mapped[Optional[str]] = mapped_column(String, default=None)
    alternative_provider: Mapped[Optional[str]] = mapped_column(String, default=None)
    portability_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    switching_cost: Mapped[Optional[float]] = mapped_column(Float, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorESG(Base):
    """ESG & sustainability — 1:1 per vendor."""
    __tablename__ = "vendor_esg"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, unique=True)
    esg_rating: Mapped[Optional[str]] = mapped_column(String, default=None)
    esg_rating_source: Mapped[Optional[str]] = mapped_column(String, default=None)
    scope3_sbt_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    environmental_certs: Mapped[Optional[str]] = mapped_column(Text, default=None)
    labour_audit_findings: Mapped[Optional[str]] = mapped_column(Text, default=None)
    diversity_classification: Mapped[Optional[str]] = mapped_column(String, default=None)
    conflict_minerals_exposure: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorInsurance(Base):
    """Insurance — one row per policy per vendor."""
    __tablename__ = "vendor_insurance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String)
    policy_type: Mapped[str] = mapped_column(String)  # professional_indemnity/cyber/public_liability
    coverage_limit: Mapped[Optional[float]] = mapped_column(Float, default=None)
    currency: Mapped[Optional[str]] = mapped_column(String, default=None)
    insurer: Mapped[Optional[str]] = mapped_column(String, default=None)
    certificate_expiry: Mapped[Optional[str]] = mapped_column(String, default=None)
    named_insured_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorMonitorSignal(Base):
    """Continuous-monitoring signals — value + source + freshness (time-series)."""
    __tablename__ = "vendor_monitor_signal"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String)
    signal_type: Mapped[str] = mapped_column(String)  # cyber_rating/financial_health/sanctions_media/news_sentiment/breach
    value: Mapped[Optional[str]] = mapped_column(String, default=None)
    source: Mapped[Optional[str]] = mapped_column(String, default=None)
    captured_at: Mapped[Optional[str]] = mapped_column(String, default=None)  # freshness
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VendorRiskProfile(Base):
    """Risk profile + performance rollup cache — 1:1 per vendor, time-versioned via history rows."""
    __tablename__ = "vendor_risk_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String)
    # risk profile (rollup)
    inherent_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    residual_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    open_findings: Mapped[int] = mapped_column(Integer, default=0)
    max_severity: Mapped[Optional[str]] = mapped_column(String, default=None)
    overall_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    last_assessment: Mapped[Optional[str]] = mapped_column(String, default=None)
    next_assessment_due: Mapped[Optional[str]] = mapped_column(String, default=None)
    monitoring_signal: Mapped[Optional[str]] = mapped_column(String, default=None)
    reputation_summary: Mapped[Optional[str]] = mapped_column(String, default=None)
    # performance & value (rollup)
    sla_summary: Mapped[Optional[str]] = mapped_column(String, default=None)
    incident_count: Mapped[int] = mapped_column(Integer, default=0)
    dispute_history: Mapped[Optional[str]] = mapped_column(Text, default=None)
    performance_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    review_cadence: Mapped[Optional[str]] = mapped_column(String, default=None)
    last_review: Mapped[Optional[str]] = mapped_column(String, default=None)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=_now)  # time-versioned


class VendorGovernanceMeta(Base):
    """Record governance / metadata — practical subset, 1:1 per vendor."""
    __tablename__ = "vendor_governance_meta"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, unique=True)
    source_of_truth: Mapped[Optional[str]] = mapped_column(String, default=None)
    match_confidence: Mapped[Optional[float]] = mapped_column(Float, default=None)
    duplicate_cluster_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    data_steward: Mapped[Optional[str]] = mapped_column(String, default=None)
    source_system: Mapped[Optional[str]] = mapped_column(String, default=None)
    dq_completeness: Mapped[Optional[float]] = mapped_column(Float, default=None)
    record_version: Mapped[int] = mapped_column(Integer, default=1)
    consent_basis: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    # lifecycle & status (entity-level)
    lifecycle_state: Mapped[str] = mapped_column(String, default="active")  # prospective/active/dormant/offboarding/terminated/blocked
    approval_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    approver: Mapped[Optional[str]] = mapped_column(String, default=None)
    offboarding_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    offboarding_reason: Mapped[Optional[str]] = mapped_column(Text, default=None)
    do_not_use_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    do_not_use_reason: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ============================================================
# REQ 3 — ENGAGEMENT REGISTER (extension + child tables)
# ============================================================
class EngagementExt(Base):
    __tablename__ = "engagement_ext"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String, unique=True)  # ENG- (FK)

    # identity & linkage
    group_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    engagement_type: Mapped[Optional[str]] = mapped_column(String, default=None)
    parent_engagement: Mapped[Optional[str]] = mapped_column(String, default=None)
    related_engagements: Mapped[Optional[str]] = mapped_column(Text, default=None)  # csv

    # commercial origination
    business_justification: Mapped[Optional[str]] = mapped_column(Text, default=None)
    requested_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    procurement_category: Mapped[Optional[str]] = mapped_column(String, default=None)
    sourcing_route: Mapped[Optional[str]] = mapped_column(String, default=None)
    competitive_flag: Mapped[Optional[str]] = mapped_column(String, default=None)  # competitive/sole-source
    competitive_rationale: Mapped[Optional[str]] = mapped_column(Text, default=None)
    requisition_ref: Mapped[Optional[str]] = mapped_column(String, default=None)
    business_case_ref: Mapped[Optional[str]] = mapped_column(String, default=None)

    # contract / agreement
    contract_reference: Mapped[Optional[str]] = mapped_column(String, default=None)
    agreement_type: Mapped[Optional[str]] = mapped_column(String, default=None)  # MSA/SOW/order/NDA/DPA/amendment
    signatories: Mapped[Optional[str]] = mapped_column(Text, default=None)
    governing_law: Mapped[Optional[str]] = mapped_column(String, default=None)
    governing_language: Mapped[Optional[str]] = mapped_column(String, default=None)
    execution_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    effective_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    initial_term: Mapped[Optional[str]] = mapped_column(String, default=None)
    renewal_type: Mapped[Optional[str]] = mapped_column(String, default=None)  # auto/manual/none
    renewal_window: Mapped[Optional[str]] = mapped_column(String, default=None)
    notice_period: Mapped[Optional[str]] = mapped_column(String, default=None)
    termination_rights: Mapped[Optional[str]] = mapped_column(String, default=None)
    cure_period: Mapped[Optional[str]] = mapped_column(String, default=None)
    change_of_control: Mapped[bool] = mapped_column(Boolean, default=False)
    assignment_rights: Mapped[Optional[str]] = mapped_column(String, default=None)
    clause_flags: Mapped[Optional[str]] = mapped_column(Text, default=None)  # csv confidentiality/ip/liability/indemnity/stepin
    contract_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    contract_doc_link: Mapped[Optional[str]] = mapped_column(String, default=None)
    contract_version: Mapped[Optional[str]] = mapped_column(String, default=None)

    # scope & deliverables (header; lines in child tables)
    scope_in: Mapped[Optional[str]] = mapped_column(Text, default=None)
    scope_out: Mapped[Optional[str]] = mapped_column(Text, default=None)
    objectives: Mapped[Optional[str]] = mapped_column(Text, default=None)
    assumptions: Mapped[Optional[str]] = mapped_column(Text, default=None)
    dependencies: Mapped[Optional[str]] = mapped_column(Text, default=None)
    delivery_locations: Mapped[Optional[str]] = mapped_column(Text, default=None)
    delivery_location: Mapped[Optional[str]] = mapped_column(String, default=None)   # country (single)
    receiving_location: Mapped[Optional[str]] = mapped_column(String, default=None)  # country (single)
    change_control_ref: Mapped[Optional[str]] = mapped_column(String, default=None)

    # service definition
    service_type: Mapped[Optional[str]] = mapped_column(String, default=None)
    supported_function: Mapped[Optional[str]] = mapped_column(String, default=None)
    function_criticality: Mapped[Optional[str]] = mapped_column(String, default=None)
    ict_flag: Mapped[Optional[str]] = mapped_column(String, default=None)  # ICT/non-ICT
    integration_points: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # financial & commercial terms
    tcv: Mapped[Optional[float]] = mapped_column(Float, default=None)
    acv: Mapped[Optional[float]] = mapped_column(Float, default=None)
    pricing_model: Mapped[Optional[str]] = mapped_column(String, default=None)
    rate_card: Mapped[Optional[str]] = mapped_column(Text, default=None)
    indexation_terms: Mapped[Optional[str]] = mapped_column(String, default=None)
    payment_terms: Mapped[Optional[str]] = mapped_column(String, default=None)
    invoicing_frequency: Mapped[Optional[str]] = mapped_column(String, default=None)
    discounts: Mapped[Optional[str]] = mapped_column(String, default=None)
    fx_terms: Mapped[Optional[str]] = mapped_column(String, default=None)
    budget_allocation: Mapped[Optional[str]] = mapped_column(String, default=None)

    # procure-to-pay (rollup-ish; entered or fed)
    po_numbers: Mapped[Optional[str]] = mapped_column(Text, default=None)
    goods_receipt_ref: Mapped[Optional[str]] = mapped_column(String, default=None)
    invoice_refs: Mapped[Optional[str]] = mapped_column(Text, default=None)
    committed_spend: Mapped[Optional[float]] = mapped_column(Float, default=None)
    actual_spend: Mapped[Optional[float]] = mapped_column(Float, default=None)

    # performance & SLA (header; SLA lines in child)
    performance_reporting_cadence: Mapped[Optional[str]] = mapped_column(String, default=None)
    current_performance: Mapped[Optional[str]] = mapped_column(String, default=None)  # rollup
    sla_breach_history: Mapped[Optional[str]] = mapped_column(Text, default=None)      # rollup

    # governance & relationship
    engagement_owner: Mapped[Optional[str]] = mapped_column(String, default=None)
    vendor_account_manager: Mapped[Optional[str]] = mapped_column(String, default=None)
    governance_forum: Mapped[Optional[str]] = mapped_column(String, default=None)
    governance_cadence: Mapped[Optional[str]] = mapped_column(String, default=None)
    escalation_path: Mapped[Optional[str]] = mapped_column(Text, default=None)
    raci: Mapped[Optional[str]] = mapped_column(Text, default=None)
    relationship_sentiment: Mapped[Optional[str]] = mapped_column(String, default=None)

    # risk-scoping inputs (feed IRQ)
    data_classification: Mapped[Optional[str]] = mapped_column(String, default=None)
    data_volume: Mapped[Optional[str]] = mapped_column(String, default=None)
    personal_data: Mapped[bool] = mapped_column(Boolean, default=False)
    data_subject_types: Mapped[Optional[str]] = mapped_column(Text, default=None)
    system_access: Mapped[Optional[str]] = mapped_column(String, default=None)
    physical_access: Mapped[bool] = mapped_column(Boolean, default=False)
    mission_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    cross_border: Mapped[bool] = mapped_column(Boolean, default=False)
    regulated_activity: Mapped[bool] = mapped_column(Boolean, default=False)
    fourth_party_reliance: Mapped[Optional[str]] = mapped_column(Text, default=None)
    concentration_contribution: Mapped[Optional[str]] = mapped_column(String, default=None)

    # operational resilience (engagement-specific)
    rto: Mapped[Optional[str]] = mapped_column(String, default=None)
    rpo: Mapped[Optional[str]] = mapped_column(String, default=None)
    bcp_dependency: Mapped[Optional[str]] = mapped_column(String, default=None)
    exit_plan: Mapped[Optional[str]] = mapped_column(Text, default=None)
    exit_plan_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    transition_in_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    alternative_provider: Mapped[Optional[str]] = mapped_column(String, default=None)

    # compliance & control flags
    dpa_in_place: Mapped[bool] = mapped_column(Boolean, default=False)
    audit_rights: Mapped[bool] = mapped_column(Boolean, default=False)
    audit_last_exercised: Mapped[Optional[str]] = mapped_column(String, default=None)
    required_clauses_present: Mapped[Optional[str]] = mapped_column(String, default=None)  # links to gap engine
    insurance_evidenced: Mapped[bool] = mapped_column(Boolean, default=False)
    regulatory_notifications: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # lifecycle & status
    engagement_stage: Mapped[Optional[str]] = mapped_column(String, default="requested")
    approval_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    approver: Mapped[Optional[str]] = mapped_column(String, default=None)
    approval_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    go_live_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    next_review_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    review_cadence: Mapped[Optional[str]] = mapped_column(String, default=None)
    renewal_decision: Mapped[Optional[str]] = mapped_column(String, default=None)
    renewal_decision_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    end_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    end_reason: Mapped[Optional[str]] = mapped_column(Text, default=None)
    transition_status: Mapped[Optional[str]] = mapped_column(String, default=None)

    # escrow (source-code / payment / continuity escrow for the engagement)
    escrow_required: Mapped[bool] = mapped_column(Boolean, default=False)
    escrow_type: Mapped[Optional[str]] = mapped_column(String, default=None)        # Source code / Payment / SaaS continuity / Data
    escrow_agent: Mapped[Optional[str]] = mapped_column(String, default=None)       # provider / agent (e.g. NCC Group, Iron Mountain)
    escrow_agreement_ref: Mapped[Optional[str]] = mapped_column(String, default=None)
    escrow_status: Mapped[Optional[str]] = mapped_column(String, default=None)      # Active / Pending / Released / Lapsed / Not required
    escrow_amount: Mapped[Optional[str]] = mapped_column(String, default=None)      # free text e.g. "USD 50,000" (string avoids float-coercion)
    escrow_deposit_frequency: Mapped[Optional[str]] = mapped_column(String, default=None)
    escrow_release_conditions: Mapped[Optional[str]] = mapped_column(Text, default=None)
    escrow_last_verified: Mapped[Optional[str]] = mapped_column(String, default=None)
    escrow_beneficiaries: Mapped[Optional[str]] = mapped_column(String, default=None)
    escrow_notes: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # audit & metadata
    data_steward: Mapped[Optional[str]] = mapped_column(String, default=None)
    source_system: Mapped[Optional[str]] = mapped_column(String, default=None)
    record_version: Mapped[int] = mapped_column(Integer, default=1)
    dq_completeness: Mapped[Optional[float]] = mapped_column(Float, default=None)
    created_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EngagementDeliverable(Base):
    __tablename__ = "engagement_deliverables"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    due_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, default=None)
    accountable_owner: Mapped[Optional[str]] = mapped_column(String, default=None)
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EngagementMilestone(Base):
    __tablename__ = "engagement_milestones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    due_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    acceptance: Mapped[Optional[str]] = mapped_column(Text, default=None)
    payment_trigger: Mapped[Optional[float]] = mapped_column(Float, default=None)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EngagementSLA(Base):
    __tablename__ = "engagement_slas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String)
    metric: Mapped[str] = mapped_column(String)
    target: Mapped[Optional[str]] = mapped_column(String, default=None)
    measurement_window: Mapped[Optional[str]] = mapped_column(String, default=None)
    calculation: Mapped[Optional[str]] = mapped_column(Text, default=None)
    credit_penalty: Mapped[Optional[str]] = mapped_column(String, default=None)
    current_value: Mapped[Optional[str]] = mapped_column(String, default=None)
    breach_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EngagementObligation(Base):
    __tablename__ = "engagement_obligations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    obligated_party: Mapped[Optional[str]] = mapped_column(String, default=None)  # us/vendor
    obl_type: Mapped[str] = mapped_column(String, default="deliverable")  # payment/reporting/certification/notice/deliverable
    due_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    recurrence: Mapped[Optional[str]] = mapped_column(String, default=None)
    accountable_owner: Mapped[Optional[str]] = mapped_column(String, default=None)
    status: Mapped[str] = mapped_column(String, default="open")
    consequence: Mapped[Optional[str]] = mapped_column(Text, default=None)
    alert_rule: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EngagementPersonnel(Base):
    __tablename__ = "engagement_personnel"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[Optional[str]] = mapped_column(String, default=None)
    key_personnel: Mapped[bool] = mapped_column(Boolean, default=False)
    vetting_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    access_level: Mapped[Optional[str]] = mapped_column(String, default=None)
    location: Mapped[Optional[str]] = mapped_column(String, default=None)
    jml_status: Mapped[str] = mapped_column(String, default="active")  # joiner/active/leaver
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ============================================================
# REQ 2 — FIRST-CLASS CONTRACT ENTITY (CON-)
# ============================================================
class ContractRecord(Base):
    """A contract as a first-class entity. Link rule (master vs call-off):
    - MSA / framework  -> primary link is the Vendor (entity-level master)
    - Contract / PO / SOW / order -> primary link is the Engagement (work-specific),
      with an optional parent_msa reference back to the governing MSA.
    Both keys are always recorded where known; `primary_link` records which governs."""
    __tablename__ = "contract_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[str] = mapped_column(String, unique=True)  # CON-xxxxxx
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None)      # VEN-
    engagement_id: Mapped[Optional[str]] = mapped_column(String, default=None)  # ENG-
    parent_msa: Mapped[Optional[str]] = mapped_column(String, default=None)     # CON- of governing MSA
    primary_link: Mapped[str] = mapped_column(String, default="engagement")     # vendor | engagement

    contract_type: Mapped[str] = mapped_column(String, default="Contract")  # MSA/Framework/Contract/PO/SOW/Order/NDA/DPA
    title: Mapped[Optional[str]] = mapped_column(String, default=None)
    counterparty: Mapped[Optional[str]] = mapped_column(String, default=None)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft/active/expired/terminated
    tier: Mapped[Optional[str]] = mapped_column(String, default=None)

    governing_law: Mapped[Optional[str]] = mapped_column(String, default=None)
    effective_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    start_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    end_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    renewal_type: Mapped[Optional[str]] = mapped_column(String, default=None)
    notice_period: Mapped[Optional[str]] = mapped_column(String, default=None)
    value: Mapped[Optional[float]] = mapped_column(Float, default=None)
    currency: Mapped[Optional[str]] = mapped_column(String, default=None)

    terms_json: Mapped[str] = mapped_column(Text, default="{}")     # required-terms snapshot
    gap_review: Mapped[Optional[str]] = mapped_column(Text, default=None)
    clause_flags: Mapped[Optional[str]] = mapped_column(Text, default=None)
    doc_link: Mapped[Optional[str]] = mapped_column(String, default=None)
    version: Mapped[Optional[str]] = mapped_column(String, default=None)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)  # set by Critical Vendors module (R3)

    source: Mapped[Optional[str]] = mapped_column(String, default=None)  # manual/engine/migrated-v1
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ============================================================
# REQ 3 — CRITICAL VENDORS MODULE
# ============================================================
class EngagementCriticalityInput(Base):
    """The four criticality parameters, scored 1-5, per engagement.
    Higher score = more critical. These feed the deterministic engine."""
    __tablename__ = "engagement_criticality_input"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String, unique=True)
    customer_impact: Mapped[Optional[int]] = mapped_column(Integer, default=None)        # impact on customer
    downtime_tolerance: Mapped[Optional[int]] = mapped_column(Integer, default=None)     # LOW tolerance = HIGH score
    alternative_availability: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # FEW alternatives = HIGH score
    substitution_complexity: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # HARD = HIGH score
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CriticalityDesignation(Base):
    """Designation record for an engagement or a vendor. Time-stamped and audited.
    `auto` distinguishes engine-driven designation from a manual override."""
    __tablename__ = "criticality_designation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_type: Mapped[str] = mapped_column(String)   # engagement | vendor
    subject_id: Mapped[str] = mapped_column(String)     # ENG- | VEN-
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    rationale: Mapped[Optional[str]] = mapped_column(Text, default=None)
    auto: Mapped[bool] = mapped_column(Boolean, default=True)   # False = manual override
    overridden_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    designated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ============================================================
# REQ 4 — VENDOR PERFORMANCE MANAGEMENT (scoped to critical vendors)
# ============================================================
class VendorScorecard(Base):
    """One scorecard per critical vendor per measurement period."""
    __tablename__ = "vendor_scorecard"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scorecard_id: Mapped[str] = mapped_column(String, unique=True)  # SCD-xxxxxx
    vendor_id: Mapped[str] = mapped_column(String)
    period_label: Mapped[str] = mapped_column(String)               # e.g. 2026-Q2
    period_start: Mapped[Optional[str]] = mapped_column(String, default=None)
    period_end: Mapped[Optional[str]] = mapped_column(String, default=None)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft/agreed/in-measurement/in-review/published/closed
    composite_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    band: Mapped[Optional[str]] = mapped_column(String, default=None)
    review_cadence: Mapped[str] = mapped_column(String, default="quarterly")
    critical_engagements: Mapped[Optional[str]] = mapped_column(Text, default=None)  # csv of ENG-
    agreed_with_vendor: Mapped[bool] = mapped_column(Boolean, default=False)
    agreed_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    agreed_party: Mapped[Optional[str]] = mapped_column(String, default=None)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    published_at: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ScorecardDimension(Base):
    __tablename__ = "scorecard_dimension"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scorecard_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)   # operational/financial_value/relationship/compliance_risk/financial_stability/esg/innovation
    weight: Mapped[float] = mapped_column(Float, default=0.0)  # percent (0-100)
    score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ScorecardKPI(Base):
    __tablename__ = "scorecard_kpi"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scorecard_id: Mapped[str] = mapped_column(String)
    dimension: Mapped[str] = mapped_column(String)
    metric: Mapped[str] = mapped_column(String)
    definition: Mapped[Optional[str]] = mapped_column(Text, default=None)
    target: Mapped[Optional[str]] = mapped_column(String, default=None)
    window: Mapped[Optional[str]] = mapped_column(String, default=None)
    method: Mapped[Optional[str]] = mapped_column(String, default=None)
    data_source: Mapped[Optional[str]] = mapped_column(String, default=None)  # auto/manual/vendor
    weight: Mapped[float] = mapped_column(Float, default=1.0)  # within dimension
    actual: Mapped[Optional[str]] = mapped_column(String, default=None)
    auto_value: Mapped[Optional[str]] = mapped_column(String, default=None)
    score: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # 1-5
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_reason: Mapped[Optional[str]] = mapped_column(String, default=None)


class PerformanceReview(Base):
    __tablename__ = "performance_review"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(String, unique=True)  # PRV-xxxxxx
    vendor_id: Mapped[str] = mapped_column(String)
    scorecard_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    review_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    cadence: Mapped[Optional[str]] = mapped_column(String, default="quarterly")
    attendees: Mapped[Optional[str]] = mapped_column(Text, default=None)
    summary: Mapped[Optional[str]] = mapped_column(Text, default=None)
    outcomes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    vendor_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    vendor_ack_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    next_review_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PerfEnrolment(Base):
    """CR-11: explicit enrolment of a vendor into performance management.
    Performance is no longer restricted to critical vendors; any vendor can be
    enrolled. Critical vendors are auto-enrolled (source='auto-critical') but a
    user may add any vendor manually (source='manual')."""
    __tablename__ = "perf_enrolment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, unique=True)
    enrolled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String, default="manual")  # manual | auto-critical
    enrolled_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
