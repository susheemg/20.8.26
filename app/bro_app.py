"""
The complete BRO Risk Oracle application (FastAPI), all features included.

Wires every feature group onto the tested foundations:
  - persistence + RBAC          (Group A)
  - core lifecycle + scoring    (Group B, ported engine)
  - four intelligence engines   (Group C, deterministic-local)
  - monitoring lifecycle        (Group D)
  - notifications + email + webhooks (Group E)
  - conversational + autopilot  (Group F)
  - admin + MCP tools + procurement (Group G)

Persistence is SQLAlchemy on SQLite by default (runs offline) or Postgres via
BRO_DB_URL. Auth is a simple bearer/session actor for API use. Every
consequential mutation appends to the hash-chained audit log.
"""
from __future__ import annotations

import json
import re as _re

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = _re.compile(r"^\+?[0-9]+$")

def _can_view_assessment(u, a) -> bool:
    """CR-3: assessment record visibility by role.
    - admin (reviewer) and vrm (assessor): see ALL records
    - buyer (business user): see ONLY their own (owner / SPOC)
    - vendor: see NONE
    """
    role = getattr(getattr(u, "role", None), "key", None)
    if role in ("admin", "vrm"):
        return True
    if role == "vendor":
        return False
    if role == "buyer":
        return u.username in (a.engagement_owner, a.spoc_user)
    return u.username in (a.engagement_owner, a.spoc_user, a.assessor_user)

def _validate_typed_fields(data: dict):
    """CR-8: server-side validation backing the typed inputs. Returns an error
    string if any email/phone/date value is malformed, else None. Empty values pass."""
    for k, v in (data or {}).items():
        if v in (None, "", []):
            continue
        key = str(k).lower()
        sval = str(v)
        if "email" in key and not _EMAIL_RE.match(sval):
            return f"'{k}' must be a valid email address"
        if _re.search(r"phone|telephone|mobile|contact_number", key) and not _PHONE_RE.match(sval):
            return f"'{k}' may contain only '+' and digits"
        if _re.search(r"date$|_date|dob$", key):
            if not _re.match(r"^\d{4}-\d{2}-\d{2}$", sval):
                return f"'{k}' must be a valid date (YYYY-MM-DD)"
    return None
