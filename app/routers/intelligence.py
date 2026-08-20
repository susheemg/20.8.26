"""Auto-extracted intelligence routes (RouterDeps pattern). See app/routers/deps.py.

Behaviour is byte-identical to the pre-split monolith; per-instance deps are bound
as locals (multi-app isolation), invariant models/imports come from bro_app globals.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import (PlainTextResponse, StreamingResponse,
    HTMLResponse, JSONResponse, FileResponse, RedirectResponse)

from .deps import RouterDeps
from ._shared import bind_shared
import app.features.admin.rbac as _RBAC


def build_intelligence_router(deps: RouterDeps) -> APIRouter:
    import app.bro_app as _M
    globals().update({k: v for k, v in vars(_M).items() if not k.startswith("__")})
    r = APIRouter()
    app = r
    db = deps.db
    actor = deps.actor
    require = deps.require
    audit = deps.audit
    notify = deps.notify
    _fb_guidance = deps.fb_guidance
    _ai_live = deps.ai_live
    AI_HOLDING = deps.ai_holding
    engine = deps.engine
    _platform_version = deps.platform_version
    SessionFactory = deps.session_factory
    _sh = bind_shared(deps)
    _monitor_interval = _sh["_monitor_interval"]
    _rmd_row = _sh["_rmd_row"]
    _file_monitoring_report = _sh["_file_monitoring_report"]
    _ai_research = _sh["_ai_research"]
    _start_research_job = _sh["_start_research_job"]
    _research_job_status = _sh["_research_job_status"]
    # --- build-level imports replicated from the pre-split factory ---
    from app.features.admin import identity as IDP
    from app.features.domain.models_db import hash_password as _hash_pw
    import secrets as _secrets
    from app.features.intelligence import sanctions as SANC
    from app.features.domain.registry_models import SanctionsScreening, WatchlistEntry, VendorPerson
    from app.features.lifecycle import monitoring as MON
    from fastapi.responses import PlainTextResponse
    import csv as _csv, io as _io
    from datetime import datetime as _dt2
    from app.features.assessment import agents as _A
    from app.features.assessment import agent_engine as _AE
    from app.features.domain.models_feature import AgentLearning, BackgroundInsight
    from app.features.domain import registry_service as RS
    from app.features.intelligence import financial as FIN
    from app.features.domain.registry_models import (
        IndustryMaster, MaterialGroupMaster, VendorGroup, VendorRecord,
        VendorIndustry, ContactRecord, EngagementRecord, AssessmentRecord,
        FindingRecord, RemediationRecord, FourthPartyRecord, FourthPartyVendor,
        ArtefactRecord, IssueRecord,
    )
    import json as _json2, os as _os2
    from app.features.lifecycle import performance_service as PERF
    from app.features.platform import platform_docs as PDOCS
    from app.features.assessment import learnings as LEARN
    from app.features.admin import integrations as INTEG
    from app.features.admin import content as CONTENT
    from app.features.admin import layout as LAYOUT


    @app.post("/api/v1/intel/financial")
    def intel_financial(b: IntelIn, s: Session = Depends(db),
                        u: User = Depends(require("intel.financial"))):
        out = intel.vera_financial(b.payload)
        s.add(IntelResult(vendor_id=b.vendor_id, engine="financial",
                          score=out.score, band=out.band, narrative=out.narrative))
        audit(s, "intel.financial", u.username, {"vendor_id": b.vendor_id, "band": out.band})
        s.commit()
        return out.__dict__

    @app.post("/api/v1/intel/reputation")
    def intel_reputation(b: IntelIn, s: Session = Depends(db),
                         u: User = Depends(require("intel.reputation"))):
        out = intel.mira_reputation(b.payload)
        s.add(IntelResult(vendor_id=b.vendor_id, engine="reputation",
                          score=out.score, band=out.band, narrative=out.narrative))
        audit(s, "intel.reputation", u.username, {"vendor_id": b.vendor_id, "band": out.band})
        s.commit()
        return out.__dict__

    # ===== Sanctions & AML screening (part of reputation checks) =====
    from app.features.intelligence import sanctions as SANC
    from app.features.domain.registry_models import SanctionsScreening, WatchlistEntry, VendorPerson

    def _live_entries(s: Session) -> list:
        """Load ingested live-feed entries (e.g. OFSI) into the engine's entry format."""
        out = []
        for w in s.scalars(select(WatchlistEntry)).all():
            out.append({"id": w.ext_id, "name": w.name, "aliases": json.loads(w.aliases or "[]"),
                        "category": w.category, "source": w.source, "list": w.list_name,
                        "program": w.program, "country": w.country, "nationality": w.nationality,
                        "entity_type": w.entity_type, "dob": w.dob, "live": True})
        return out

    def _apply_screening_outcome(s: Session, vendor_id, vendor_name, band, detail, by):
        return RS.apply_screening_outcome(s, vendor_id, vendor_name, band, detail, by,
                                          audit_fn=audit)

    @app.get("/api/v2/sanctions/sources")
    def v2_sanctions_sources(u: User = Depends(require("vendor.view"))):
        return SANC.sources()

    @app.post("/api/v2/sanctions/screen")
    def v2_sanctions_screen(body: dict = Body(default={}), s: Session = Depends(db),
                            u: User = Depends(require("vendor.view"))):
        name = (body.get("name") or "").strip()
        country = body.get("country"); dob = body.get("dob"); nationality = body.get("nationality")
        vid = body.get("vendor_id")
        if vid and not name:
            v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vid)).first()
            if not v:
                raise HTTPException(404, "vendor not found")
            name = v.legal_name
            country = country or v.hq_country
        if not name:
            raise HTTPException(400, "name or vendor_id required")
        res = SANC.screen_name(name, country, dob, nationality, extra=_live_entries(s))
        sid = RS.next_id(s, "screening")
        s.add(SanctionsScreening(
            screening_id=sid, vendor_id=vid, screened_name=name, country=country,
            band=res["band"], hit_count=res["hit_count"], hits=json.dumps(res["hits"]),
            sources_used=json.dumps(res["sources_screened"]), screened_by=u.username))
        if vid:
            top = res["hits"][0]["matched_name"] if res["hits"] else ""
            res["risk"] = _apply_screening_outcome(
                s, vid, name, res["band"],
                f"{res['band']} — {name} vs {top}".strip(" —"), u.username)
        audit(s, "sanctions.screen", u.username,
              {"screening_id": sid, "vendor_id": vid, "name": name, "band": res["band"]})
        s.commit()
        res["screening_id"] = sid
        return res

    @app.get("/api/v2/sanctions/screenings")
    def v2_sanctions_screenings(vendor_id: Optional[str] = None, limit: int = 50,
                                s: Session = Depends(db),
                                u: User = Depends(require("vendor.view"))):
        stmt = select(SanctionsScreening).order_by(SanctionsScreening.id.desc())
        rows = s.scalars(stmt).all()
        if vendor_id:
            rows = [r for r in rows if r.vendor_id == vendor_id]
        return [{"screening_id": r.screening_id, "vendor_id": r.vendor_id,
                 "screened_name": r.screened_name, "country": r.country, "band": r.band,
                 "hit_count": r.hit_count, "hits": json.loads(r.hits or "[]"),
                 "screened_by": r.screened_by,
                 "created_at": r.created_at.isoformat() if r.created_at else None}
                for r in rows[:limit]]

    @app.get("/api/v2/sanctions/summary")
    def v2_sanctions_summary(s: Session = Depends(db),
                             u: User = Depends(require("vendor.view"))):
        """Deterministic portfolio sweep — screens every registered vendor's legal name."""
        live = _live_entries(s)
        dist = {"Clear": 0, "Review": 0, "Hit": 0}
        flagged = []
        for v in s.scalars(select(VendorRecord)).all():
            r = SANC.screen_name(v.legal_name, v.hq_country, extra=live)
            dist[r["band"]] = dist.get(r["band"], 0) + 1
            if r["band"] != "Clear":
                flagged.append({"vendor_id": v.vendor_id, "legal_name": v.legal_name,
                                "band": r["band"], "hit_count": r["hit_count"],
                                "top": r["hits"][0] if r["hits"] else None})
        flagged.sort(key=lambda f: (f["band"] != "Hit", -f["hit_count"]))
        return {"distribution": dist, "flagged": flagged, "screened": sum(dist.values()),
                "representative": not bool(live), "live_entries": len(live)}

    # ---- live issuer feed: OFSI (UK consolidated list, free CSV) ----
    @app.get("/api/v2/sanctions/feeds")
    def v2_sanctions_feeds(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        feeds = {}
        for w in s.scalars(select(WatchlistEntry)).all():
            f = feeds.setdefault(w.source, {"source": w.source, "count": 0, "last_loaded": None})
            f["count"] += 1
            ts = w.loaded_at.isoformat() if w.loaded_at else None
            if ts and (not f["last_loaded"] or ts > f["last_loaded"]):
                f["last_loaded"] = ts
        return {"feeds": list(feeds.values()), "ofsi_url": SANC.OFSI_URL}

    def _ingest_feed(s: Session, source: str, entries: list) -> int:
        from datetime import datetime, timezone
        src = f"{source} (live)"
        existing = {w.ext_id: w for w in s.scalars(
            select(WatchlistEntry).where(WatchlistEntry.source == src)).all()}
        loaded = 0
        for e in entries:
            w = existing.get(e["id"])
            if not w:
                w = WatchlistEntry(ext_id=e["id"], source=src); s.add(w)
            w.name = e["name"]; w.aliases = json.dumps(e.get("aliases", []))
            w.category = e["category"]; w.list_name = e.get("list"); w.program = e.get("program")
            w.country = e.get("country"); w.nationality = e.get("nationality")
            w.entity_type = e.get("entity_type"); w.dob = e.get("dob")
            w.loaded_at = datetime.now(timezone.utc)
            loaded += 1
        return loaded

    @app.post("/api/v2/sanctions/load-feed")
    def v2_sanctions_load_feed(body: dict = Body(default={}), s: Session = Depends(db),
                               u: User = Depends(require("admin.config"))):
        """Ingest an issuer feed. source in OFSI/OFAC/UN/EU. Tries the live URL; if egress
        is blocked, accepts the file in the body (`csv` or `xml`/`text`)."""
        source = (body.get("source") or "OFSI").upper()
        if source not in SANC.FEED_LOADERS:
            raise HTTPException(400, f"unknown source {source}")
        text = body.get("csv") or body.get("xml") or body.get("text")
        via = "uploaded file"
        if not text:
            try:
                text = SANC.fetch_feed(source, body.get("url")); via = "live fetch"
            except Exception as e:
                raise HTTPException(502, f"{source} fetch failed ({e}); allowlist the issuer "
                                         f"host on this network, or POST the file in the body.")
        try:
            entries = SANC.load_feed(source, text)
        except Exception as e:
            raise HTTPException(400, f"could not parse {source} feed: {e}")
        loaded = _ingest_feed(s, source, entries)
        audit(s, "sanctions.load_feed", u.username, {"source": source, "loaded": loaded, "via": via})
        s.commit()
        total = s.scalar(select(func.count()).select_from(WatchlistEntry)
                         .where(WatchlistEntry.source == f"{source} (live)"))
        return {"source": source, "loaded": loaded, "via": via, "total": total}

    @app.post("/api/v2/sanctions/load-ofsi")
    def v2_sanctions_load_ofsi(body: dict = Body(default={}), s: Session = Depends(db),
                               u: User = Depends(require("admin.config"))):
        body = dict(body or {}); body["source"] = "OFSI"
        return v2_sanctions_load_feed(body, s, u)

    # ---- beneficial owners / key people + entity screening ----
    @app.post("/api/v2/sanctions/screen-vendor/{vid}")
    def v2_screen_vendor_entities(vid: str, s: Session = Depends(db),
                                  u: User = Depends(require("vendor.view"))):
        """Screen the vendor entity AND each beneficial owner / key person, applying
        DOB + nationality disambiguation. Persists each screen and returns an aggregate."""
        _RBAC.assert_object_visible(s, u, "vendor", vid)
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vid)).first()
        if not v:
            raise HTTPException(404, "vendor not found")
        live = _live_entries(s)

        def _persist(name, country, res):
            sid = RS.next_id(s, "screening")
            s.add(SanctionsScreening(screening_id=sid, vendor_id=vid, screened_name=name,
                                     country=country, band=res["band"], hit_count=res["hit_count"],
                                     hits=json.dumps(res["hits"]),
                                     sources_used=json.dumps(res["sources_screened"]),
                                     screened_by=u.username))
            return sid

        entity_res = SANC.screen_name(v.legal_name, v.hq_country, extra=live)
        entity_res["screening_id"] = _persist(v.legal_name, v.hq_country, entity_res)
        people = []
        bands = [entity_res["band"]]
        for p in s.scalars(select(VendorPerson).where(VendorPerson.vendor_id == vid)).all():
            pr = SANC.screen_name(p.name, p.nationality, p.dob, p.nationality, extra=live)
            pr["screening_id"] = _persist(p.name, p.nationality, pr)
            bands.append(pr["band"])
            people.append({"person_id": p.person_id, "name": p.name, "role": p.role,
                           "dob": p.dob, "nationality": p.nationality,
                           "is_ubo": p.is_ubo, "result": pr})
        order = {"Hit": 2, "Review": 1, "Clear": 0}
        overall = max(bands, key=lambda b: order.get(b, 0)) if bands else "Clear"
        # compose a detail naming the worst subject, then wire into risk + Issues
        worst = entity_res
        worst_subj = v.legal_name
        for p in people:
            if order.get(p["result"]["band"], 0) > order.get(worst["band"], 0):
                worst = p["result"]; worst_subj = f"owner {p['name']}"
        top = worst["hits"][0]["matched_name"] if worst["hits"] else ""
        risk = _apply_screening_outcome(s, vid, v.legal_name, overall,
                                        f"{overall} — {worst_subj} vs {top}".strip(" —"), u.username)
        audit(s, "sanctions.screen_vendor", u.username,
              {"vendor_id": vid, "overall": overall, "people": len(people)})
        s.commit()
        return {"vendor_id": vid, "legal_name": v.legal_name, "entity_result": entity_res,
                "people": people, "overall_band": overall, "risk": risk}

    # ===== monitoring (scheduled / on-request sweeps) =====
    from app.features.lifecycle import monitoring as MON

    @app.post("/api/v1/intel/contract")
    def intel_contract(b: IntelIn, s: Session = Depends(db),
                       u: User = Depends(require("intel.contract"))):
        v = s.get(Vendor, b.vendor_id)
        out = intel.matt_contract(v.tier if v else "Tier 3")
        audit(s, "intel.contract", u.username, {"vendor_id": b.vendor_id})
        s.commit()
        return out.__dict__

    @app.post("/api/v1/intel/evidence")
    def intel_evidence(b: IntelIn, s: Session = Depends(db),
                       u: User = Depends(require("intel.evidence"))):
        out = intel.isaac_evidence(b.payload.get("text", ""))
        s.add(IntelResult(vendor_id=b.vendor_id, engine="evidence",
                          score=out.score, band=out.band, narrative=out.narrative))
        audit(s, "intel.evidence", u.username, {"vendor_id": b.vendor_id, "band": out.band})
        s.commit()
        return out.__dict__

    # ===== monitoring lifecycle =====
    @app.get("/api/v2/pestle/exposure-summary")
    def v2_pestle_exposure_summary(focus_type: str = "portfolio", focus_id: Optional[str] = None,
                                   s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        """Narrative risk summary for the current knowledge-map focus. Deterministic;
        upgrades to AI when a model is connected."""
        from app.features.intelligence import pestle as PES
        from app.agents import llm_config
        try:
            d = PES.get_summary(s)
        except Exception:
            d = None
        if not d:
            return {"summary": "No PESTLE data yet — run an overnight sweep to populate the threat surface.",
                    "ai": False, "focus": focus_type}
        cats = d.get("categories", {})
        means = d.get("cat_means", {})
        top = d.get("top_threats", [])[:6]
        movers = d.get("movers", [])[:5]
        label = focus_id or "the portfolio"
        hi = sorted(means.items(), key=lambda x: -x[1])[:2]
        hi_txt = ", ".join(f"{cats.get(c, {}).get('name', c)} ({v})" for c, v in hi)
        top_txt = "; ".join(f"{t['name']} ({t['score']})" for t in top)
        mv_up = [m for m in movers if m.get("delta", 0) > 0][:3]
        mv_txt = ", ".join(f"{m['name']} ▲{abs(m['delta']):.1f}" for m in mv_up)
        det = (f"Focus: {label} ({focus_type}). Highest-exposure PESTLE categories are {hi_txt}. "
               f"The most systemic threats are {top_txt}. "
               + (f"Overnight, the sharpest deteriorations were {mv_txt}. " if mv_txt else "No material overnight moves. ")
               + "Prioritise the highest-scoring threats above for mitigation and monitor the movers.")
        ai = False
        if llm_config.status().get("live_ready"):
            try:
                out = llm_config.complete(
                    PROMPTS.resolve(s, "pestle_summary"),
                    f"Focus: {label} ({focus_type}). Category means: {means}. Top threats: {top}. Movers: {movers}.",
                    domain="risk", max_tokens=300, review=True)
                if out and out.strip():
                    det = out.strip(); ai = True
            except Exception as _e:
                _obs_swallow('bro_app.py', _e)
        return {"summary": det, "ai": ai, "focus": focus_type, "focus_id": focus_id}

    # ---- Controller: assign engagement to an assessor ----
    @app.get("/api/v2/graph/overview")
    def v2_graph_overview(u: User = Depends(require("vendor.view")), s: Session = Depends(db)):
        from app.features.intelligence import graph as GRAPH
        return GRAPH.build_graph(s)

    @app.get("/api/v2/graph/network")
    def v2_graph_network(u: User = Depends(require("vendor.view")), s: Session = Depends(db)):
        """Node-link data for the interactive entity brain map (read-only, live DB)."""
        from app.features.intelligence import graph as GRAPH
        return GRAPH.network(s)

    @app.post("/api/v2/graph/contagion")
    def v2_graph_contagion(b: ContagionIn, s: Session = Depends(db),
                           u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import graph as GRAPH
        if b.node_type not in ("fourth_party", "owner", "vendor"):
            raise HTTPException(400, "node_type must be fourth_party | owner | vendor")
        return GRAPH.contagion(s, b.node_type, b.node_id)

    # ===== Phase 3 — Exposure & event linkage =====
    @app.get("/api/v2/exposure/bu")
    def v2_exposure_bu(u: User = Depends(require("vendor.view")), s: Session = Depends(db)):
        from app.features.intelligence import exposure as EXP
        return EXP.bu_exposure(s)

    @app.post("/api/v2/exposure/brief")
    def v2_exposure_brief(b: BriefIn, s: Session = Depends(db),
                          u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import exposure as EXP
        from app.agents import llm_config
        prof = next((p for p in EXP.bu_exposure(s)["business_units"]
                     if p["business_unit"] == b.business_unit), None)
        if not prof:
            raise HTTPException(404, "business unit not found")
        rmix = ", ".join(f"{k} {v}" for k, v in prof["residual"].items() if v)
        deterministic = (f"{prof['business_unit']}: {prof['vendor_count']} vendors "
                         f"({prof['critical_count']} critical) across {prof['engagements']} engagements, "
                         f"£{prof['spend']:,} annual spend. Residual mix: {rmix or 'n/a'}. "
                         f"{prof['open_findings']} open findings. Exposure score {prof['exposure_score']}.")
        if not llm_config.status().get("live_ready"):
            return {"holding": True, "message": AI_HOLDING, "brief": deterministic, "profile": prof}
        try:
            out = llm_config.complete(
                PROMPTS.resolve(s, "exposure_brief"),
                f"Write an exposure brief for business unit '{prof['business_unit']}'. Data: {deterministic}",
                domain="risk", max_tokens=400)
            return {"holding": False, "brief": (out or deterministic).strip(), "profile": prof}
        except Exception:
            return {"holding": False, "brief": deterministic, "profile": prof}

    # ===== Phase 4 — Export-control / geopolitical sensor =====
    @app.get("/api/v2/geopolitical/exposure")
    def v2_geo_exposure(u: User = Depends(require("reg.view")), s: Session = Depends(db)):
        from app.features.intelligence import geopolitical as GEO
        return GEO.exposure(s)

    @app.post("/api/v2/geopolitical/scan")
    def v2_geo_scan(s: Session = Depends(db), u: User = Depends(require("reg.assess"))):
        from app.features.intelligence import geopolitical as GEO
        from app.agents import llm_config
        exp = GEO.exposure(s)
        countries = sorted({j["country"] for j in exp["jurisdictions"]
                            if GEO._LEVEL_RANK[j["level"]] >= 1})
        if not llm_config.status().get("live_ready"):
            return {"holding": True, "message": AI_HOLDING, "events": [], "exposed_countries": countries}
        if not countries:
            return {"holding": False, "events": [], "exposed_countries": []}
        prompt = "\n".join([
            "FS supply-chain analyst. Web-search 2026-onward export-control, sanctions and dual-use actions",
            "affecting these jurisdictions where our vendors / sub-processors sit: " + ", ".join(countries) + ".",
            "Cover: new export restrictions (esp. semiconductors / components → likely shortages),",
            "sanctions designations, Entity List additions, dual-use rule changes. Primary sources only.",
            "JSON array only, no prose/fences.",
            "Per item: {country:str,title:str,summary:str<=180c,impact:str<=120c,date:str,source:str}.",
            "Max 8 newest-first. Nothing new: []."])
        try:
            out = llm_config.complete(
                PROMPTS.resolve(s, "geopolitical_analyst"),
                prompt, domain="regulatory", web_search=True, max_tokens=1100)
            import json as _j
            t = (out or "").replace("```json", "").replace("```", "").strip()
            i, e = t.find("["), t.rfind("]")
            events = [x for x in _j.loads(t[i:e + 1]) if isinstance(x, dict)] if (i != -1 and e != -1) else []
        except Exception:
            events = []
        # map events to affected vendors by country
        by_country = {}
        for f in exp["flagged_vendors"]:
            by_country.setdefault(f["country"], []).append(
                {"vendor_id": f["vendor_id"], "legal_name": f["legal_name"], "via": f["via"]})
        for ev in events:
            ev["affected_vendors"] = by_country.get(ev.get("country"), [])
        audit(s, "v2.geo_scan", u.username, {"countries": countries, "events": len(events)})
        s.commit()
        return {"holding": False, "events": events, "exposed_countries": countries}

    # ===== Multilingual layer (display / input / documents) — backend stays English =====
    @app.get("/api/v2/stress-radar")
    def v2_stress_radar(u: User = Depends(require("vendor.view")), s: Session = Depends(db)):
        from app.features.intelligence import stress as STRESS
        return STRESS.radar(s)

    @app.get("/api/v2/scenario/options")
    def v2_scenario_options(u: User = Depends(require("vendor.view")), s: Session = Depends(db)):
        from app.features.intelligence import scenario as SCEN
        return SCEN.options(s)

    @app.get("/api/v2/scenario/fourth-party-impact/{vid}")
    def v2_scenario_fourth_party_impact(vid: str, s: Session = Depends(db),
                                        u: User = Depends(require("vendor.view"))):
        """Downstream 4th-party impact: the registered third parties that declared this
        vendor as a sub-processor / dependency, and are therefore *indirectly* exposed if
        it fails. Matches the vendor to its 4th-party identity (explicit link or name)."""
        _RBAC.assert_object_visible(s, u, "vendor", vid)
        from app.features.domain.registry_models import (FourthPartyRecord, FourthPartyVendor,
                                               EngagementRecord)
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vid)).first()
        if not v:
            raise HTTPException(404, "vendor not found")
        # resolve the vendor's 4th-party identity/identities
        fp_ids = set()
        if getattr(v, "fourth_party_id", None):
            fp_ids.add(v.fourth_party_id)
        nm = (v.legal_name or "").strip().lower()
        for f in s.scalars(select(FourthPartyRecord)).all():
            if (f.legal_name or "").strip().lower() == nm:
                fp_ids.add(f.fourth_party_id)
        dep_ids = []
        seen = set()
        if fp_ids:
            for ln in s.scalars(select(FourthPartyVendor).where(
                    FourthPartyVendor.fourth_party_id.in_(fp_ids))).all():
                if ln.vendor_id and ln.vendor_id != vid and ln.vendor_id not in seen:
                    seen.add(ln.vendor_id); dep_ids.append(ln.vendor_id)
        dep_vendors = {x.vendor_id: x for x in s.scalars(select(VendorRecord).where(
            VendorRecord.vendor_id.in_(dep_ids))).all()} if dep_ids else {}
        # engagements per dependent
        engs_by_v: dict[str, list] = {}
        if dep_ids:
            for e in s.scalars(select(EngagementRecord).where(
                    EngagementRecord.vendor_id.in_(dep_ids))).all():
                engs_by_v.setdefault(e.vendor_id, []).append(
                    {"engagement_id": e.engagement_id, "title": e.title, "status": e.status})
        dependents = []
        eng_total = 0
        for did in dep_ids:
            dv = dep_vendors.get(did)
            if not dv:
                continue
            elist = engs_by_v.get(did, [])
            eng_total += len(elist)
            dependents.append({"vendor_id": dv.vendor_id, "legal_name": dv.legal_name,
                               "tier": dv.tier, "is_critical": dv.is_critical,
                               "engagements": elist})
        dependents.sort(key=lambda d: (not d["is_critical"], -len(d["engagements"])))
        return {"vendor": {"vendor_id": v.vendor_id, "legal_name": v.legal_name,
                           "is_critical": v.is_critical},
                "is_fourth_party": bool(fp_ids), "fourth_party_ids": sorted(fp_ids),
                "dependent_count": len(dependents), "engagement_count": eng_total,
                "dependents": dependents}

    @app.post("/api/v2/scenario/simulate")
    def v2_scenario_simulate(b: ScenarioIn, s: Session = Depends(db),
                             u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import scenario as SCEN
        from app.agents import llm_config
        res = SCEN.simulate(s, b.node_type, b.node_id, b.hours)
        res["brief_ai"] = False
        if llm_config.status().get("live_ready"):
            try:
                out = llm_config.complete(
                    PROMPTS.resolve(s, "scenario_impact"),
                    res["brief"], domain="risk", max_tokens=350)
                if out and out.strip():
                    res["brief"] = out.strip(); res["brief_ai"] = True
            except Exception as _e:
                _obs_swallow('bro_app.py', _e)
        return res

    @app.post("/api/v2/financial-dd")
    def v2_financial_dd(b: FinancialIn, s: Session = Depends(db),
                        u: User = Depends(require("intel.financial"))):
        from app.features.domain import master_service as MS
        from app.features.intelligence import entity_resolve as ER
        result = FIN.assess_financials(b.figures, b.flags or {})
        ent = ER.resolve_entity(s, vendor_id=b.vendor_id, other_name=b.other_name)
        persisted = False
        if ent.get("registered"):
            persisted = MS.persist_fdd(s, ent["vendor_id"], result)
            MS.refresh_risk_profile(s, ent["vendor_id"])
        result["entity"] = ent
        result["persisted"] = persisted
        audit(s, "v2.financial_dd", u.username,
              {"banding": result["banding"], "altman_zone": result["altman"]["zone"],
               "entity": ent["vendor_name"], "persisted": persisted})
        s.commit()
        return result

    # ---- reputation & ESG (7-pillar engine) ----
    @app.post("/api/v2/reputation")
    def v2_reputation(b: ReputationIn, s: Session = Depends(db),
                      u: User = Depends(require("intel.reputation"))):
        from app.features.intelligence import reputation as REP
        from app.features.intelligence import entity_resolve as ER
        from app.features.domain import master_service as MS
        ent = ER.resolve_entity(s, vendor_id=b.vendor_id, other_name=b.other_name)
        result = REP.assess_reputation(b.events or [], b.customer_facing)
        result["entity"] = ent
        persisted = False
        if ent.get("registered"):
            persisted = MS.persist_reputation(s, ent["vendor_id"], result)
            MS.refresh_risk_profile(s, ent["vendor_id"])
        result["persisted"] = persisted
        audit(s, "v2.reputation", u.username,
              {"overall": result["overall"], "verdict": result["verdict"],
               "entity": ent["vendor_name"], "events": result["event_count"],
               "persisted": persisted})
        s.commit()
        return result

    # ---- system configuration manager (admin) ----
    @app.get("/api/v2/management/risk-view")
    def v2_risk_view(s: Session = Depends(db), u: User = Depends(require("dashboard.risk"))):
        from app.features.intelligence import management as MGMT
        return MGMT.risk_view(s)

    @app.get("/api/v2/management/ops-view")
    def v2_ops_view(s: Session = Depends(db), u: User = Depends(require("dashboard.ops"))):
        from app.features.intelligence import management as MGMT
        return MGMT.ops_view(s)

    @app.get("/api/v2/management/concentration")
    def v2_concentration(s: Session = Depends(db), u: User = Depends(require("dashboard.risk"))):
        from app.features.intelligence import management as MGMT
        return MGMT.concentration_graph(s)

    @app.get("/api/v2/management/concentration/detail")
    def v2_concentration_detail(node_type: str, key: str, s: Session = Depends(db),
                                u: User = Depends(require("dashboard.risk"))):
        from app.features.intelligence import management as MGMT
        if node_type not in ("location", "fourth_party", "vendor"):
            raise HTTPException(400, "node_type must be location, fourth_party or vendor")
        return MGMT.concentration_node_detail(s, node_type, key)

    @app.post("/api/v2/intelligence/board")
    def v2_board_intelligence(s: Session = Depends(db),
                              u: User = Depends(require("dashboard.exec"))):
        from app.features.intelligence import intelligence as INTEL
        result = INTEL.board_intelligence(s)
        from app.agents import llm_config
        if llm_config.is_enabled():
            try:
                import json as _json
                ctx = _json.dumps({"internal": result["internal"],
                                   "external": result["external"],
                                   "observations": result["observations"][:6],
                                   "predictions": result["predictions"]})
                enriched = llm_config.complete(
                    PROMPTS.resolve(s, "board_intelligence"),
                    f"Analysis: {ctx}", domain="management")
                if enriched:
                    result["executive_briefing"] = enriched
                    result["engine"] = "llm"
            except Exception as _e:
                _obs_swallow('bro_app.py', _e)
        audit(s, "v2.board_intelligence", u.username,
              {"engine": result["engine"], "observations": len(result["observations"])})
        s.commit()
        return result

    @app.post("/api/v2/intelligence/board/followup")
    def v2_board_followup(b: BoardFollowupIn, s: Session = Depends(db),
                          u: User = Depends(require("dashboard.exec"))):
        """Executive deep-dive follow-up — answered by AI over the board-intelligence
        base + live portfolio, at Board/ExCo (BCG-grade) level."""
        from app.agents import llm_config
        if not llm_config.status().get("live_ready"):
            return {"answer": AI_HOLDING, "engine": "holding"}
        from app.features.intelligence import intelligence as INTEL
        from app.features.intelligence import management as MGMT
        base = INTEL.board_intelligence(s)
        ctx = MGMT.portfolio_context(s)
        hist = ""
        for t in (b.history or [])[-4:]:
            if isinstance(t, dict) and t.get("q"):
                hist += f"\nPrevious Q: {t.get('q')}\nPrevious A: {(t.get('a') or '')[:400]}\n"
        system = PROMPTS.resolve(s, "board_followup")
        user_msg = (hist + f"\nFollow-up question: {b.question}\n\nBOARD DEEP-DIVE (JSON):\n"
                    f"{json.dumps(base)[:9000]}\n\nPORTFOLIO CONTEXT (JSON):\n{json.dumps(ctx)[:6000]}")
        ocx = None
        try:
            from app.features.intelligence import oss as OSS
            _os = OSS.summary(s)
            if _os and _os.get("sboms"):
                ocx = ("OSS / SBOM exposure (external): "
                       f"{_os['coverage_pct']}% coverage, {_os['kev_components']} components with "
                       f"known-exploited (KEV) vulnerabilities, {_os['prohibited_licences']} prohibited licences.")
        except Exception:
            ocx = None
        ans = llm_config.complete(system, user_msg, domain="management", max_tokens=1500,
                                  review=bool(getattr(b, "deep", False)),
                                  timeout_s=(150 if getattr(b, "deep", False) else 60),
                                  external_context=ocx,
                                  feedback_context=_fb_guidance(s, "board"))
        if not ans:
            return {"answer": ("The AI engine is connected but the call did not complete: "
                               + (llm_config.last_error() or "unknown error") + "."),
                    "engine": "ai_failed"}
        audit(s, "v2.board_followup", u.username, {"q": b.question[:80]})
        s.commit()
        return {"answer": ans, "engine": "llm"}

    @app.post("/api/v2/management/chat")
    def v2_management_chat(b: MgmtChatIn, s: Session = Depends(db),
                           u: User = Depends(require("dashboard.exec"))):
        from app.features.intelligence import management as MGMT
        from app.agents import llm_config
        ctx = MGMT.portfolio_context(s)
        result = MGMT.management_answer(s, b.question)  # deterministic baseline/fallback
        result["context"] = ctx
        if llm_config.status().get("live_ready"):
            try:
                hist = ""
                for turn in (b.history or [])[-4:]:
                    if isinstance(turn, dict) and turn.get("q"):
                        hist += f"\nPrevious Q: {turn.get('q')}\nPrevious A: {(turn.get('a') or '')[:400]}\n"
                system = PROMPTS.resolve(s, "management_chat")
                user_msg = (hist + f"\nCurrent question: {b.question}\n\n"
                            f"PORTFOLIO CONTEXT (JSON):\n{json.dumps(ctx)}")
                pcx = None
                try:
                    from app.features.intelligence import pestle as PES
                    _ps = PES.get_summary(s)
                    if _ps:
                        pcx = "Top live portfolio threats: " + "; ".join(
                            f"{t['name']} ({t['score']})" for t in _ps.get("top_threats", [])[:8])
                except Exception:
                    pcx = None
                ocx = None
                try:
                    from app.features.intelligence import oss as OSS
                    _os = OSS.summary(s)
                    if _os and _os.get("sboms"):
                        topc = ", ".join(f"{c['name']} ({c['usage']} eng)"
                                         for c in _os.get("top_concentration", [])[:5])
                        ocx = ("OSS / SBOM exposure (external): "
                               f"{_os['coverage_pct']}% SBOM coverage, {_os['components']} components, "
                               f"{_os['kev_components']} with known-exploited (KEV) vulnerabilities, "
                               f"{_os['prohibited_licences']} prohibited licences; "
                               f"most-concentrated components: {topc}.")
                except Exception:
                    ocx = None
                enriched = llm_config.complete(system, user_msg, domain="management",
                                               max_tokens=1200,
                                               review=bool(getattr(b, "deep", False)),
                                               timeout_s=(150 if getattr(b, "deep", False) else 60),
                                               pestle_context=pcx, external_context=ocx,
                                               feedback_context=_fb_guidance(s, "management"))
                if enriched:
                    result["answer"] = enriched
                    result["engine"] = "llm"
                else:
                    result["ai_error"] = llm_config.last_error()
            except Exception as e:
                result["ai_error"] = str(e)[:200]
        audit(s, "v2.management_chat", u.username, {"engine": result["engine"]})
        s.commit()
        return result

    @app.get("/api/v2/management/suggested")
    def v2_management_suggested(u: User = Depends(require("dashboard.exec"))):
        from app.features.intelligence import management as MGMT
        return {"questions": MGMT.SUGGESTED_QUESTIONS}

    # ---- capture a chat session into a structured assessment ----
    @app.post("/api/v2/financial-dd/peers")
    def v2_peers(b: PeerBenchmarkIn, s: Session = Depends(db),
                 u: User = Depends(require("intel.financial"))):
        result = FIN.assess_financials(b.figures, b.flags or {})
        peers = FIN.peer_benchmark(result["ratios"], b.sector)
        return {"sector": b.sector, "peers": peers}

    @app.post("/api/v2/financial-dd/research")
    def v2_fin_research(b: FinResearchIn, s: Session = Depends(db),
                        u: User = Depends(require("intel.financial"))):
        from app.features.intelligence import entity_resolve as ER
        res = ER.research_financials(b.company, b.jurisdiction or "UK",
                                     b.identifier or "", b.year or "")
        audit(s, "v2.fin_research", u.username,
              {"company": b.company, "matched": res.get("matched")})
        s.commit()
        return res

    @app.post("/api/v2/research/reputation")
    def v2_research_reputation(b: AIResearchIn, s: Session = Depends(db),
                               u: User = Depends(require("intel.reputation"))):
        if not _ai_live():
            return {"available": False, "holding": True, "message": AI_HOLDING}
        job_id = _start_research_job(vendor_id=b.vendor_id, company=b.company,
                                     jurisdiction=b.jurisdiction, identifier=b.identifier,
                                     mode="reputation", deep=bool(getattr(b, "deep", False)),
                                     actor=u.username)
        audit(s, "v2.research_reputation.start", u.username,
              {"vendor_id": b.vendor_id, "company": b.company, "job_id": job_id}); s.commit()
        return {"pending": True, "job_id": job_id,
                "message": ("Research started — running on the server. It will appear here when "
                            "complete and is filed in AI Reports even if you navigate away.")}

    # ===== BRO Chat Stage 0: PR pull (MOCK) + similar-engagement check =====
    @app.post("/api/v2/vendor-attributes/{vid}/screening")
    def v2_attr_screening(vid: str, b: ScreeningIn, s: Session = Depends(db),
                          u: User = Depends(require("vendor.edit"))):
        from app.features.domain import master_service as MS
        if b.screen_type not in MS.SCREEN_TYPES:
            raise HTTPException(400, f"screen_type must be one of {MS.SCREEN_TYPES}")
        MS.set_screening(s, vid, b.screen_type, result=b.result, detail=b.detail,
                         screened_date=b.screened_date, next_due=b.next_due)
        audit(s, "v2.screening_update", u.username, {"vendor_id": vid, "type": b.screen_type})
        s.commit()
        return MS.list_screening(s, vid)

    @app.get("/api/v2/pestle/catalogue")
    def v2_pestle_catalogue(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import pestle as PES
        return {"categories": PES.CATEGORIES, "threats": PES.THREATS, "count": len(PES.THREATS)}

    @app.get("/api/v2/pestle/summary")
    def v2_pestle_summary(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import pestle as PES
        summ = PES.get_summary(s)
        if not summ:
            return {"empty": True}
        return {"as_of": summ["as_of"], "entities": summ["entities"], "cat_means": summ["cat_means"],
                "top_threats": summ["top_threats"], "movers": summ["movers"],
                "categories": PES.CATEGORIES}

    @app.get("/api/v2/pestle/graph")
    def v2_pestle_graph(focus_type: str = "portfolio", focus_id: Optional[str] = None,
                        min_score: int = 55, limit: int = 8,
                        s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import pestle as PES
        return PES.graph(s, focus_type=focus_type, focus_id=focus_id,
                         min_score=min_score, limit=limit)

    @app.get("/api/v2/pestle/profile/{entity_type}/{entity_id}")
    def v2_pestle_profile(entity_type: str, entity_id: str,
                          s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import pestle as PES
        prof = PES.get_profile(s, entity_type, entity_id)
        if not prof:
            raise HTTPException(404, "no PESTLE profile for that entity")
        prof["categories"] = PES.CATEGORIES
        return prof

    @app.post("/api/v2/pestle/refresh")
    def v2_pestle_refresh(as_of: Optional[str] = None, s: Session = Depends(db),
                          u: User = Depends(require("admin.config"))):
        """Simulated overnight News + Reputation sweep that refreshes the PESTLE vectors."""
        from app.features.intelligence import pestle as PES
        res = PES.refresh_all(s, as_of=as_of)
        audit(s, "v2.pestle_refresh", u.username, {"entities": res["entities"], "as_of": res["as_of"]})
        s.commit()
        return res

    @app.post("/api/v2/pestle/rebuild")
    def v2_pestle_rebuild(s: Session = Depends(db), u: User = Depends(require("admin.config"))):
        from app.features.intelligence import pestle as PES
        n = PES.build_all(s)
        audit(s, "v2.pestle_rebuild", u.username, {"entities": n})
        s.commit()
        return {"entities": n}

    # ---------------- Open-Source Software register ----------------
    @app.get("/api/v2/oss/summary")
    def v2_oss_summary(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        return OSS.summary(s)

    @app.get("/api/v2/oss/components")
    def v2_oss_components(q: Optional[str] = None, licence: Optional[str] = None,
                          band: Optional[str] = None, s: Session = Depends(db),
                          u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        return {"components": OSS.components(s, q=q, licence=licence, band_filter=band)}

    @app.get("/api/v2/oss/component/{cid}")
    def v2_oss_component(cid: int, s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        d = OSS.component_detail(s, cid)
        if not d:
            raise HTTPException(404, "component not found")
        return d

    @app.get("/api/v2/oss/blast")
    def v2_oss_blast(q: str, version: Optional[str] = None, s: Session = Depends(db),
                     u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        return OSS.blast_radius(s, q, version=version)

    @app.get("/api/v2/oss/engagement/{eid}")
    def v2_oss_engagement(eid: str, s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        return OSS.engagement_oss(s, eid)

    @app.get("/api/v2/oss/concentration")
    def v2_oss_concentration(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        return {"components": OSS.concentration(s)}

    @app.get("/api/v2/oss/licences")
    def v2_oss_licences(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        return OSS.licences(s)

    @app.get("/api/v2/oss/vulnerabilities")
    def v2_oss_vulnerabilities(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        return {"vulnerabilities": OSS.vulnerabilities(s)}

    @app.get("/api/v2/oss/coverage")
    def v2_oss_coverage(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.intelligence import oss as OSS
        return {"rows": OSS.coverage(s)}

    @app.post("/api/v2/oss/ingest")
    def v2_oss_ingest(body: dict = Body(...), s: Session = Depends(db),
                      u: User = Depends(require("engagement.edit"))):
        """Ingest a vendor SBOM (CycloneDX or SPDX JSON) and tag it to an engagement."""
        from app.features.intelligence import oss as OSS
        eid = body.get("engagement_id"); sbom = body.get("sbom")
        if not eid or sbom is None:
            raise HTTPException(400, "engagement_id and sbom are required")
        if isinstance(sbom, str):
            try:
                sbom = json.loads(sbom)
            except Exception:
                raise HTTPException(400, "sbom is not valid JSON")
        try:
            res = OSS.ingest_sbom(s, eid, body.get("product") or "Unspecified product",
                                  body.get("product_version") or "0.0.0", sbom, channel="upload")
        except ValueError as e:
            raise HTTPException(400, str(e))
        audit(s, "v2.oss_ingest", u.username, {"engagement": eid, "components": res["components"]})
        s.commit()
        return res

    @app.post("/api/v2/oss/rebuild")
    def v2_oss_rebuild(s: Session = Depends(db), u: User = Depends(require("admin.config"))):
        from app.features.intelligence import oss as OSS
        res = OSS.seed_all(s)
        audit(s, "v2.oss_rebuild", u.username, res)
        s.commit()
        return res

    # ---------------- AI answer feedback ----------------

    return r
