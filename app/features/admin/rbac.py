"""
Group A: seed data + RBAC checks (ported from database.py PERMISSIONS/SYSTEM_ROLES).

49 permissions across 10 categories and 4 protected system roles, reproduced
exactly from the uploaded app so behaviour parity holds. has_permission() is the
basis for the FastAPI RBAC dependency.
"""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.domain.models_db import (
    Base, Permission, Role, RolePermission, User, Vendor,
    hash_password,
)

# (category, key, label) — exact port.
PERMISSIONS: list[tuple[str, str, str]] = [
    ("Engagements", "engagement.view", "View engagements"),
    ("Engagements", "engagement.create", "Create engagements"),
    ("Engagements", "engagement.edit", "Edit engagements / answer IRQ & DDQ"),
    ("Engagements", "engagement.publish", "Publish assessment reports"),
    ("Engagements", "engagement.review", "Review & sign off (Assessor)"),
    ("Engagements", "engagement.assign", "Assign engagements to assessors (Controller)"),
    ("Global Regulations", "reg.view", "View the global regulatory catalogue"),
    ("Global Regulations", "reg.assess", "Run AI regulatory updates & gap assessment"),
    ("Data Quality", "integrity.view", "View data-integrity health & issues"),
    ("Data Quality", "integrity.manage", "Apply fixes, merges & enrichment"),
    ("Supplier Incidents", "incident.view", "View supplier incidents"),
    ("Supplier Incidents", "incident.manage", "Create & manage supplier incidents"),
    ("Engagements", "engagement.override", "Override decisions"),
    ("Engagements", "engagement.autopilot", "Run AI autopilot assessment"),
    ("Vendors", "vendor.view", "View vendor register"),
    ("Vendors", "vendor.edit", "Add / edit vendors"),
    ("Vendors", "vendor.critical", "Designate critical vendors"),
    ("Action Plan", "finding.view", "View findings / action plan"),
    ("Action Plan", "finding.manage", "Raise & manage findings"),
    ("Action Plan", "finding.delete", "Delete findings"),
    ("Action Plan", "acceptance.manage", "Record risk acceptances"),
    ("Intelligence", "intel.financial", "Run financial due diligence & monitoring"),
    ("Intelligence", "intel.reputation", "Run reputation & ESG screening"),
    ("Intelligence", "intel.contract", "Generate & review contracts"),
    ("Intelligence", "intel.evidence", "Auto-validate assurance evidence"),
    ("Intelligence", "intel.ratings", "View external security ratings"),
    ("Intelligence", "intel.sanctions", "Run sanctions, PEP & UBO screening"),
    ("Lifecycle", "lifecycle.fourthparty", "Manage 4th-party register"),
    ("Lifecycle", "lifecycle.documents", "Upload & manage documents"),
    ("Lifecycle", "lifecycle.monitoring", "Run & view monitoring sweeps"),
    ("Lifecycle", "lifecycle.reassess", "Manage reassessments"),
    ("Lifecycle", "lifecycle.offboard", "Run offboarding workflow"),
    ("Lifecycle", "lifecycle.certs", "Manage certifications"),
    ("Lifecycle", "lifecycle.evidence", "Track & validate evidence expiry"),
    ("Lifecycle", "lifecycle.cap", "Manage corrective action plans"),
    ("Lifecycle", "lifecycle.performance", "Manage vendor performance & SLAs"),
    ("Lifecycle", "lifecycle.obligations", "Manage contract obligations"),
    ("Lifecycle", "lifecycle.bia", "Manage business impact analysis"),
    ("Lifecycle", "lifecycle.incident", "Manage third-party incidents"),
    ("Notifications", "notify.view", "View notifications"),
    ("Notifications", "notify.inbound", "Process inbound email submissions"),
    ("Dashboards", "dashboard.trending", "View risk-score trending"),
    ("Dashboards", "dashboard.exec", "View executive dashboard"),
    ("Dashboards", "dashboard.ops", "View operational dashboard"),
    ("Dashboards", "dashboard.risk", "View risk posture dashboard"),
    ("Dashboards", "dashboard.executive_view", "Executive View AI analytics"),
    ("Governance", "audit.view", "View audit trail"),
    ("Governance", "audit.export", "Export audit trail"),
    ("Governance", "methodology.version", "Version the methodology"),
    ("Governance", "reg.report", "Generate regulatory reports & registers"),
    ("Administration", "admin.email", "Configure email service & integration"),
    ("Administration", "admin.aikeys", "Manage AI provider API keys"),
    ("Administration", "admin.users", "Manage users"),
    ("Administration", "admin.roles", "Manage roles & permissions"),
    ("Administration", "admin.integrations", "Manage integrations & API tokens"),
    ("Administration", "admin.webhooks", "Manage webhooks & procurement triggers"),
    ("Administration", "admin.config", "Manage system configuration & risk parameters"),
    ("Administration", "admin.content", "Edit application content & labels (Content Studio)"),
    ("Administration", "supplier.manage", "Manage supplier users (backup users)"),
    ("Vendor Portal", "portal.self", "Vendor self-service portal"),
    ("Watchlist", "watchlist.view", "View the supplier watchlist, criteria and candidates"),
    ("Watchlist", "watchlist.edit", "Add/edit/delete watchlist entries & criteria (Controller)"),
    ("Watchlist", "watchlist.sweep", "Run the watchlist database sweep (Controller)"),
    ("Watchlist", "watchlist.approve", "Approve/reject sweep candidates (Controller)"),
    ("Supplier Notes", "note.view", "View supplier notes (internal only)"),
    ("Supplier Notes", "note.add", "Add supplier notes (internal only)"),
]

