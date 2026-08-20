"""Activity classification: human actions versus system/agent actions.

The audit trail records `actor` as a username, and it always will — the SOP is explicit
(IAM-4) that an AI action is attributed to the human who invoked it, because the model
is never the accountable party. That is correct for accountability and unhelpful for
transparency: a reviewer looking at the trail cannot tell whether a person made a
decision or whether an automated chain fired underneath one.

This module supplies the missing distinction without changing the attribution. Every
audited action is classified by what performed it:

    HUMAN   a person chose to do this — created, edited, approved, signed off
    AGENT   the system or an AI agent did it, usually as a consequence of a human act
            or a schedule: automated record chains, sweeps, screenings, model calls

The classification is by action name, held here in one place rather than scattered
across call sites, so it can be reviewed as a whole and corrected without touching the
audit writer. Unknown actions default to HUMAN: over-attributing to a person is the
conservative error, because it invites scrutiny rather than hiding an action in a
system log nobody reads.
"""
from __future__ import annotations

HUMAN = "human"
AGENT = "agent"

# Prefixes that identify an automated chain, a scheduled sweep, or an AI action.
# Ordered longest-first at match time so a specific rule beats a general one.
_AGENT_PREFIXES = (
    "monitoring.",          # portfolio sweep and all its sub-tasks
    "schedules.",           # scheduler firing
    "sanctions.screen",     # automated re-screening
    "v2.screening",
    "revalidation.",        # certificate expiry chain
    "cert.",
    "email_intake.",        # inbound certificate mail
    "ai.",                  # model calls, budget events, dump-to-draft
    "v2.research",          # background research jobs
    "research.",
    "proassess.auto",       # autonomous assessment
    "agent.",               # conversational agent turns and handoffs
    "brocall.",             # voice agent tool calls
    "auto.",                # anything explicitly marked automated
    "watchlist.sweep",
    "integrity.",           # data-integrity checks
    "v2.integrity",
    "notification.emit",
    "finding.auto",         # findings created by an assessment rather than a person
)

# Actions that look automated by prefix but are a human decision, and vice versa.
_OVERRIDES = {
    "ai.prompt_set": HUMAN,          # an administrator edited a prompt
    "ai.prompt_reset": HUMAN,
    "ai.key_saved": HUMAN,
    "ai.provider_changed": HUMAN,
    "agent.session_opened": HUMAN,   # a person started the conversation
    "brocall.consent": HUMAN,        # a person recorded consent
    "schedules.update": HUMAN,       # an administrator changed a cadence
    "monitoring.run_manual": HUMAN,  # a person triggered the sweep by hand
}


def classify(action: str) -> str:
    """Return HUMAN or AGENT for an audit action name."""
    a = (action or "").strip()
    if a in _OVERRIDES:
        return _OVERRIDES[a]
    low = a.lower()
    for pfx in sorted(_AGENT_PREFIXES, key=len, reverse=True):
        if low.startswith(pfx):
            return AGENT
    return HUMAN            # unknown → attribute to a person, the conservative error


def label(action: str) -> str:
    """A readable description of an audit action for a non-engineer reviewer."""
    a = (action or "")
    known = {
        "v2.vendor_created": "Created a supplier",
        "v2.vendors_imported": "Imported suppliers from a file",
        "v2.engagement_created": "Created an engagement",
        "engagement.created": "Created an engagement",
        "vendor.created": "Created a supplier",
        "assessment.registered": "Registered an assessment",
        "agent.session_opened": "Opened a conversation",
        "agent.handoff": "Agent handed off to a specialist",
        "finding.updated": "Updated a finding",
        "finding.auto_created": "Finding raised automatically by an assessment",
        "user.created": "Created a user",
        "user.password_changed": "Changed a password",
        "supplier_user.created": "Provisioned a supplier portal account",
        "v2.research_fdd.start": "Started financial due-diligence research",
        "v2.research_reputation.start": "Started reputation research",
        "monitoring.band_divergence": "Detected divergent risk bands",
        "monitoring.run": "Ran the monitoring sweep",
        "v2.integrity_sweep": "Ran a data-integrity sweep",
        "incident.notable": "Flagged a notable event",
        "privacy.erasure_executed": "Executed a data-erasure request",
        "ai.prompt_set": "Changed an AI prompt",
        "schedules.update": "Changed a schedule",
        "engagement.watchlist_signoff_required": "Required watchlist sign-off",
    }
    if a in known:
        return known[a]
    # Fall back to a humanised form of the action name rather than showing a raw key.
    tail = a.split(".", 1)[-1].replace("_", " ").strip()
    return tail[:1].upper() + tail[1:] if tail else "Action"


def summarise(action: str) -> dict:
    return {"action": action, "kind": classify(action), "label": label(action)}
