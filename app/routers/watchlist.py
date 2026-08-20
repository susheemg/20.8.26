"""Watchlist module router — entries, criteria, sweep, candidates, and supplier notes.

Visibility: watchlist and notes are readable by all internal roles (require
`watchlist.view` / `note.view`) — the supplier role holds neither, so suppliers
are blocked at the function level. Mutation of watchlist data is Controller-only
(`watchlist.edit` / `watchlist.sweep` / `watchlist.approve`); admin has ALL.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from .deps import RouterDeps
from app.features.domain import watchlist_service as WL


def build_watchlist_router(deps: RouterDeps) -> APIRouter:
    r = APIRouter(tags=["watchlist"])
    db = deps.db
    require = deps.require
    audit = deps.audit

    # ---------- criteria ----------
    @r.get("/api/v1/watchlist/criteria")
    def list_criteria(s: Session = Depends(db), u=Depends(require("watchlist.view"))):
        return WL.list_criteria(s)

    @r.post("/api/v1/watchlist/criteria")
    def add_criterion(b: dict = Body(...), s: Session = Depends(db),
                      u=Depends(require("watchlist.edit"))):
        if not b.get("name"):
            raise HTTPException(400, "name is required")
        c = WL.add_criterion(s, b, u.username)
        audit(s, "watchlist.criterion_added", u.username, {"criterion_id": c["criterion_id"]})
        return c

    @r.patch("/api/v1/watchlist/criteria/{cid}")
    def update_criterion(cid: str, b: dict = Body(...), s: Session = Depends(db),
                         u=Depends(require("watchlist.edit"))):
        try:
            c = WL.update_criterion(s, cid, b)
        except ValueError as e:
            raise HTTPException(404, str(e))
        audit(s, "watchlist.criterion_updated", u.username, {"criterion_id": cid})
        return c

    @r.delete("/api/v1/watchlist/criteria/{cid}")
    def delete_criterion(cid: str, s: Session = Depends(db),
                         u=Depends(require("watchlist.edit"))):
        WL.delete_criterion(s, cid)
        audit(s, "watchlist.criterion_deleted", u.username, {"criterion_id": cid})
        return {"deleted": cid}

    # ---------- entries ----------
    @r.get("/api/v1/watchlist/entries")
    def list_entries(status: str = "Active", s: Session = Depends(db),
                     u=Depends(require("watchlist.view"))):
        return WL.list_entries(s, status)

    @r.get("/api/v1/watchlist/vendor/{vendor_id}")
    def vendor_watchlist(vendor_id: str, s: Session = Depends(db),
                         u=Depends(require("watchlist.view"))):
        entries = WL.entries_for_vendor(s, vendor_id, status="all")
        return {"vendor_id": vendor_id, "watchlisted": WL.is_watchlisted(s, vendor_id),
                "entries": entries}

    @r.post("/api/v1/watchlist/entries")
    def add_entry(b: dict = Body(...), s: Session = Depends(db),
                  u=Depends(require("watchlist.edit"))):
        if not b.get("vendor_id") or not b.get("reason"):
            raise HTTPException(400, "vendor_id and reason are required")
        e = WL.add_entry(s, b, u.username)
        audit(s, "watchlist.entry_added", u.username,
              {"entry_id": e["entry_id"], "vendor_id": b["vendor_id"]})
        return e

    @r.patch("/api/v1/watchlist/entries/{eid}")
    def update_entry(eid: str, b: dict = Body(...), s: Session = Depends(db),
                     u=Depends(require("watchlist.edit"))):
        try:
            e = WL.update_entry(s, eid, b, u.username)
        except ValueError as ex:
            raise HTTPException(404, str(ex))
        audit(s, "watchlist.entry_updated", u.username, {"entry_id": eid})
        return e

    @r.delete("/api/v1/watchlist/entries/{eid}")
    def delete_entry(eid: str, s: Session = Depends(db),
                     u=Depends(require("watchlist.edit"))):
        WL.delete_entry(s, eid)
        audit(s, "watchlist.entry_deleted", u.username, {"entry_id": eid})
        return {"deleted": eid}

    # ---------- sweep + candidates ----------
    @r.post("/api/v1/watchlist/sweep")
    def sweep(s: Session = Depends(db), u=Depends(require("watchlist.sweep"))):
        res = WL.run_sweep(s, u.username)
        audit(s, "watchlist.sweep_run", u.username,
              {"created": res["created"], "scanned": res["vendors_scanned"]})
        return res

    @r.get("/api/v1/watchlist/candidates")
    def list_candidates(status: str = "pending", s: Session = Depends(db),
                        u=Depends(require("watchlist.view"))):
        return WL.list_candidates(s, status)

    @r.post("/api/v1/watchlist/candidates/{cand_id}/decide")
    def decide_candidate(cand_id: str, b: dict = Body(...), s: Session = Depends(db),
                         u=Depends(require("watchlist.approve"))):
        decision = (b or {}).get("decision")
        if decision not in ("approve", "reject"):
            raise HTTPException(400, "decision must be 'approve' or 'reject'")
        try:
            res = WL.decide_candidate(s, cand_id, decision, u.username)
        except ValueError as e:
            raise HTTPException(400, str(e))
        audit(s, "watchlist.candidate_decided", u.username,
              {"candidate_id": cand_id, "decision": decision})
        return res

    @r.get("/api/v1/watchlist/summary")
    def summary(s: Session = Depends(db), u=Depends(require("watchlist.view"))):
        return WL.summary(s)

    # ---------- supplier notes (internal-only) ----------
    @r.get("/api/v1/vendors/{vendor_id}/notes")
    def list_notes(vendor_id: str, s: Session = Depends(db),
                   u=Depends(require("note.view"))):
        return WL.list_notes(s, vendor_id)

    @r.post("/api/v1/vendors/{vendor_id}/notes")
    def add_note(vendor_id: str, b: dict = Body(...), s: Session = Depends(db),
                 u=Depends(require("note.add"))):
        body = (b or {}).get("body", "").strip()
        if not body:
            raise HTTPException(400, "note body is required")
        n = WL.add_note(s, vendor_id, body, u.username, (b or {}).get("category", "General"))
        audit(s, "note.added", u.username, {"vendor_id": vendor_id, "note_id": n["note_id"]})
        return n

    @r.delete("/api/v1/vendors/{vendor_id}/notes/{note_id}")
    def delete_note(vendor_id: str, note_id: str, s: Session = Depends(db),
                    u=Depends(require("note.add"))):
        WL.delete_note(s, note_id)
        audit(s, "note.deleted", u.username, {"vendor_id": vendor_id, "note_id": note_id})
        return {"deleted": note_id}

    return r
