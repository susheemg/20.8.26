"""
Phase 6c: the FastAPI application surface.

Exposes the tested engine as a working REST API under /api/v1, mirroring BRO's
capability set: vendors, engagements, lifecycle transitions, inherent/residual
scoring with banding + the critical-control override, straight-through routing,
and the decision step with VRM sign-off / justified override (the two-gate model).

Persistence here is an in-memory store so the app RUNS and is testable with no
database server (the deterministic-by-default stance). A SQLAlchemy repository
over schema.sql is the drop-in for production; the route handlers depend on the
Store interface, not on the storage.

Every consequential transition writes to the hash-chained audit trail.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .core.audit import AuditTrail
from .core.lifecycle import Engagement, Stage, IllegalTransition
from .core.scoring import (
    Band, ControlOutcome, ControlResult, RoutingDecision, TriageInput,
    band_for_score, residual_band, route,
)


# ----- request schemas (module-level so FastAPI infers them as bodies) -----

class VendorIn(BaseModel):
    org_id: str
    name: str
    business_contact: Optional[str] = None

class EngagementIn(BaseModel):
    org_id: str
    vendor_id: str
    business_contact: Optional[str] = None

class IRQIn(BaseModel):
    exposure_score: float = Field(ge=0, le=100)

class TriageIn(BaseModel):
    tier: int = Field(ge=1, le=4)
    special_data: bool = False
    sanctions_exposure: bool = False
    cross_border: bool = False
    uses_ai: bool = False

class InherentIn(BaseModel):
    irq: IRQIn
    t: TriageIn

class ControlIn(BaseModel):
    control_id: str
    domain: str
    outcome: ControlOutcome
    is_critical: bool = False

class DecisionIn(BaseModel):
    exposure_score: float = Field(ge=0, le=100)
    controls: list[ControlIn] = []
    actor_id: str
    actor_is_human: bool
    override_band: Optional[Band] = None
    override_reason: Optional[str] = None
    second_approver: Optional[str] = None


# ----- in-memory store (swap for SQLAlchemy repo in prod) -----

@dataclass
class Store:
    vendors: dict[str, dict] = field(default_factory=dict)
    engagements: dict[str, Engagement] = field(default_factory=dict)
    audit: AuditTrail = field(default_factory=AuditTrail)
    _seq: int = 0

    def next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"


def create_app(store: Optional[Store] = None) -> FastAPI:
    store = store or Store()
    app = FastAPI(title="BRO Risk Oracle", version="3.1")

    # ---- vendors ----
    @app.post("/api/v1/vendors")
    def create_vendor(v: VendorIn):
        vid = store.next_id("ven")
        store.vendors[vid] = v.model_dump() | {"vendor_id": vid}
        store.audit.append(v.org_id, "vendor.created", "system",
                           {"vendor_id": vid, "name": v.name})
        return store.vendors[vid]

    # ---- engagements + lifecycle ----
    @app.post("/api/v1/engagements")
    def create_engagement(e: EngagementIn):
        if e.vendor_id not in store.vendors:
            raise HTTPException(404, "vendor not found")
        eid = store.next_id("eng")
        eng = Engagement(eid, e.vendor_id, e.org_id,
                         business_contact=e.business_contact)
        store.engagements[eid] = eng
        store.audit.append(e.org_id, "engagement.created", "system",
                           {"engagement_id": eid, "vendor_id": e.vendor_id})
        return {"engagement_id": eid, "stage": eng.stage.value}

    def _get(eid: str) -> Engagement:
        eng = store.engagements.get(eid)
        if not eng:
            raise HTTPException(404, "engagement not found")
        return eng

    @app.post("/api/v1/engagements/{eid}/triage")
    def triage(eid: str, t: TriageIn):
        eng = _get(eid)
        eng.transition(Stage.TRIAGE, "triage_started")
        store.audit.append(eng.org_id, "stage.triage", "system",
                           {"engagement_id": eid} | t.model_dump())
        return {"engagement_id": eid, "stage": eng.stage.value}

    @app.post("/api/v1/engagements/{eid}/inherent")
    def inherent(eid: str, body: InherentIn):
        eng = _get(eid)
        irq, t = body.irq, body.t
        if eng.stage is Stage.TRIAGE:
            eng.transition(Stage.INHERENT, "inherent_scored", notify_vrm=False)
        band = band_for_score(irq.exposure_score)
        routing = route(TriageInput(
            tier=t.tier, special_data=t.special_data,
            sanctions_exposure=t.sanctions_exposure, cross_border=t.cross_border,
            uses_ai=t.uses_ai, inherent_band=band,
        ))
        store.audit.append(eng.org_id, "inherent.scored", "system",
                           {"engagement_id": eid, "score": irq.exposure_score,
                            "band": band.value, "routing": routing.value})
        return {"engagement_id": eid, "inherent_band": band.value,
                "routing": routing.value}

    @app.post("/api/v1/engagements/{eid}/decision")
    def decision(eid: str, d: DecisionIn):
        eng = _get(eid)
        controls = [ControlResult(c.control_id, c.domain, c.outcome, c.is_critical)
                    for c in d.controls]
        residual = residual_band(d.exposure_score, controls)

        final_band = residual.band
        override_used = False
        # Justified override (Q3 / BRO): human-only, requires reason + 2nd approval.
        if d.override_band is not None:
            if not d.actor_is_human:
                raise HTTPException(403, "override requires a human actor")
            if not d.override_reason or not d.second_approver:
                raise HTTPException(400,
                    "override requires justification and a second approver")
            final_band = d.override_band
            override_used = True

        # advance lifecycle toward decision
        if eng.stage in (Stage.INHERENT, Stage.DILIGENCE):
            target = Stage.DECISION
            if eng.stage is Stage.INHERENT and not eng.can_transition_to(target):
                pass
            try:
                eng.transition(Stage.DECISION, "decision_recorded",
                               notify_vrm=True, notify_business=True)
            except IllegalTransition:
                raise HTTPException(409, f"cannot decide from {eng.stage.value}")

        store.audit.append(eng.org_id, "decision.recorded", d.actor_id,
            {"engagement_id": eid, "computed_band": residual.band.value,
             "final_band": final_band.value,
             "critical_override": residual.critical_override_applied,
             "human_override": override_used,
             "override_reason": d.override_reason,
             "second_approver": d.second_approver})
        return {
            "engagement_id": eid,
            "computed_band": residual.band.value,
            "critical_override_applied": residual.critical_override_applied,
            "final_band": final_band.value,
            "human_override_applied": override_used,
            "rationale": residual.rationale,
        }

    @app.get("/api/v1/engagements/{eid}")
    def get_engagement(eid: str):
        eng = _get(eid)
        return {"engagement_id": eid, "vendor_id": eng.vendor_id,
                "stage": eng.stage.value,
                "notifications": [n.event for n in eng.notifications]}

    @app.get("/api/v1/audit/verify")
    def verify_audit():
        return {"intact": store.audit.verify(),
                "entries": len(store.audit.entries())}

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": "3.1"}

    return app


app = create_app()