_BUYER = [
    "engagement.view", "engagement.create", "engagement.edit", "engagement.publish",
    "engagement.autopilot", "vendor.view", "vendor.edit", "finding.view",
    "finding.manage", "acceptance.manage", "intel.financial", "intel.reputation",
    "intel.contract", "intel.evidence", "lifecycle.fourthparty", "lifecycle.documents",
    "lifecycle.monitoring", "lifecycle.reassess", "lifecycle.offboard",
    "lifecycle.certs", "lifecycle.evidence", "intel.ratings", "intel.sanctions",
    "lifecycle.cap", "lifecycle.performance", "lifecycle.obligations", "lifecycle.bia",
    "lifecycle.incident", "dashboard.trending", "notify.view", "notify.inbound",
    "dashboard.exec", "dashboard.ops", "dashboard.risk", "dashboard.executive_view",
    "audit.view",
]
_BUYER = _BUYER + ["reg.view", "reg.assess", "integrity.view", "incident.view",
                   "watchlist.view", "note.view", "note.add"]
_VRM = _BUYER + ["engagement.review", "vendor.critical", "reg.report",
                 "audit.export", "methodology.version", "integrity.manage", "incident.manage"]
_VRM = [p for p in _VRM if p not in ("engagement.create", "engagement.edit",
                                     "engagement.publish", "vendor.edit")]
_VRM = _VRM + ["supplier.manage"]

# Controller: assigns engagements to assessors, oversees the action plan.
_CONTROLLER = ["engagement.view", "engagement.assign", "engagement.review",
               "vendor.view", "finding.view", "finding.manage", "finding.delete",
               "acceptance.manage", "lifecycle.documents", "notify.view",
               "dashboard.exec", "dashboard.ops", "dashboard.risk",
               "dashboard.trending", "dashboard.executive_view", "audit.view", "audit.export",
               "reg.view", "reg.assess", "integrity.view", "integrity.manage", "incident.manage", "supplier.manage",
               "watchlist.view", "watchlist.edit", "watchlist.sweep", "watchlist.approve",
               "note.view", "note.add"]

_EXEC = ["vendor.view", "finding.view", "incident.view", "reg.view",
         "integrity.view", "audit.view", "watchlist.view", "note.view"]

SYSTEM_ROLES = {
    "admin": ("Administrator", "#5C2A1A",
              "Full platform access, oversight, methodology & override.", "ALL"),
    "buyer": ("Buyer / Business Lead", "#1A4D3C",
              "Owns the engagement first contact to published report.", _BUYER),
    "vrm": ("Assessor", "#1E3A5C",
            "Reviews HIGH/ELEVATED engagements, validates, signs off.", _VRM),
    "controller": ("Controller", "#7A4E2D",
                   "Assigns engagements to assessors and oversees the action plan.", _CONTROLLER),
    "exec": ("Executive Management", "#2C2A4A",
             "Board / executive oversight — read-only across the estate, dashboards, board pack and evidence.", _EXEC),
    "vendor": ("Supplier", "#6B7280",
               "Self-service: own supplier, engagements, performance issues, findings, issues log and remediation plans.",
               ["portal.self", "engagement.edit", "engagement.view", "vendor.view",
                "finding.view", "finding.manage", "incident.view", "lifecycle.performance",
                "lifecycle.cap"]),
}