from typing import Optional, Union

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.assessment import prompts as PROMPTS
from app.features.admin import security as SEC
from app.features.assessment import bro_engine as eng
from app.features.intelligence import intel
from app.features.domain.models_db import (
    Base, EngagementRow, Role, User, Vendor,
    make_engine, make_session_factory, verify_password,
)
from app.features.domain.models_feature import (
    Acceptance, AuditLog, Certification, Contract, ConversationMessage,
    ConversationSession, Document, EmailOutbox, Finding, FourthParty,
    Incident, IntelResult, MethodologyVersion, Monitoring, Notification,
    Offboarding, Reassessment, Webhook,
)
from app.features.admin.rbac import has_permission, seed
from app.features.admin.auth import bearer_subject, issue_token, TokenError


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line.
    Never raises — observability must not change control flow."""
    try:
        from app.features.admin.security import log_json as _lj
    except Exception:
        try:
            from app.features.admin.security import log_json as _lj
        except Exception:
            return
    try:
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass



# ---------- request schemas ----------

class VendorIn(BaseModel):
    name: str
    industry: Optional[str] = None
    country: Optional[str] = None
    contact_email: Optional[str] = None
    tier: str = "Tier 3"

class CriticalIn(BaseModel):
    reason: str

class EngagementIn(BaseModel):
    vendor_id: int
    title: str
    service_description: Optional[str] = None
    business_contact_email: Optional[str] = None

class IRQIn(BaseModel):
    answers: dict

class DDQIn(BaseModel):
    answers: dict

class AiKeyIn(BaseModel):
    provider: str = "claude"
    api_key: str = ""
    model: str = ""

class ExitPlanIn(BaseModel):
    exit_mode: Optional[str] = None
    strategy_type: Optional[str] = None
    rationale: Optional[str] = None
    target_window: Optional[str] = None
    impact_summary: Optional[str] = None
    data_plan: Optional[str] = None
    comms_plan: Optional[str] = None
    owner: Optional[str] = None
    approver: Optional[str] = None
    status: Optional[str] = None
    one_off_cost: Optional[float] = None
    dual_running_cost: Optional[float] = None
    penalty_cost: Optional[float] = None

class ExitChildIn(BaseModel):
    kind: str
    name: Optional[str] = None
    prequalified: Optional[bool] = False
    lead_time_days: Optional[int] = None
    viability: Optional[int] = 3
    note: Optional[str] = ""
    description: Optional[str] = None
    owner: Optional[str] = ""
    duration_days: Optional[int] = None
    rto: Optional[str] = ""
    rpo: Optional[str] = ""
    dependency: Optional[str] = ""
    service_name: Optional[str] = None
    impact_tolerance: Optional[str] = ""
    max_downtime: Optional[str] = ""
    criticality: Optional[str] = "Important"

class ExitTestIn(BaseModel):
    method: str = "tabletop"
    outcome: str = ""
    lessons: str = ""
    participants: str = ""
    passed: bool = True

class ExitInvokeIn(BaseModel):
    mode: str = "planned"

class MethodologyIn(BaseModel):
    title: str = "Methodology"
    content_text: Optional[str] = None
    data_b64: Optional[str] = None
    filename: Optional[str] = None

class ActiveIn(BaseModel):
    active: bool = True

class AIResearchIn(BaseModel):
    deep: Optional[bool] = False
    vendor_id: Optional[str] = None
    company: Optional[str] = None
    jurisdiction: Optional[str] = "UK"
    identifier: Optional[str] = ""

class OverrideIn(BaseModel):
    band: str
    reason: str
    second_approver: str

class FindingIn(BaseModel):
    engagement_id: Optional[int] = None
    title: str
    severity: str = "medium"

class IntelIn(BaseModel):
    vendor_id: int
    payload: dict = {}

class LoginIn(BaseModel):
    username: str
    password: str

class ChatStart(BaseModel):
    engagement_id: Optional[int] = None
    actor_role: str = "assessor"

class ChatTurn(BaseModel):
    session_id: int
    message: str

class MethIn(BaseModel):
    version: str
    note: Optional[str] = None

class POIn(BaseModel):
    vendor_name: str
    amount: float
    ext_ref: Optional[str] = None

class CertIn(BaseModel):
    vendor_id: int
    name: str
    valid_until: Optional[str] = None

class DocIn(BaseModel):
    vendor_id: Optional[int] = None
    engagement_id: Optional[int] = None
    name: str
    doc_type: str = "other"
    next_validation: Optional[str] = None

class FourthIn(BaseModel):
    vendor_id: int
    name: str
    service: Optional[str] = None

class AcceptIn(BaseModel):
    engagement_id: int
    rationale: str
    expires_at: Optional[str] = None

class ReassessIn(BaseModel):
    engagement_id: int
    mode: str = "periodic"

# --- new: CRUD / admin / self-service schemas ---
class VendorUpdateIn(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    contact_email: Optional[str] = None
    tier: Optional[str] = None

class EngagementUpdateIn(BaseModel):
    title: Optional[str] = None
    service_description: Optional[str] = None
    business_contact_email: Optional[str] = None

class FindingUpdateIn(BaseModel):
    title: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None

class UserIn(BaseModel):
    username: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    password: str
    role_key: str

class UserUpdateIn(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role_key: Optional[str] = None
    is_active: Optional[bool] = None

class SupplierUserIn(BaseModel):
    username: str
    full_name: Optional[str] = None
    email: str
    password: str
    vendor_id: str
    is_backup: Optional[bool] = False


class SupplierUserUpdateIn(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    is_backup: Optional[bool] = None
    password: Optional[str] = None


class RbacCellIn(BaseModel):
    role_key: str
    perm_key: str
    access: str            # read | write | modify | denied


class NotifTemplateIn(BaseModel):
    name: str
    subject: Optional[str] = ""
    body: Optional[str] = ""
    groups: Optional[list] = None


class NotifTemplateUpdateIn(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    groups: Optional[list] = None
    enabled: Optional[bool] = None


class RolePermsIn(BaseModel):
    permission_keys: list[str]

class PasswordIn(BaseModel):
    current_password: str
    new_password: str

class ProfileIn(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    secondary_email: Optional[str] = None
    timezone: Optional[str] = None

class WebhookIn(BaseModel):
    url: str
    event: str = "*"

class SignoffIn(BaseModel):
    decision: str = "approved"
    note: Optional[str] = None

class EmailIn(BaseModel):
    to_addr: str
    subject: str
    body: str

class ChatSessionIn(BaseModel):
    engagement_id: Optional[int] = None

class ChatSendIn(BaseModel):
    deep: Optional[bool] = False
    session_id: int
    message: str
    agent: Optional[str] = None

class LearningIn(BaseModel):
    rating: int = 3
    agent: Optional[str] = None
    stage: int = 0
    issue: Optional[str] = None
    note: Optional[str] = None

# --- v2 registry schemas ---
class V2VendorIn(BaseModel):
    legal_name: str
    trading_name: Optional[str] = None
    registration_number: Optional[str] = None
    hq_country: Optional[str] = None
    website: Optional[str] = None
    listing_status: Optional[str] = None
    tier: Optional[str] = "Tier 3"
    group_id: Optional[str] = None
    parent_company: Optional[str] = None
    industries: Optional[list[str]] = None
    procurement_ref: Optional[str] = None
    created_via: Optional[str] = "button"

class GroupOverrideIn(BaseModel):
    group_id: str

class V2ContactIn(BaseModel):
    owner_type: str
    owner_id: str
    name: str
    is_primary: bool = False
    email: Optional[str] = None
    phone_country_code: Optional[str] = None
    phone_number: Optional[str] = None
    designation: Optional[str] = None
    country: Optional[str] = None
    mailing_address: Optional[str] = None

class V2EngagementIn(BaseModel):
    vendor_id: str
    title: str
    service_description: Optional[str] = None
    material_group_id: Optional[str] = None
    business_unit: Optional[str] = None
    deployment_model: Optional[str] = None
    owner_user: Optional[str] = None
    annual_value: Optional[float] = None
    currency: Optional[str] = None

class V2AssessmentIn(BaseModel):
    engagement_id: str
    vendor_id: Optional[str] = None
    session_id: Optional[int] = None
    inherent_band: Optional[str] = None
    residual_band: Optional[str] = None

class ReassignIn(BaseModel):
    assessor_user: str

class V2FindingIn(BaseModel):
    title: str
    severity: Optional[str] = "Medium"
    source: Optional[str] = "Assessor"
    description: Optional[str] = None
    domain: Optional[str] = None
    engagement_id: Optional[str] = None
    vendor_id: Optional[str] = None
    assessment_id: Optional[str] = None
    due_date: Optional[str] = None
    owner: Optional[str] = None
    assessor: Optional[str] = None
    suggested_remediation: Optional[str] = None
    suggested_closure: Optional[str] = None
    status: Optional[str] = None

class FindingPatchIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    assessor: Optional[str] = None
    suggested_remediation: Optional[str] = None
    suggested_closure: Optional[str] = None
    due_date: Optional[str] = None

class RiskAcceptIn(BaseModel):
    rationale: str
    expiry_date: str
    accept: Optional[bool] = True

class FindingNoteIn(BaseModel):
    note: str

class FindingAttachIn(BaseModel):
    doc_id: str
    name: Optional[str] = None

class AssignAssessorIn(BaseModel):
    assessor_user: str

class ConnectorPullIn(BaseModel):
    vendor_id: Optional[str] = None
    company: Optional[str] = None

class ConnectorWebhookIn(BaseModel):
    vendor_id: Optional[str] = None
    payload: Optional[dict] = None

class RegExportIn(BaseModel):
    codes: list
    updates: Optional[list] = None

class RegRefreshIn(BaseModel):
    codes: list

class RegAssessIn(BaseModel):
    codes: list
    doc_text: Optional[str] = ""
    industry: Optional[str] = None

class RegRelevanceIn(BaseModel):
    codes: list
    industry: Optional[dict] = None

class RegReportExportIn(BaseModel):
    report: dict

class IntegritySweepIn(BaseModel):
    limit: Optional[int] = None
    vendor_ids: Optional[list] = None

class IntegrityFixIn(BaseModel):
    vendor_id: str
    field: str
    value: Optional[str] = None

class IntegrityMergeIn(BaseModel):
    primary_vendor_id: str
    duplicate_vendor_id: str

class IntegrityVendorIn(BaseModel):
    vendor_id: str

class ContagionIn(BaseModel):
    node_type: str   # fourth_party | owner | vendor
    node_id: str

class IncidentMatchIn(BaseModel):
    vendor_id: str
    description: Optional[str] = ""
    domain: Optional[str] = None

class BriefIn(BaseModel):
    business_unit: str

class I18nTranslateIn(BaseModel):
    strings: list
    lang: str

class I18nTextIn(BaseModel):
    text: str
    lang: Optional[str] = None

class IncidentIn(BaseModel):
    date_of_incident: Optional[str] = None
    reported_date: Optional[str] = None
    reported_by: Optional[str] = None
    vendor_id: Optional[str] = None
    engagement_id: Optional[str] = None
    incident_type: Optional[str] = None
    severity: Optional[str] = "Medium"
    customer_impacting: Optional[bool] = False
    impacts_client_org: Optional[bool] = False
    impact_description: Optional[str] = None
    region: Optional[list] = None
    root_cause_assessment: Optional[str] = None
    risk_entry_needed: Optional[bool] = False
    status: Optional[str] = None
    vendor_notified_at: Optional[str] = None
    notification_sla_hours: Optional[int] = None

class IncidentNoteIn(BaseModel):
    note: str

class IncidentAttachIn(BaseModel):
    name: str

class ScenarioIn(BaseModel):
    node_type: str = "fourth_party"
    node_id: str
    hours: int = 24

class V2RemediationIn(BaseModel):
    finding_id: str
    plan: str
    owner: Optional[str] = None
    target_date: Optional[str] = None

class V2FourthPartyIn(BaseModel):
    legal_name: str
    service_provided: Optional[str] = None
    hq_country: Optional[str] = None
    vendor_ids: Optional[list[str]] = None
    vendor_id: Optional[str] = None

class V2ArtefactIn(BaseModel):
    vendor_id: str
    name: str
    artefact_type: Optional[str] = "certificate"
    expiry_date: Optional[str] = None
    issue_date: Optional[str] = None
    engagement_id: Optional[str] = None
    received_via: Optional[str] = "upload"
    supersedes: Optional[str] = None

class FinancialIn(BaseModel):
    deep: Optional[bool] = False
    figures: dict
    flags: Optional[dict] = None
    vendor_id: Optional[str] = None
    other_name: Optional[str] = None

class ReputationIn(BaseModel):
    deep: Optional[bool] = False
    events: Optional[list[dict]] = None
    customer_facing: bool = False
    vendor_id: Optional[str] = None
    other_name: Optional[str] = None

class ConfigSetIn(BaseModel):
    value: Union[int, float, str]

class NavOrderIn(BaseModel):
    order: Optional[dict] = None

class ContractTermsIn(BaseModel):
    inherent_band: str = "MODERATE"
    exposure: Optional[dict] = None
    vendor_id: Optional[str] = None
    other_name: Optional[str] = None

class ContractGapIn(BaseModel):
    contract_text: str
    inherent_band: str = "MODERATE"
    exposure: Optional[dict] = None

class ContractDiffIn(BaseModel):
    inherent_band: str = "MODERATE"
    exposure: Optional[dict] = None
    prior_contract_texts: list[str]

class MgmtChatIn(BaseModel):
    deep: Optional[bool] = False
    question: str
    history: Optional[list] = None

class BoardFollowupIn(BaseModel):
    deep: Optional[bool] = False
    question: str
    history: Optional[list] = None

class PRPullIn(BaseModel):
    pr_number: str

class SimilarIn(BaseModel):
    entity: Optional[str] = None
    scope: Optional[str] = None

class CaptureIn(BaseModel):
    session_id: int
    engagement_id: str
    vendor_id: Optional[str] = None

class EmailIntakeIn(BaseModel):
    sender: str
    subject: Optional[str] = None
    attachment_name: Optional[str] = None
    attachment_b64: Optional[str] = None
    body_text: Optional[str] = None
    vendor_id: Optional[str] = None

class _DocFile(BaseModel):
    filename: str
    content_type: Optional[str] = "application/octet-stream"
    data_b64: str

class DocUploadIn(BaseModel):
    files: list[_DocFile]
    vendor_id: Optional[str] = None
    engagement_id: Optional[str] = None
    purpose: Optional[str] = None

class CertIngestIn(BaseModel):
    files: list[_DocFile]
    vendor_id: str
    engagement_id: Optional[str] = None

class ContractGapDocIn(BaseModel):
    file: _DocFile
    engagement_id: Optional[str] = None
    vendor_id: Optional[str] = None
    other_name: Optional[str] = None
    inherent_band: Optional[str] = None

class PeerBenchmarkIn(BaseModel):
    figures: dict
    flags: Optional[dict] = None
    sector: str = "other"

class FinResearchIn(BaseModel):
    deep: Optional[bool] = False
    company: str
    jurisdiction: str = "UK"
    identifier: Optional[str] = ""
    year: Optional[str] = ""

class FinMonitorAddIn(BaseModel):
    vendor_id: Optional[str] = None
    other_name: Optional[str] = None

class FinMonitorSweepIn(BaseModel):
    monitor_id: Optional[int] = None   # sweep one, or all if None

# ---- Req 1/2/3 schemas ----
class VendorMasterIn(BaseModel):
    data: dict
    include_bank: bool = False

class ScreeningIn(BaseModel):
    screen_type: str
    result: Optional[str] = None
    detail: Optional[str] = None
    screened_date: Optional[str] = None
    next_due: Optional[str] = None

class AttrDomainIn(BaseModel):
    data: dict

class InsuranceIn(BaseModel):
    policy_type: str
    coverage_limit: Optional[float] = None
    currency: Optional[str] = None
    insurer: Optional[str] = None
    certificate_expiry: Optional[str] = None
    named_insured_verified: bool = False

class MonitorSignalIn(BaseModel):
    signal_type: str
    value: str
    source: Optional[str] = None

class EngExtIn(BaseModel):
    data: dict

class EngChildIn(BaseModel):
    kind: str   # deliverable/milestone/sla/obligation/personnel
    data: dict

# ---- R2 contract entity schemas ----
class ContractCreateIn(BaseModel):
    contract_type: str = "Contract"
    vendor_id: Optional[str] = None
    engagement_id: Optional[str] = None
    parent_msa: Optional[str] = None
    data: Optional[dict] = None

class ContractUpdateIn(BaseModel):
    data: dict

# ---- R3 critical vendors schemas ----
class CriticalityInputIn(BaseModel):
    customer_impact: Optional[int] = None
    downtime_tolerance: Optional[int] = None
    alternative_availability: Optional[int] = None
    substitution_complexity: Optional[int] = None

class CriticalAnalysisIn(BaseModel):
    vendor_id: Optional[str] = None

class CriticalOverrideIn(BaseModel):
    is_critical: bool
    reason: str

# ---- R4 performance management schemas ----
class ScorecardCreateIn(BaseModel):
    vendor_id: str
    period_label: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    cadence: str = "quarterly"

class PerfEnrolIn(BaseModel):
    vendor_ids: list[str]

class KPIScoreIn(BaseModel):
    actual: Optional[str] = None
    score: Optional[int] = None
    excluded: Optional[bool] = None
    exclude_reason: Optional[str] = None

class AgreeIn(BaseModel):
    party: str

class ReviewIn(BaseModel):
    data: dict

class PerfCapaIn(BaseModel):
    scorecard_id: str
    gap: str
    owner: str
    due_date: Optional[str] = None

class CapaVerifyIn(BaseModel):
    evidence: str

# ---- R5 ProAssess schemas ----
class ProAssessRunIn(BaseModel):
    deep: Optional[bool] = False
    vendor_id: Optional[str] = None
    engagement_id: Optional[str] = None
    irq: Optional[dict] = None
    ddq: Optional[dict] = None
    documents: Optional[list] = None
    extracted: Optional[dict] = None   # LLM-extracted structured inputs (financials, reputation_events, flags)

class ProAssessRegisterIn(BaseModel):
    report: dict

class ProAssessAutoIn(BaseModel):
    deep: Optional[bool] = False
    free_text: Optional[str] = ""
    documents: Optional[list] = None        # [{filename, content_type, data_b64}]
    vendor_id: Optional[str] = None         # existing vendor, OR:
    new_vendor_name: Optional[str] = None   # create a new vendor
    engagement_title: Optional[str] = None
    ddq: Optional[dict] = None
    create_records: bool = True


class SLAIn(BaseModel):
    engagement_id: str
    vendor_id: Optional[str] = None
    description: str
    threshold_type: Optional[str] = "min"
    threshold: float = 0.0
    unit: Optional[str] = ""
    baseline: Optional[float] = None
    window: Optional[str] = "monthly"
    source: Optional[str] = "manual"
    contract_id: Optional[str] = None


class SLAEditIn(BaseModel):
    description: Optional[str] = None
    threshold_type: Optional[str] = None
    threshold: Optional[float] = None
    unit: Optional[str] = None
    baseline: Optional[float] = None
    window: Optional[str] = None
    active: Optional[bool] = None


class MeasurementIn(BaseModel):
    period: str
    value: Optional[float] = None


class ExtractIn(BaseModel):
    engagement_id: str
    vendor_id: Optional[str] = None
    mode: Optional[str] = "contract"
    contract_id: Optional[str] = None


class EnquiryIn(BaseModel):
    engagement_id: str
    question: str


class PerfIssueIn(BaseModel):
    engagement_id: str
    vendor_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = "Medium"
    source: Optional[str] = "Manual"
    status: Optional[str] = "Open"
    owner: Optional[str] = None
    due_date: Optional[str] = None
    linked_ref: Optional[str] = None
    suggested_remediation: Optional[str] = None


class PerfIssueEditIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[str] = None
    linked_ref: Optional[str] = None
    suggested_remediation: Optional[str] = None
    risk_accepted: Optional[bool] = None
    acceptance_rationale: Optional[str] = None


class NoteIn(BaseModel):
    note: str


class RaiseFromSLAIn(BaseModel):
    sla_id: str


class LearningIn(BaseModel):
    category: str = "Risk pattern"
    insight: str
    confidence: Optional[str] = "Medium"
    source_engagement: Optional[str] = None
    source_vendor: Optional[str] = None


class ConnectorConfigIn(BaseModel):
    enabled: Optional[bool] = None
    base_url: Optional[str] = None
    secret_name: Optional[str] = None
    config: Optional[dict] = None


class ConnectorSyncIn(BaseModel):
    vendor_id: Optional[str] = None       # one vendor; omit for all
    vendor_ids: Optional[list] = None     # explicit set


class ContentSetIn(BaseModel):
    value: str


class ContentCustomIn(BaseModel):
    source_text: str
    value: str


class ContentImportIn(BaseModel):
    data: dict

class LayoutItemIn(BaseModel):
    hidden: Optional[bool] = None
    order: Optional[int] = None


class LayoutReorderIn(BaseModel):
    slug: str
    order: list


ALEMBIC_EXPECTED_HEAD = "access_scope_1"
# db_hardening_2_pg adds PostgreSQL foreign keys and CHECK constraints. It is opt-in
# and PostgreSQL-only, so a database sitting on it is correctly ahead of the baseline
# rather than mismatched — accept it without warning.
ALEMBIC_ACCEPTED_REVISIONS = {"db_hardening_1", "db_hardening_2_pg", "access_scope_1"}

import logging as _logging
_log = _logging.getLogger("brata.schema")


def _schema_revision_check(engine, created_fresh: bool = False) -> dict:
    """Reconcile the two schema-provisioning paths (DB-01).

    The application can build its schema either with ``create_all`` (fast, used for
    dev and demo databases) or with Alembic (authoritative, used for anything with
    real data). These produce different results when a change lives only in a
    migration, and a create_all database has no revision stamp at all — so Alembic
    cannot safely upgrade it later.

    On a freshly created database we stamp the expected head, so the two paths
    converge. On an existing database we compare and log; we never rewrite a stamp we
    did not create, because guessing another operator's migration state is worse than
    reporting the mismatch.
    """
    out = {"expected": ALEMBIC_EXPECTED_HEAD, "actual": None, "action": "none"}
    try:
        from sqlalchemy import inspect as _i, text as _t
        insp = _i(engine)
        has_stamp = "alembic_version" in insp.get_table_names()
        if has_stamp:
            with engine.connect() as c:
                row = c.execute(_t("SELECT version_num FROM alembic_version")).fetchone()
                out["actual"] = row[0] if row else None
        if created_fresh and not has_stamp:
            with engine.begin() as c:
                c.exec_driver_sql(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) NOT NULL)")
                c.exec_driver_sql("DELETE FROM alembic_version")
                c.exec_driver_sql(
                    f"INSERT INTO alembic_version (version_num) VALUES "
                    f"('{ALEMBIC_EXPECTED_HEAD}')")
            out.update(actual=ALEMBIC_EXPECTED_HEAD, action="stamped_fresh")
        elif not has_stamp:
            out["action"] = "unstamped_existing"
            _log.warning(
                "SCHEMA: database has no Alembic stamp. It was built by create_all and "
                "cannot be upgraded by `alembic upgrade head` until it is stamped. "
                "Verify the schema, then run: alembic stamp %s", ALEMBIC_EXPECTED_HEAD)
        elif out["actual"] not in ALEMBIC_ACCEPTED_REVISIONS:
            out["action"] = "revision_mismatch"
            _log.warning(
                "SCHEMA: database revision %s is not one this build recognises (%s). "
                "Run `alembic upgrade head` before serving traffic.",
                out["actual"], ", ".join(sorted(ALEMBIC_ACCEPTED_REVISIONS)))
    except Exception as e:  # never block boot on a diagnostic
        out["action"] = f"check_failed: {type(e).__name__}"
    return out


def create_app(db_url: Optional[str] = None) -> FastAPI:
    engine = make_engine(db_url or "sqlite:///:memory:")
    # ensure registry models are imported so their tables register on Base
    from app.features.domain import registry_models as _rm  # noqa: F401
    from app.features.domain import master_ext as _mx  # noqa: F401  (Req 1/2/3 tables)
    from app.features.lifecycle import documents as _docs  # noqa: F401  (CR-4/5/12 document store)
    from app.features.lifecycle import exit_planning as _exit  # noqa: F401  (vendor exit strategy)
    from app.features.assessment import methodology as _meth  # noqa: F401  (admin methodology library)
    from app.features.domain import config_store as _cfg  # noqa: F401  (system configuration store)
    from app.features.lifecycle import performance_models as _perf  # noqa: F401  (SLA + performance issues)
    from app.features.platform import platform_docs as _pdocs  # noqa: F401  (SOP/TDA + version history)
    from app.features.assessment import learnings as _learn  # noqa: F401  (platform learnings log)
    from app.features.admin import integrations as _integ  # noqa: F401  (external connector suite)
    from app.features.admin import content as _content  # noqa: F401  (content studio overrides)
    from app.features.admin import layout as _layout  # noqa: F401  (nav & layout config)
    # Dev/demo bootstrap creates tables directly. In production set
    # BRO_DB_AUTO_CREATE=0 and manage schema with Alembic (`alembic upgrade head`).
    if _os.environ.get("BRO_DB_AUTO_CREATE", "1") != "0":
        try:
            from sqlalchemy import inspect as _insp0
            _fresh_db = not _insp0(engine).get_table_names()
        except Exception:
            _fresh_db = False
        Base.metadata.create_all(engine)
        # self-healing: add graded-access column to older databases where
        # create_all cannot ALTER an existing table (enterprise in-place upgrade)
        try:
            from sqlalchemy import inspect as _inspect
            _insp = _inspect(engine)
            if "role_permissions" in _insp.get_table_names():
                _cols = {c["name"] for c in _insp.get_columns("role_permissions")}
                if "access" not in _cols:
                    with engine.begin() as _conn:
                        _conn.exec_driver_sql(
                            "ALTER TABLE role_permissions ADD COLUMN access VARCHAR DEFAULT 'modify'")
            if "users" in _insp.get_table_names():
                _ucols = {c["name"] for c in _insp.get_columns("users")}
                with engine.begin() as _conn:
                    if "vendor_id" not in _ucols:
                        _conn.exec_driver_sql("ALTER TABLE users ADD COLUMN vendor_id VARCHAR")
                    if "is_backup" not in _ucols:
                        _conn.exec_driver_sql("ALTER TABLE users ADD COLUMN is_backup BOOLEAN DEFAULT 0")
                    if "managed_by" not in _ucols:
                        _conn.exec_driver_sql("ALTER TABLE users ADD COLUMN managed_by VARCHAR")
                    if "phone" not in _ucols:
                        _conn.exec_driver_sql("ALTER TABLE users ADD COLUMN phone VARCHAR")
                    if "secondary_email" not in _ucols:
                        _conn.exec_driver_sql("ALTER TABLE users ADD COLUMN secondary_email VARCHAR")
                    if "timezone" not in _ucols:
                        _conn.exec_driver_sql("ALTER TABLE users ADD COLUMN timezone VARCHAR")
                    if "business_unit" not in _ucols:
                        _conn.exec_driver_sql("ALTER TABLE users ADD COLUMN business_unit VARCHAR")
            # v4.25.8: conversation session provenance (owner, subject, status) so
            # unfinished chats can be listed, resumed and access-scoped.
            if "conversation_sessions" in _insp.get_table_names():
                _ccols = {c["name"] for c in _insp.get_columns("conversation_sessions")}
                with engine.begin() as _conn:
                    for _c, _t in (("created_by", "VARCHAR"), ("business_unit", "VARCHAR"),
                                   ("vendor_id", "VARCHAR"), ("subject_label", "VARCHAR"),
                                   ("status", "VARCHAR"), ("updated_at", "DATETIME"),
                                   ("assigned_to", "VARCHAR"), ("assigned_by", "VARCHAR"),
                                   ("assigned_at", "DATETIME")):
                        if _c not in _ccols:
                            _conn.exec_driver_sql(
                                f"ALTER TABLE conversation_sessions ADD COLUMN {_c} {_t}")
                    if "status" not in _ccols:
                        _conn.exec_driver_sql(
                            "UPDATE conversation_sessions SET status='active' WHERE status IS NULL")
                    if "updated_at" not in _ccols:
                        _conn.exec_driver_sql(
                            "UPDATE conversation_sessions SET updated_at=created_at "
                            "WHERE updated_at IS NULL")
            # DB-03: audit subject columns on databases created before this release.
            # create_all cannot ALTER, and dev/demo databases are not Alembic-managed,
            # so add the columns and backfill them from the payload already stored.
            if "audit_log" in _insp.get_table_names():
                _acols = {c["name"] for c in _insp.get_columns("audit_log")}
                with engine.begin() as _conn:
                    for _c, _pfx in (("vendor_id", "VEN-"), ("engagement_id", "ENG-")):
                        if _c not in _acols:
                            _conn.exec_driver_sql(
                                f"ALTER TABLE audit_log ADD COLUMN {_c} VARCHAR")
                            _conn.exec_driver_sql(f"""
                                UPDATE audit_log SET {_c} = substr(
                                    detail,
                                    instr(detail, '"{_c}": "{_pfx}') + length('"{_c}": "'),
                                    10)
                                WHERE detail LIKE '%"{_c}": "{_pfx}%'
                            """) if engine.dialect.name == "sqlite" else None
        except Exception:
            pass
        # DB-01: a database built by create_all carries no Alembic stamp, so a later
        # `alembic upgrade head` would try to replay migrations against tables that
        # already exist. Stamp a freshly-created database at head so the two
        # provisioning paths converge, and warn loudly when an existing database is
        # at a different revision than this build expects — silent divergence between
        # environments is the actual hazard, not divergence itself.
        _schema_revision_check(engine, created_fresh=_fresh_db)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as s:
        seed(s)
        from app.features.domain.registry_service import seed_masters
        seed_masters(s)
        from app.features.domain.watchlist_service import seed_criteria as _seed_wl
        _seed_wl(s)
        _cfg.seed_defaults(s)
        # seed default notification templates (editable by admins)
        try:
            from app.features.admin import notifications as _notif
            _notif.seed_templates(s)
        except Exception:
            pass
        # upgrade-safe: grant the new supplier.manage permission to assessor + controller
        # (seed only refreshes the admin ALL-role, so existing installs need this once).
        try:
            from app.features.domain.models_db import Role, Permission, RolePermission
            _sp = s.scalars(select(Permission).where(Permission.key == "supplier.manage")).first()
            if _sp:
                for _rk in ("vrm", "controller"):
                    _role = s.scalars(select(Role).where(Role.key == _rk)).first()
                    if _role and not s.get(RolePermission, (_role.id, _sp.id)):
                        s.add(RolePermission(role_id=_role.id, perm_id=_sp.id, access="modify"))
                s.commit()
        except Exception:
            pass
        # restore admin-entered AI provider keys (persisted in system config) into env
        try:
            from app.agents import llm_config as _llm
            from app.features.admin import security as _sec
            for _cp in (_cfg.get_json(s, "ai_custom_providers", []) or []):
                try:
                    _llm.register_provider(_cp["id"], _cp.get("label"),
                                           _cp["base_url"], _cp.get("model"))
                except Exception as _e:
                    _obs_swallow('bro_app.py', _e)
            _stored = _cfg.get_json(s, "ai_provider_keys", {}) or {}
            for _prov, _k in _stored.items():
                ev = _llm._PROVIDER_KEY_ENV.get(_prov)
                if ev and _k and not _os.environ.get(ev):
                    _os.environ[ev] = _sec.decrypt_value(_k)
            _ap = (_cfg.get_json(s, "ai_active_provider", {}) or {}).get("provider")
            if _ap and not _os.environ.get("BRO_LLM_PROVIDER"):
                _os.environ["BRO_LLM_PROVIDER"] = _ap
        except Exception as _e:
            _obs_swallow('bro_app.py', _e)
        # AI governance: call ledger + daily budget hooks
        try:
            from app.features.assessment import ai_ledger as _AL
            _AL.ensure_table(s)
            from app.agents import llm_config as _llm3
            _llm3.set_telemetry(
                record=lambda p: _AL.safe_record(SessionFactory, p),
                budget=lambda: _AL.budget_check(SessionFactory))
        except Exception as _e:
            _obs_swallow('bro_app.py', _e)
        s.commit()

    def _platform_version() -> str:
        try:
            import pathlib
            return pathlib.Path(__file__).resolve().parent.parent.joinpath(
                "VERSION").read_text().strip()
        except Exception:
            return "4.1.0"

    app = FastAPI(title="BRO Risk Oracle", version=_platform_version())
    app.state.session_factory = SessionFactory

    # transfer efficiency: compress large responses (the app bundle, JSON payloads)
    from fastapi.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def _correlation(request, call_next):
        """AI-06: one correlation identifier from the edge through to the provider
        call and back. Without it, debugging a distributed run is archaeology."""
        try:
            from app.features.platform import telemetry as _TEL
            cid = _TEL.set_correlation_id(request.headers.get("X-Correlation-Id"))
        except Exception:
            cid = None
        resp = await call_next(request)
        if cid:
            resp.headers.setdefault("X-Correlation-Id", cid)
        return resp

    @app.middleware("http")
    async def _security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy",
                                "camera=(), microphone=(), geolocation=(), payment=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob:; "
            "frame-src 'self' blob:; connect-src 'self'")
        if SEC.is_production():
            resp.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        # static assets are version-busted (?v=) so they can be cached hard
        if request.url.path.startswith("/static"):
            resp.headers.setdefault("Cache-Control", "public, max-age=86400, immutable")
        return resp

    def db() -> Session:
        s = SessionFactory()
        try:
            yield s
        finally:
            s.close()

    # ----- actor + RBAC -----
    # Production auth: identity comes from a verified JWT bearer token, NOT a
    # client-supplied header. A test/dev escape hatch (BRO_TRUST_HEADER=1) keeps
    # the x-user header working for the existing test suite and local poking.
    def actor(authorization: str = Header(default=None),
              x_user: str = Header(default=None),
              s: Session = Depends(db)) -> User:
        username: Optional[str] = None
        if authorization:
            try:
                username = bearer_subject(authorization)
            except TokenError as e:
                raise HTTPException(401, str(e))
        elif _os.environ.get("BRO_TRUST_HEADER") == "1" and x_user and not SEC.is_production():
            username = x_user  # dev/test only
        if not username:
            raise HTTPException(401, "authentication required")
        u = s.scalars(select(User).where(User.username == username)).first()
        if not u or not u.is_active:
            raise HTTPException(401, "unknown or inactive user")
        return u

    def require(perm: str):
        def dep(u: User = Depends(actor)):
            if not has_permission(u, perm):
                raise HTTPException(403, f"missing permission: {perm}")
            return u
        return dep

    # ----- audit (hash-chained, persisted) -----
    def _audit_subject(detail: dict):
        """Pull the vendor / engagement this event concerns out of the payload.

        Audit call-sites use varied payload shapes, so this looks for the usual key
        names at the top level, then falls back to a bounded recursive scan and a
        pattern match on any VEN-/ENG- string. Best effort by design: a missing
        subject must never block an audit write."""
        vid = eid = None
        try:
            def _scan(obj, depth=0):
                nonlocal vid, eid
                if depth > 3 or (vid and eid):
                    return
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, str):
                            kl = str(k).lower()
                            if not vid and kl in ("vendor_id", "vendorid", "vendor"):
                                if v.startswith("VEN-"):
                                    vid = v
                            elif not eid and kl in ("engagement_id", "engagementid", "engagement"):
                                if v.startswith("ENG-"):
                                    eid = v
                            elif not vid and v.startswith("VEN-"):
                                vid = v
                            elif not eid and v.startswith("ENG-"):
                                eid = v
                        elif isinstance(v, (dict, list)):
                            _scan(v, depth + 1)
                elif isinstance(obj, list):
                    for it in obj[:20]:
                        _scan(it, depth + 1)
            _scan(detail or {})
        except Exception:
            return None, None
        return vid, eid

    def audit(s: Session, action: str, actor_name: str, detail: dict) -> None:
        last = s.scalars(select(AuditLog).order_by(AuditLog.seq.desc())).first()
        prev = last.entry_hash if last else "genesis"
        seq = (last.seq + 1) if last else 0
        # NOTE: the chain hash is still computed over (prev, action, actor, detail)
        # exactly as before. The subject columns below are a denormalised index of
        # what is already inside `detail`, so existing chains stay verifiable.
        h = eng.chain_hash(prev, action, actor_name, detail)
        _vid, _eid = _audit_subject(detail)
        s.add(AuditLog(seq=seq, action=action, actor=actor_name,
                       detail=json.dumps(detail, sort_keys=True),
                       vendor_id=_vid, engagement_id=_eid,
                       prev_hash=prev, entry_hash=h))

    def notify(s: Session, event: str, audience: str = "all",
               body: str = "") -> None:
        s.add(Notification(audience=audience, event=event, body=body))

    def _fb_guidance(s: Session, surface: str) -> Optional[str]:
        """Distil prior user feedback into prompt guidance; safe no-op on any error."""
        try:
            from app.features.assessment import feedback as FB
            g = FB.guidance(s, surface=surface)
            return g or None
        except Exception:
            return None

    def _ai_live() -> bool:
        try:
            from app.agents import llm_config
            return bool(llm_config.status().get("live_ready"))
        except Exception:
            return False

    AI_HOLDING = ("Noted — AI engines not available yet. BRO Chat, ProAssess, FDD and "
                  "Reputation are AI-driven workflows: they follow the assessment "
                  "methodology with adaptive questioning and analysis, and do not proceed "
                  "without it. Connect an AI provider in Settings → AI to enable them.")

    # ===== health =====
    # ===== health/readiness — extracted to app/routers/health.py (Gap-7 pattern) =====
    # These endpoints now live in their own router module, wired via RouterDeps
    # dependency injection instead of closing over create_app's local scope.
    # This is the reference implementation for decomposing the monolith.
    from .routers.deps import RouterDeps
    from .routers.health import build_health_router
    _router_deps = RouterDeps(
        db=db, actor=actor, require=require, audit=audit,
        platform_version=_platform_version,
    )
    app.include_router(build_health_router(_router_deps))

    # ===== auth =====

    # ===== business routes — extracted per sub-package (RouterDeps pattern) =====
    from .routers.domain import build_domain_router
    from .routers.assessment import build_assessment_router
    from .routers.intelligence import build_intelligence_router
    from .routers.lifecycle import build_lifecycle_router
    from .routers.admin import build_admin_router
    from .routers.platform import build_platform_router
    from .routers.watchlist import build_watchlist_router
    from .routers.genie import build_genie_router
    from .routers.brocall import build_brocall_router
    _core_deps = RouterDeps(
        db=db, actor=actor, require=require, audit=audit,
        platform_version=_platform_version, notify=notify, fb_guidance=_fb_guidance,
        ai_live=_ai_live, ai_holding=AI_HOLDING, engine=engine,
        session_factory=SessionFactory,
    )
    for _build in (build_admin_router, build_domain_router, build_assessment_router,
                   build_intelligence_router, build_lifecycle_router, build_platform_router,
                   build_watchlist_router, build_genie_router, build_brocall_router):
        app.include_router(_build(_core_deps))


    # ===== mount the web UI =====
    from .web import ui as _ui
    app.include_router(_ui)
    # Serve the SPA's JavaScript (extracted from the page into a real asset file,
    # cacheable by the browser and editable with normal JS tooling).
    from fastapi.staticfiles import StaticFiles
    _static_dir = _os.path.join(_os.path.dirname(__file__), "static")
    if _os.path.isdir(_static_dir):
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    # Optional in-process scheduler (single-worker/dev). For multi-worker/prod use a
    # Render Cron Job running run_monitoring.py instead (see render.yaml).
    if _os.environ.get("BRO_SCHEDULER_ENABLED") == "1":
        import threading
        import time as _time
        from app.features.lifecycle import monitoring as _MON

        def _scheduler_loop():
            interval = _monitor_interval()
            check_every = max(60, min(interval * 3600, 3600))  # check hourly at most
            _time.sleep(10)  # let the app finish booting
            while True:
                try:
                    with SessionFactory() as _s:
                        if _MON.claim_due_run(_s, interval):
                            _MON.run_all(_s, by="scheduler", trigger="scheduler", audit_fn=audit)
                except Exception as e:
                    print(f"monitoring scheduler error: {e}")
                _time.sleep(check_every)

        threading.Thread(target=_scheduler_loop, daemon=True, name="bro-monitoring").start()
        print("monitoring scheduler started (interval "
              f"{_monitor_interval()}h)")

    return app


def _count_by(rows, attr):
    out: dict = {}
    for r in rows:
        k = getattr(r, attr) or "none"
        out[k] = out.get(k, 0) + 1
    return out


import os as _os
app = create_app(_os.environ.get("BRO_DB_URL", "sqlite:///bro_unified.db"))
