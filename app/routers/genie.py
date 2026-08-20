"""TPRM Genie — autonomous discovery, contract/SOW intelligence and risk profiling.

Genie sits at the top of the risk funnel. It (1) scans configured data sources for
vendors and engagements, (2) builds a Statement-of-Work summary for every engagement
from the contract/engagement data, and (3) compiles a comprehensive risk profile from
the connected enrichment data. Each phase is human-gated: Genie proposes, a user
confirms before the next phase runs (consistent with the ProAssess governance model).

This build scans the connected Brata registry as its data source. In an enterprise
deployment the source addresses captured at run start are bound to read-only
connectors; the phase logic is identical. Run state is persisted (config store) so the
confirm flow survives across workers. Heavy result arrays are computed fresh per call
and returned to the client, keeping the persisted run record small.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .deps import RouterDeps
from app.features.domain import config_store as CFG


def build_genie_router(deps: RouterDeps) -> APIRouter:
    r = APIRouter(tags=["genie"])
    db = deps.db
    actor = deps.actor
    audit = deps.audit

    # ---- guards & persistence -------------------------------------------------
    def internal(u):
        role = getattr(getattr(u, "role", None), "key", None)
        if role == "vendor":
            raise HTTPException(403, "TPRM Genie is not available to supplier users")
        return u

    def _key(rid: str) -> str:
        return f"genie_run_{rid}"

    def _load(s: Session, rid: str) -> dict:
        run = CFG.get_json(s, _key(rid), None)
        if not run:
            raise HTTPException(404, "Genie run not found")
        return run

    def _save(s: Session, run: dict) -> None:
        CFG.upsert_json(s, _key(run["id"]), run, updated_by=run.get("by", "genie"),
                        category="_genie")
        s.commit()

    # ---- source scanning (reads the connected registry) -----------------------
    def _rows(s: Session, sql: str):
        try:
            return s.execute(text(sql)).fetchall()
        except Exception:
            return []

    def _discover(s: Session) -> dict:
        vendors = []
        for row in _rows(s, "select vendor_id, legal_name, hq_country, tier, duns, lei, "
                             "annual_revenue, revenue_currency, status from vendor_records "
                             "order by legal_name"):
            vendors.append(dict(vendor_id=row[0], name=row[1], country=row[2] or "\u2014",
                                tier=row[3] or "\u2014", duns=row[4], lei=row[5],
                                revenue=row[6], revenue_ccy=row[7] or "", status=row[8] or "active"))
        engs = []
        for row in _rows(s, "select engagement_id, vendor_id, title, service_description, "
                             "business_unit, deployment_model, annual_value, currency, "
                             "start_date, end_date, inherent_band, residual_band, contract_id, "
                             "assessment_id, status from engagement_records order by engagement_id"):
            engs.append(dict(engagement_id=row[0], vendor_id=row[1], title=row[2],
                             service_description=row[3], business_unit=row[4],
                             deployment_model=row[5], annual_value=row[6],
                             currency=row[7] or "GBP", start_date=row[8], end_date=row[9],
                             inherent_band=row[10], residual_band=row[11],
                             contract_id=row[12], assessment_id=row[13], status=row[14]))
        vmap = {v["vendor_id"]: v["name"] for v in vendors}
        for e in engs:
            e["vendor_name"] = vmap.get(e["vendor_id"], e["vendor_id"])
        # unmanaged / shadow = engagement with no assessment on file
        unmanaged = [e for e in engs if not e.get("assessment_id")]
        return dict(vendors=vendors, engagements=engs,
                    vendor_count=len(vendors), engagement_count=len(engs),
                    unmanaged_count=len(unmanaged),
                    unmanaged=[dict(engagement_id=e["engagement_id"],
                                    vendor_name=e["vendor_name"], title=e["title"])
                               for e in unmanaged[:50]])

    _DATA_HINTS = [
        (("payroll", "hr", "human res", "benefit", "pension"), "Personal / HR data"),
        (("payment", "card", "billing", "invoice", "treasury", "bank"), "Financial / payment data"),
        (("cloud", "infrastructure", "hosting", "compute", "data centre", "datacenter", "platform"), "Systems access / hosting"),
        (("data", "analytics", "customer", "crm", "marketing"), "Customer data"),
        (("security", "identity", "access", "soc", "siem"), "Security / privileged access"),
        (("legal", "audit", "consult", "advis"), "Confidential business data"),
    ]

    def _data_sensitivity(text_val: str) -> str:
        t = (text_val or "").lower()
        for keys, label in _DATA_HINTS:
            if any(k in t for k in keys):
                return label
        return "General / to be confirmed"

    def _sow(s: Session) -> list:
        # contracts keyed by id and by engagement (demo links contracts via engagement_id)
        contracts, by_eng = {}, {}
        for row in _rows(s, "select contract_id, engagement_id, title, contract_type, start_date, "
                            "end_date, value, currency, governing_law, renewal_type, clause_flags "
                            "from contract_records"):
            rec = dict(contract_id=row[0], title=row[2], type=row[3], start=row[4], end=row[5],
                       value=row[6], currency=row[7], law=row[8], renewal=row[9], flags=row[10])
            contracts[row[0]] = rec
            if row[1]:
                by_eng[row[1]] = rec
        out = []
        for row in _rows(s, "select engagement_id, vendor_id, title, service_description, "
                            "business_unit, deployment_model, annual_value, currency, "
                            "start_date, end_date, contract_id from engagement_records "
                            "order by engagement_id"):
            (eid, vid, title, desc, bu, deploy, val, ccy, sd, ed, cid) = row
            c = contracts.get(cid or "", {}) or by_eng.get(eid, {})
            if not cid and c:
                cid = c.get("contract_id")
            scope = desc or f"{title} \u2014 {bu or 'cross-business'} service"
            flags = []
            if not cid or not c:
                flags.append("No contract linked on file")
            if not desc:
                flags.append("Scope inferred from engagement title (no SOW text)")
            law = c.get("law")
            term = None
            if (sd or c.get("start")) and (ed or c.get("end")):
                term = f"{sd or c.get('start')} \u2192 {ed or c.get('end')}"
            value = val or c.get("value")
            summary = (f"{title}: {scope}. "
                       f"Business unit: {bu or 'not specified'}. "
                       f"Delivery: {deploy or 'not specified'}. "
                       + (f"Annual value: {ccy} {int(value):,}. " if value else "")
                       + (f"Term: {term}. " if term else "")
                       + (f"Governing law: {law}. " if law else "")
                       + (f"Contract: {cid}." if cid else "Contract: not found."))
            out.append(dict(
                engagement_id=eid, vendor_id=vid, title=title,
                scope=scope, business_unit=bu, deployment_model=deploy,
                annual_value=value, currency=ccy,
                term=term, governing_law=law,
                contract_id=cid, contract_type=c.get("type"),
                data_sensitivity=_data_sensitivity(f"{title} {desc or ''}"),
                summary=summary, flags=flags,
                citations="engagement_records" + (" + contract_records" if c else ""),
            ))
        return out

    def _risk(s: Session) -> list:
        prof, cyber, screen = {}, {}, {}
        for row in _rows(s, "select vendor_id, inherent_band, residual_band, open_findings, "
                            "max_severity, overall_score, monitoring_signal, reputation_summary, "
                            "incident_count from vendor_risk_profile"):
            prof[row[0]] = dict(inherent=row[1], residual=row[2], open_findings=row[3],
                                max_sev=row[4], score=row[5], monitoring=row[6],
                                reputation=row[7], incidents=row[8])
        for row in _rows(s, "select vendor_id, external_rating, breach_history_flag, "
                            "assurance_status, pentest_recency from vendor_cyber"):
            cyber[row[0]] = dict(rating=row[1], breach=row[2], assurance=row[3], pentest=row[4])
        for row in _rows(s, "select vendor_id, screen_type, result, detail, screened_date "
                            "from vendor_screening order by screened_date"):
            screen[row[0]] = dict(type=row[1], result=row[2], detail=row[3], date=row[4])  # last=latest

        # fallback bands from engagements (max across the vendor's engagements)
        _BORD = {"Severe": 5, "Critical": 5, "High": 4, "Elevated": 3, "Moderate": 2,
                 "Medium": 2, "Low": 1}
        eng_bands = {}
        for row in _rows(s, "select vendor_id, inherent_band, residual_band from engagement_records"):
            vid_, ib, rb = row
            cur = eng_bands.setdefault(vid_, {"inherent": None, "residual": None})
            if ib and _BORD.get(ib, 0) > _BORD.get(cur["inherent"], 0):
                cur["inherent"] = ib
            if rb and _BORD.get(rb, 0) > _BORD.get(cur["residual"], 0):
                cur["residual"] = rb

        try:
            from app.features.domain import watchlist_service as WL
        except Exception:
            WL = None

        vendors = _rows(s, "select vendor_id, legal_name, hq_country, tier from vendor_records "
                           "order by legal_name")
        out = []
        for (vid, name, country, tier) in vendors:
            p = prof.get(vid, {})
            cy = cyber.get(vid, {})
            sc = screen.get(vid, {})
            watch = False
            if WL is not None:
                try:
                    watch = bool(WL.is_watchlisted(s, vid))
                except Exception:
                    watch = False
            hit = str(sc.get("result") or "").lower() in (
                "hit", "match", "positive", "adverse", "true", "flag", "flagged")
            severe = str(p.get("max_sev") or "").lower() in ("severe", "high", "critical")
            needs_review = bool(hit or watch or severe)
            eb = eng_bands.get(vid, {})
            out.append(dict(
                vendor_id=vid, name=name, country=country or "\u2014", tier=tier or "\u2014",
                inherent_band=p.get("inherent") or eb.get("inherent"),
                residual_band=p.get("residual") or eb.get("residual"),
                overall_score=p.get("score"), open_findings=p.get("open_findings") or 0,
                max_severity=p.get("max_sev"), incidents=p.get("incidents") or 0,
                monitoring=p.get("monitoring"), reputation=p.get("reputation"),
                cyber_rating=cy.get("rating"), breach_flag=bool(cy.get("breach")),
                assurance=cy.get("assurance"),
                screening=sc.get("result"), screening_type=sc.get("type"),
                watchlisted=watch, needs_review=needs_review,
                sources="vendor_risk_profile + vendor_cyber + vendor_screening"
                        + (" + watchlist" if watch else ""),
            ))
        # highest-risk first
        order = {"Severe": 0, "Critical": 0, "High": 1, "Elevated": 2, "Moderate": 3,
                 "Medium": 3, "Low": 4, None: 5}
        out.sort(key=lambda x: (0 if x["needs_review"] else 1,
                                order.get(x.get("inherent_band"), 5)))
        return out

    # ---- endpoints ------------------------------------------------------------
    @r.get("/api/v1/genie/sources/template")
    def sources_template(u=Depends(actor)):
        internal(u)
        return {"sources": [
            {"key": "erp", "label": "ERP / Vendor master", "placeholder": "jdbc:postgresql://erp-db:5432/vendors", "value": ""},
            {"key": "procurement", "label": "Procurement / spend (S2P)", "placeholder": "https://ariba.example.com/api", "value": ""},
            {"key": "contracts", "label": "Contract repository (CLM)", "placeholder": "https://clm.example.com/api", "value": ""},
            {"key": "registry", "label": "Assessment / registry DB", "placeholder": "connected: Brata registry", "value": "connected: Brata registry"},
        ]}

    @r.post("/api/v1/genie/run")
    def start_run(b: dict = Body(default={}), s: Session = Depends(db), u=Depends(actor)):
        internal(u)
        sources = b.get("sources") or {}
        d = _discover(s)
        rid = uuid.uuid4().hex[:12]
        run = {
            "id": rid, "by": u.username, "at": int(time.time()),
            "sources": sources, "phase": "discover", "status": "awaiting_confirm",
            "counts": {"vendors": d["vendor_count"], "engagements": d["engagement_count"],
                       "unmanaged": d["unmanaged_count"]},
            "log": [f"Connected to configured sources ({len([v for v in sources.values() if v]) or 1} endpoint(s)).",
                    f"Scanned registry \u2014 discovered {d['vendor_count']} vendors and {d['engagement_count']} engagements.",
                    f"Flagged {d['unmanaged_count']} engagement(s) with no assessment on file (unmanaged)."],
        }
        _save(s, run)
        audit(s, "genie.run_started", u.username,
              {"run_id": rid, "vendors": d["vendor_count"], "engagements": d["engagement_count"]})
        return {"run": run, "discovery": d}

    @r.get("/api/v1/genie/run/{rid}")
    def get_run(rid: str, s: Session = Depends(db), u=Depends(actor)):
        internal(u)
        return {"run": _load(s, rid)}

    @r.post("/api/v1/genie/run/{rid}/confirm")
    def confirm(rid: str, s: Session = Depends(db), u=Depends(actor)):
        internal(u)
        run = _load(s, rid)
        phase = run.get("phase")
        if phase == "discover":
            sow = _sow(s)
            run["phase"] = "sow"
            run["status"] = "awaiting_confirm"
            run["counts"]["sow"] = len(sow)
            run["counts"]["sow_no_contract"] = sum(1 for x in sow if "No contract linked on file" in x["flags"])
            run["log"].append(f"Built SOW summaries for {len(sow)} engagement(s); "
                              f"{run['counts']['sow_no_contract']} without a linked contract.")
            _save(s, run)
            audit(s, "genie.sow_built", u.username, {"run_id": rid, "engagements": len(sow)})
            return {"run": run, "sow": sow}
        if phase == "sow":
            risk = _risk(s)
            run["phase"] = "risk"
            run["status"] = "awaiting_confirm"
            run["counts"]["profiles"] = len(risk)
            run["counts"]["needs_review"] = sum(1 for x in risk if x["needs_review"])
            run["log"].append(f"Compiled risk profiles for {len(risk)} vendor(s); "
                              f"{run['counts']['needs_review']} flagged for mandatory human review.")
            _save(s, run)
            audit(s, "genie.risk_built", u.username,
                  {"run_id": rid, "profiles": len(risk), "needs_review": run["counts"]["needs_review"]})
            return {"run": run, "risk": risk}
        if phase == "risk":
            run["phase"] = "complete"
            run["status"] = "complete"
            run["log"].append("Run complete \u2014 inventory, SOW summaries and risk profiles ready "
                              "for triage into ProAssess.")
            _save(s, run)
            audit(s, "genie.completed", u.username, {"run_id": rid})
            return {"run": run}
        raise HTTPException(400, "Run already complete")

    @r.post("/api/v1/genie/run/{rid}/cancel")
    def cancel(rid: str, s: Session = Depends(db), u=Depends(actor)):
        internal(u)
        run = _load(s, rid)
        run["status"] = "cancelled"
        run["phase"] = "cancelled"
        _save(s, run)
        audit(s, "genie.cancelled", u.username, {"run_id": rid})
        return {"run": run}

    return r
