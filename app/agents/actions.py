"""
Phase 2d: actions and notifications — the SECOND gate (Q3).

Critical separation from escalation: a FINDING may auto-deliver (high confidence,
low impact), but any consequential ACTION arising from it ALWAYS requires explicit
human agreement. No auto-execute, regardless of confidence. Two different gates:

    finding  -> escalation engine (confidence x impact; some auto-deliver)
    action   -> human agreement   (ALWAYS, by your choice)

Notifications split in two tiers:
    INFORMATIONAL : no real-world consequence -> may fire automatically
    CONSEQUENTIAL : touches the vendor / changes a record of consequence
                    -> treated as an action, needs agreement

This makes the posture: AI-first ASSESSMENT, human-gated CONSEQUENCE.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ActionState(str, Enum):
    PROPOSED = "proposed"
    AGREED = "agreed"
    REJECTED = "rejected"
    EXECUTED = "executed"


class NotificationTier(str, Enum):
    INFORMATIONAL = "informational"   # may auto-fire
    CONSEQUENTIAL = "consequential"   # gated like an action


@dataclass(frozen=True)
class ProposedAction:
    action_id: str
    org_id: str
    engagement_id: str
    description: str
    proposed_by: str          # agent id
    target_touches_vendor: bool


@dataclass(frozen=True)
class ActionRecord:
    action: ProposedAction
    state: ActionState
    decided_by: Optional[str] = None    # human id
    reason_code: Optional[str] = None


def agree_action(
    action: ProposedAction,
    human_actor_id: str,
    actor_is_human: bool,
    reason_code: str,
) -> ActionRecord:
    """Human agrees -> action becomes executable. Enforces human-only."""
    if not actor_is_human:
        raise PermissionError("only a human can agree to execute an action")
    return ActionRecord(action, ActionState.AGREED, human_actor_id, reason_code)


def reject_action(
    action: ProposedAction, human_actor_id: str, reason_code: str
) -> ActionRecord:
    return ActionRecord(action, ActionState.REJECTED, human_actor_id, reason_code)


def execute_action(record: ActionRecord) -> ActionRecord:
    """Execution only permitted on an AGREED action."""
    if record.state is not ActionState.AGREED:
        raise PermissionError(
            f"cannot execute action in state '{record.state.value}'; "
            "must be AGREED by a human first"
        )
    return ActionRecord(
        record.action, ActionState.EXECUTED, record.decided_by, record.reason_code
    )


def may_auto_fire(tier: NotificationTier) -> bool:
    """Only informational notifications auto-fire; consequential ones are gated."""
    return tier is NotificationTier.INFORMATIONAL