def seed(session: Session) -> None:
    """Idempotent seed of permissions, system roles, and a default admin."""
    existing = {p.key for p in session.scalars(select(Permission)).all()}
    for cat, key, label in PERMISSIONS:
        if key not in existing:
            session.add(Permission(key=key, label=label, category=cat))
    session.flush()

    all_perms = {p.key: p for p in session.scalars(select(Permission)).all()}
    have_roles = {r.key: r for r in session.scalars(select(Role)).all()}
    for rkey, (label, color, desc, perms) in SYSTEM_ROLES.items():
        if rkey in have_roles:
            # Keep existing roles as-is, but always refresh full-access ("ALL")
            # roles so newly added permissions are granted automatically on boot
            # (e.g. the admin role picks up admin.content without a manual grant).
            if perms == "ALL":
                have_roles[rkey].permissions = list(all_perms.values())
            else:
                # Additive reconciliation for system roles: grant any permission
                # newly defined in SYSTEM_ROLES that the role is missing (never
                # removes), so existing deployments pick up new features (e.g.
                # watchlist.view) without a manual grant or a DB reset.
                role = have_roles[rkey]
                have = {p.key for p in role.permissions}
                for k in perms:
                    if k not in have and k in all_perms:
                        role.permissions.append(all_perms[k])
            continue
        role = Role(key=rkey, label=label, description=desc, color=color,
                    is_system=True)
        keys = list(all_perms) if perms == "ALL" else perms
        role.permissions = [all_perms[k] for k in keys if k in all_perms]
        session.add(role)
    session.flush()

    if not session.scalars(select(User).where(User.username == "admin")).first():
        from app.features.admin.secrets import get_secret, is_production
        admin_role = session.scalars(select(Role).where(Role.key == "admin")).first()
        admin_user = get_secret("BRO_ADMIN_USERNAME", default="admin")
        admin_email = get_secret("BRO_ADMIN_EMAIL", default="admin@bro.example")
        admin_pw = get_secret("BRO_ADMIN_PASSWORD")
        if is_production():
            # Never seed a guessable admin in production.
            if not admin_pw or admin_pw == "admin" or len(admin_pw) < 12:
                raise RuntimeError(
                    "Refusing to seed the platform admin in production without a strong "
                    "BRO_ADMIN_PASSWORD (>= 12 chars). Set it via env/secret store.")
        elif not admin_pw:
            admin_pw = "admin"
            print("WARNING: seeding default admin/admin (dev only). "
                  "Set BRO_ADMIN_PASSWORD for any shared environment.")
        session.add(User(username=admin_user, full_name="Platform Admin",
                         email=admin_email,
                         password_hash=hash_password(admin_pw),
                         role_id=admin_role.id))
    session.commit()


def has_permission(user: User, perm_key: str) -> bool:
    """True if the user's role grants perm_key at any access level (admin ALL implies everything)."""
    if user.role is None:
        return False
    return any(p.key == perm_key for p in user.role.permissions)


# ---- graded access (read | write | modify | denied) -------------------------
ACCESS_LEVELS = ["denied", "read", "write", "modify"]
_ACCESS_RANK = {"denied": 0, "read": 1, "write": 2, "modify": 3}


def access_of(session: Session, role_id: int, perm_id: int) -> str:
    from app.features.domain.models_db import RolePermission
    row = session.get(RolePermission, (role_id, perm_id))
    return (row.access or "modify") if row else "denied"


def user_access(session: Session, user: User, perm_key: str) -> str:
    """Effective access level a user has for a permission ('denied' if none)."""
    from app.features.domain.models_db import Permission
    if user.role is None:
        return "denied"
    p = session.scalars(select(Permission).where(Permission.key == perm_key)).first()
    if not p:
        return "denied"
    return access_of(session, user.role_id, p.id)


def at_least(level: str, required: str) -> bool:
    return _ACCESS_RANK.get(level, 0) >= _ACCESS_RANK.get(required, 0)


def set_access(session: Session, role_key: str, perm_key: str, access: str,
               actor: str = "admin") -> dict:
    """Set the access level for one (role, permission). 'denied' removes the grant."""
    from app.features.domain.models_db import Role, Permission, RolePermission
    if access not in ACCESS_LEVELS:
        raise ValueError("access must be one of " + ", ".join(ACCESS_LEVELS))
    role = session.scalars(select(Role).where(Role.key == role_key)).first()
    perm = session.scalars(select(Permission).where(Permission.key == perm_key)).first()
    if not role or not perm:
        raise KeyError("unknown role or permission")
    row = session.get(RolePermission, (role.id, perm.id))
    if access == "denied":
        if row:
            session.delete(row)
        session.flush()
        return {"role": role_key, "perm": perm_key, "access": "denied"}
    if not row:
        row = RolePermission(role_id=role.id, perm_id=perm.id)
        session.add(row)
    row.access = access
    session.flush()
    return {"role": role_key, "perm": perm_key, "access": access}


