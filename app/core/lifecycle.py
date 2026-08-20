"""
Phase 6b: the 10-stage lifecycle state machine.

BRO's lifecycle: Sourcing -> Triage -> Inherent -> Diligence -> Decision ->
Contract -> Onboard -> Monitor -> Reassess -> Terminate. Each transition raises
a notification (the compendium's stage notifications). Monitoring can loop back
to Reassessment (monitoring-triggered reopen). Termination is terminal.

The state machine enforces legal transitions so an engagement can't skip
exposure-first ordering ("Exposure first, controls second, verdict last").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Stage(str, Enum):
    SOURCING = "sourcing"
    TRIAGE = "triage"
    INHERENT = "inherent"
    DILIGENCE = "diligence"
    DECISION = "decision"
    CONTRACT = "contract"
    ONBOARD = "onboard"
    MONITOR = "monitor"
    REASSESS = "reassess"
    TERMINATE = "terminate"


# Legal forward transitions; plus monitoring<->reassessment loop and
# reassessment can re-enter diligence (delta reassessment).
_TRANSITIONS: dict[Stage, tuple[Stage, ...]] = {
    Stage.SOURCING: (Stage.TRIAGE,),
    Stage.TRIAGE: (Stage.INHERENT,),
    Stage.INHERENT: (Stage.DILIGENCE, Stage.DECISION),  # auto-approve can skip
    Stage.DILIGENCE: (Stage.DECISION,),
    Stage.DECISION: (Stage.CONTRACT, Stage.TERMINATE),  # do-not-proceed -> exit
    Stage.CONTRACT: (Stage.ONBOARD,),
    Stage.ONBOARD: (Stage.MONITOR,),
    Stage.MONITOR: (Stage.REASSESS, Stage.TERMINATE),
    Stage.REASSESS: (Stage.DILIGENCE, Stage.DECISION, Stage.MONITOR),
    Stage.TERMINATE: (),
}


class IllegalTransition(ValueError):
    pass


@dataclass(frozen=True)
class Notification:
    engagement_id: str
    stage: Stage
    event: str
    notify_vrm: bool
    notify_business: bool


@dataclass
class Engagement:
    engagement_id: str
    vendor_id: str
    org_id: str
    stage: Stage = Stage.SOURCING
    business_contact: Optional[str] = None
    notifications: list[Notification] = field(default_factory=list)

    def can_transition_to(self, target: Stage) -> bool:
        return target in _TRANSITIONS[self.stage]

    def transition(self, target: Stage, event: str,
                   notify_vrm: bool = False,
                   notify_business: bool = False) -> Notification:
        if not self.can_transition_to(target):
            raise IllegalTransition(
                f"cannot move {self.stage.value} -> {target.value}"
            )
        self.stage = target
        note = Notification(self.engagement_id, target, event,
                            notify_vrm, notify_business)
        self.notifications.append(note)
        return note
