"""Canonical controlled vocabularies (DB-05).

Before this module, four modules each declared their own finding-status list, in
three different cases, and the database held a value ("In remediation") that none of
them declared. Because status matching is a string comparison, the mismatch never
raised — it silently under-counted every status-filtered report.

One definition lives here. Every writer and validator imports it. `normalise()`
maps historical and case-variant values onto the canonical set so old rows, agent
output and API input all converge without a breaking change.

Rules:
  * Canonical values are the ones stored in the database and returned by the API.
  * Anything unrecognised is returned unchanged, never silently dropped — an unknown
    value is a data-quality signal and must stay visible.
"""
from typing import Optional

# ── Findings ────────────────────────────────────────────────────────────────────
# Canonical lifecycle, matching SOP-21.
FINDING_STATUSES = [
    "Draft",                # auto-created by an assessment, awaiting confirmation
    "Open",                 # confirmed by an assessor; remediation not started
    "In Remediation",       # a remediation plan exists (set automatically)
    "Evidence Submitted",   # supplier has submitted closure evidence
    "Validated",            # evidence reviewed and resolution confirmed
    "Closed",               # finding closed
    "Not Valid",            # rejected on review with rationale
]

_FINDING_ALIASES = {
    # case and spacing variants seen in live data
    "in remediation": "In Remediation",
    "under remediation": "In Remediation",
    "in-remediation": "In Remediation",
    "in progress": "In Remediation",
    "in-progress": "In Remediation",
    "remediated": "Validated",
    "verified": "Validated",
    "evidence submitted": "Evidence Submitted",
    "evidence-submitted": "Evidence Submitted",
    "published": "Open",          # legacy vocabulary: "Published" meant confirmed
    "open": "Open",
    "draft": "Draft",
    "closed": "Closed",
    "validated": "Validated",
    "not valid": "Not Valid",
    "rejected": "Not Valid",
}

SEVERITIES = ["Critical", "High", "Medium", "Low"]
_SEVERITY_ALIASES = {
    "critical": "Critical", "crit": "Critical", "severe": "Critical",
    "high": "High", "medium": "Medium", "med": "Medium",
    "moderate": "Medium", "low": "Low", "info": "Low", "informational": "Low",
}

# ── Risk bands ──────────────────────────────────────────────────────────────────
BANDS = ["HIGH", "ELEVATED", "MODERATE", "LOW"]
_BAND_ALIASES = {
    "high": "HIGH", "elevated": "ELEVATED", "moderate": "MODERATE", "medium": "MODERATE",
    "low": "LOW", "critical": "HIGH",
}

# ── Assessment records ──────────────────────────────────────────────────────────
ASSESSMENT_STATUSES = ["Drafted", "In-Progress", "Completed", "Cancelled"]
_ASSESSMENT_ALIASES = {
    "drafted": "Drafted", "draft": "Drafted",
    "in-progress": "In-Progress", "in progress": "In-Progress", "inprogress": "In-Progress",
    "completed": "Completed", "complete": "Completed", "done": "Completed",
    "cancelled": "Cancelled", "canceled": "Cancelled",
}

# ── Issues ──────────────────────────────────────────────────────────────────────
ISSUE_STATUSES = ["Open", "Closed"]
_ISSUE_ALIASES = {"open": "Open", "closed": "Closed", "resolved": "Closed"}

_SETS = {
    "finding_status": (FINDING_STATUSES, _FINDING_ALIASES),
    "severity": (SEVERITIES, _SEVERITY_ALIASES),
    "band": (BANDS, _BAND_ALIASES),
    "assessment_status": (ASSESSMENT_STATUSES, _ASSESSMENT_ALIASES),
    "issue_status": (ISSUE_STATUSES, _ISSUE_ALIASES),
}


def normalise(kind: str, value: Optional[str]) -> Optional[str]:
    """Map a value onto its canonical form. Unknown values pass through unchanged."""
    if value is None:
        return None
    canon, aliases = _SETS.get(kind, ([], {}))
    v = str(value).strip()
    if v in canon:
        return v
    return aliases.get(v.lower(), v)


def is_valid(kind: str, value: Optional[str]) -> bool:
    canon, _ = _SETS.get(kind, ([], {}))
    return value in canon


def allowed(kind: str) -> list:
    return list(_SETS.get(kind, ([], {}))[0])