def access_matrix(session: Session) -> dict:
    """Full role x permission grant map: {'role_key|perm_key': access_level}."""
    from app.features.domain.models_db import Role, Permission, RolePermission
    roles = {r.id: r.key for r in session.scalars(select(Role)).all()}
    perms = {p.id: p.key for p in session.scalars(select(Permission)).all()}
    grants = {}
    for rp in session.scalars(select(RolePermission)).all():
        rk, pk = roles.get(rp.role_id), perms.get(rp.perm_id)
        if rk and pk:
            grants[rk + "|" + pk] = rp.access or "modify"
    return grants


# ============ Menu visibility by permission (data-v -> required permission) ============
# A nav item is hidden unless the user has at least READ access to its permission.
# Items not listed here are always visible (home, settings, help, etc.).
NAV_PERMISSION = {
    "vendors": "vendor.view", "vendor360": "vendor.view", "entitygraph": "vendor.view",
    "fourthparties": "vendor.view", "criticality": "vendor.view", "exposure": "vendor.view",
    "engagements": "engagement.view", "assess": "engagement.view", "proassess": "engagement.view",
    "assessments": "engagement.view", "review": "engagement.review", "governance": "engagement.review",
    "findings": "finding.view", "remediation": "finding.view", "issues": "finding.view",
    "perfissues": "finding.view", "acceptance": "acceptance.manage",
    "fdd": "intel.financial", "reputation": "intel.reputation",
    "oss": "vendor.view", "pestle": "vendor.view", "geopolitical": "vendor.view",
    "stressradar": "vendor.view", "scenario": "vendor.view",
    "lifecycle": "vendor.view", "contracts": "lifecycle.documents", "artefacts": "lifecycle.documents",
    "documents": "lifecycle.documents", "performance": "lifecycle.performance",
    "slamgmt": "lifecycle.performance", "exit": "lifecycle.offboard", "incidents": "incident.view",
    "globalreg": "reg.view", "methodology": "methodology.version",
    "intel": "vendor.view", "management": "dashboard.exec", "boardpack": "dashboard.exec",
    "reports": "dashboard.exec", "aireports": "dashboard.exec",
    "notifications": "notify.view", "schedules": "notify.view",
    "watchlist": "watchlist.view",
    "evidence": "audit.view", "audit": "audit.view", "integrity": "integrity.view",
    "admin": "admin.users", "adminchange": "admin.content", "config": "admin.config",
    "aicontrol": "admin.config", "connections": "admin.integrations",
    "supplierusers": "supplier.manage",
    "usermgmt": "supplier.manage",
}


def user_permissions(session: Session, user: User) -> dict:
    """Effective permission -> access level map for the user's role (denied omitted)."""
    from app.features.domain.models_db import Permission, RolePermission
    if user.role is None:
        return {}
    out = {}
    perm_by_id = {p.id: p.key for p in session.scalars(select(Permission)).all()}
    for rp in session.scalars(select(RolePermission).where(RolePermission.role_id == user.role_id)).all():
        k = perm_by_id.get(rp.perm_id)
        if k:
            out[k] = rp.access or "modify"
    return out


def denied_navs(session: Session, user: User) -> list:
    """data-v nav items the user must NOT see (no read+ access to the required permission)."""
    perms = user_permissions(session, user)
    hidden = []
    for datav, need in NAV_PERMISSION.items():
        if need not in perms:            # denied = no grant at all
            hidden.append(datav)
    return hidden


# ============ Row-level data isolation (own records only) ============
def user_business_units(session: Session, user: User) -> set:
    """The business units a user acts for.

    Explicit assignment on the user record wins. Where it is unset we derive the BUs
    from the engagements the user owns, so an existing deployment scopes correctly
    without a backfill — and a buyer who owns nothing sees nothing rather than
    everything, which is the safe direction to fail.
    """
    explicit = (getattr(user, "business_unit", None) or "").strip()
    if explicit:
        return {b.strip() for b in explicit.split(",") if b.strip()}
    from app.features.domain.registry_models import EngagementRecord
    rows = session.scalars(select(EngagementRecord.business_unit)
                           .where(EngagementRecord.owner_user == user.username)).all()
    return {b for b in rows if b}


def scoped_vendor_ids(session: Session, user: User):
    """None = unrestricted (admin/vrm/controller/exec). Otherwise the set of
    vendor_ids this user may see: a supplier sees only their own vendor; a buyer
    sees every vendor engaged by their business unit(s)."""
    rk = user.role.key if user.role else None
    if rk == "vendor":
        return {user.vendor_id} if getattr(user, "vendor_id", None) else set()
    if rk == "buyer":
        from app.features.domain.registry_models import EngagementRecord
        bus = user_business_units(session, user)
        if not bus:
            return set()
        rows = session.scalars(select(EngagementRecord.vendor_id)
                               .where(EngagementRecord.business_unit.in_(bus))).all()
        return set(v for v in rows if v)
    return None


def can_see_vendor(session: Session, user: User, vendor_id: str) -> bool:
    allowed = scoped_vendor_ids(session, user)
    return allowed is None or (vendor_id in allowed)


# ---------------------------------------------------------------------------
# Object-level authorization (BOLA / OWASP API #1)
#
# Function-level RBAC (require(perm)) gates *which actions* a role may perform.
# These helpers gate *which objects* a scoped role may act on — closing the gap
# where a `vendor` or `buyer` could reach another supplier's object by ID.
#
# Design:
#   - Unrestricted roles (admin / vrm / controller / exec) short-circuit with
#     no extra query — scoped_vendor_ids returns None for them.
#   - Every registry record (engagement, assessment, finding, incident,
#     remediation, person) carries a vendor_id; we resolve it and check
#     membership of the caller's allowed set.
#   - On a scope miss we raise 404 (not 403) so a scoped user cannot enumerate
#     the existence of objects outside their scope.
# ---------------------------------------------------------------------------

def _resolve_vendor_id(session: Session, kind: str, ident) -> Optional[str]:
    """Return the vendor_id an object belongs to, or None if not found/unlinked."""
    from app.features.domain.registry_models import (
        EngagementRecord, AssessmentRecord, FindingRecord,
        IncidentRecord, RemediationRecord, VendorPerson, VendorRecord)
    m = {
        "vendor":      (VendorRecord,     VendorRecord.vendor_id),
        "engagement":  (EngagementRecord, EngagementRecord.engagement_id),
        "assessment":  (AssessmentRecord, AssessmentRecord.assessment_id),
        "finding":     (FindingRecord,    FindingRecord.finding_id),
        "incident":    (IncidentRecord,   IncidentRecord.incident_id),
        "person":      (VendorPerson,     VendorPerson.person_id),
    }
    if kind == "remediation":
        rem = session.scalars(select(RemediationRecord).where(
            RemediationRecord.remediation_id == ident)).first()
        if not rem or not rem.finding_id:
            return None
        return _resolve_vendor_id(session, "finding", rem.finding_id)
    if kind not in m:
        return None
    model, keycol = m[kind]
    row = session.scalars(select(model).where(keycol == ident)).first()
    return getattr(row, "vendor_id", None) if row else None


def assert_object_visible(session: Session, user: User, kind: str, ident) -> None:
    """Raise 404 if a scoped user tries to reach an object outside their scope.

    `kind` is 'vendor' (ident IS the vendor_id) or an object type whose record
    carries a vendor_id ('engagement'/'assessment'/'finding'/'incident'/
    'remediation'/'person'). No-op for unrestricted roles.
    """
    from fastapi import HTTPException
    allowed = scoped_vendor_ids(session, user)
    if allowed is None:            # admin / vrm / controller / exec — unrestricted
        return
    vendor_id = ident if kind == "vendor" else _resolve_vendor_id(session, kind, ident)
    if vendor_id is not None and vendor_id not in allowed:
        # Log the denial: a scoped user reaching for another supplier's object is a
        # signal worth seeing, and a silent 404 makes it invisible.
        try:
            import logging as _lg
            _lg.getLogger("brata.access").warning(
                "scope denied: user=%s role=%s kind=%s ident=%s vendor=%s",
                user.username, (user.role.key if user.role else "?"), kind, ident, vendor_id)
        except Exception:
            pass
        raise HTTPException(404, "not found")


def scope_engagement_query(session: Session, user: User, query):
    """Restrict an EngagementRecord select to the user's own records where scoped."""
    from app.features.domain.registry_models import EngagementRecord
    rk = user.role.key if user.role else None
    if rk == "vendor":
        return query.where(EngagementRecord.vendor_id == (user.vendor_id or "__none__"))
    if rk == "buyer":
        bus = user_business_units(session, user)
        if not bus:
            return query.where(EngagementRecord.engagement_id == "__none__")
        return query.where(EngagementRecord.business_unit.in_(bus))
    return query
