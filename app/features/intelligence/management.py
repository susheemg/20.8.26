"""
Management analytics — BCG-consultant-grade aggregation over the platform data.

Two views:
  risk_view  — portfolio risk posture for leadership (exposure, concentration,
               findings, certificate/issue exposure, critical vendors)
  ops_view   — how the TPRM function is running (assessment pipeline, engagement
               status, assessor workload, open vs closed actions)

management_answer(question) — deterministic natural-language Q&A over the same
data (prompt-chip style). When a live LLM key is set the caller can route
free-form questions through it; this provides the offline-always path.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.domain.registry_models import (
    ArtefactRecord, AssessmentRecord, EngagementRecord, FindingRecord,
    FourthPartyRecord, IssueRecord, VendorRecord,
)


def _count(s: Session, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for w in where:
        stmt = stmt.where(w)
    return int(s.scalar(stmt) or 0)


def concentration_node_detail(s: Session, node_type: str, key: str) -> dict:
    """Drill-down behind a concentration node — the specifics a user can research.
    node_type: 'location' (key=country) | 'fourth_party' (key=F4P id) | 'vendor' (key=VEN id).
    Returns connected vendors / engagements with names, criticality and bands."""
    from app.features.domain.master_ext import EngagementExt
    from app.features.domain.registry_models import FourthPartyVendor

    out = {"node_type": node_type, "key": key, "title": key, "vendors": [],
           "engagements": [], "summary": {}}

    def _vrow(v):
        return {"vendor_id": v.vendor_id, "name": v.legal_name,
                "tier": v.tier, "critical": bool(v.is_critical)}

    if node_type == "location":
        seen_v = {}
        for ext in s.scalars(select(EngagementExt).where(
                EngagementExt.delivery_location == key)).all():
            eng = s.scalars(select(EngagementRecord).where(
                EngagementRecord.engagement_id == ext.engagement_id)).first()
            if not eng:
                continue
            v = s.scalars(select(VendorRecord).where(
                VendorRecord.vendor_id == eng.vendor_id)).first()
            out["engagements"].append({
                "engagement_id": eng.engagement_id, "title": eng.title,
                "vendor_id": eng.vendor_id, "vendor_name": v.legal_name if v else eng.vendor_id,
                "inherent_band": eng.inherent_band, "residual_band": eng.residual_band,
                "annual_value": eng.annual_value, "service_type": getattr(ext, "service_type", None),
                "receiving_location": getattr(ext, "receiving_location", None)})
            if v and v.vendor_id not in seen_v:
                seen_v[v.vendor_id] = _vrow(v)
        out["vendors"] = list(seen_v.values())
        out["summary"] = {"vendors": len(out["vendors"]), "engagements": len(out["engagements"]),
                          "critical_vendors": sum(1 for v in out["vendors"] if v["critical"]),
                          "total_value": sum(e["annual_value"] or 0 for e in out["engagements"])}

    elif node_type == "fourth_party":
        fp = s.scalars(select(FourthPartyRecord).where(
            FourthPartyRecord.fourth_party_id == key)).first()
        out["title"] = fp.legal_name if fp else key
        out["fourth_party"] = {"id": key, "name": fp.legal_name if fp else key,
                               "service": getattr(fp, "service_provided", None) if fp else None,
                               "hq_country": getattr(fp, "hq_country", None) if fp else None,
                               "concentration_flag": bool(fp.concentration_flag) if fp else False}
        for link in s.scalars(select(FourthPartyVendor).where(
                FourthPartyVendor.fourth_party_id == key)).all():
            v = s.scalars(select(VendorRecord).where(
                VendorRecord.vendor_id == link.vendor_id)).first()
            if v:
                out["vendors"].append(_vrow(v))
        out["summary"] = {"dependent_vendors": len(out["vendors"]),
                          "critical_dependents": sum(1 for v in out["vendors"] if v["critical"])}

    elif node_type == "vendor":
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == key)).first()
        out["title"] = v.legal_name if v else key
        if v:
            out["vendor"] = _vrow(v)
            for eng in s.scalars(select(EngagementRecord).where(
                    EngagementRecord.vendor_id == key)).all():
                ext = s.scalars(select(EngagementExt).where(
                    EngagementExt.engagement_id == eng.engagement_id)).first()
                out["engagements"].append({
                    "engagement_id": eng.engagement_id, "title": eng.title,
                    "inherent_band": eng.inherent_band, "residual_band": eng.residual_band,
                    "annual_value": eng.annual_value,
                    "delivery_location": getattr(ext, "delivery_location", None) if ext else None})
            fps = []
            for link in s.scalars(select(FourthPartyVendor).where(
                    FourthPartyVendor.vendor_id == key)).all():
                fp = s.scalars(select(FourthPartyRecord).where(
                    FourthPartyRecord.fourth_party_id == link.fourth_party_id)).first()
                if fp:
                    fps.append({"id": fp.fourth_party_id, "name": fp.legal_name})
            out["fourth_parties"] = fps
            out["summary"] = {"engagements": len(out["engagements"]),
                              "fourth_parties": len(fps),
                              "total_value": sum(e["annual_value"] or 0 for e in out["engagements"])}
    return out


def concentration_graph(s: Session) -> dict:
    """Supply-chain concentration network + delivery-location aggregates.

    Nodes: vendors, the fourth parties they rely on, and delivery locations
    (countries). Edges: vendor->fourth_party (shared dependency) and
    vendor->delivery_location. Concentration surfaces as high-degree hub nodes —
    a shared fourth party or a country that many vendors funnel through. Node
    `risk` (0..1) drives colour; node `degree` drives size.
    """
    from app.features.domain.master_ext import EngagementExt
    from app.features.domain.registry_models import FourthPartyVendor

    vendors = list(s.scalars(select(VendorRecord)).all())
    vmap = {v.vendor_id: v for v in vendors}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(nid, label, kind, **kw):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "kind": kind, "degree": 0, **kw}
        return nodes[nid]

    # vendor nodes
    for v in vendors:
        add_node(v.vendor_id, v.legal_name or v.vendor_id, "vendor",
                 critical=bool(v.is_critical), tier=v.tier)

    # vendor -> fourth party edges (shared 4th parties = concentration hubs)
    f4_names = {f.fourth_party_id: f for f in s.scalars(select(FourthPartyRecord)).all()}
    for link in s.scalars(select(FourthPartyVendor)).all():
        if link.vendor_id not in vmap:
            continue
        f4 = f4_names.get(link.fourth_party_id)
        fname = (f4.legal_name if f4 else link.fourth_party_id)
        add_node(link.fourth_party_id, fname, "fourth_party",
                 concentration=bool(f4 and f4.concentration_flag))
        edges.append({"source": link.vendor_id, "target": link.fourth_party_id})

    # vendor -> delivery location edges (geographic concentration)
    loc_counter: Counter = Counter()
    for ext in s.scalars(select(EngagementExt)).all():
        eng = s.scalars(select(EngagementRecord).where(
            EngagementRecord.engagement_id == ext.engagement_id)).first()
        vid = eng.vendor_id if eng else None
        if not vid or vid not in vmap:
            continue
        loc = getattr(ext, "delivery_location", None)
        if loc:
            lid = "LOC:" + loc
            add_node(lid, loc, "location")
            edges.append({"source": vid, "target": lid})
            loc_counter[loc] += 1

    # degree + concentration risk
    for e in edges:
        if e["source"] in nodes:
            nodes[e["source"]]["degree"] += 1
        if e["target"] in nodes:
            nodes[e["target"]]["degree"] += 1
    maxdeg = max([n["degree"] for n in nodes.values()] + [1])
    for n in nodes.values():
        base = n["degree"] / maxdeg
        if n["kind"] == "vendor" and n.get("critical"):
            base = min(1.0, base + 0.35)
        if n["kind"] == "fourth_party" and n.get("concentration"):
            base = min(1.0, base + 0.4)
        if n["kind"] == "location" and n["degree"] >= 3:
            base = min(1.0, base + 0.3)
        n["risk"] = round(base, 3)

    # top concentration callouts
    hubs = sorted([n for n in nodes.values() if n["kind"] in ("fourth_party", "location")],
                  key=lambda x: x["degree"], reverse=True)[:6]

    # delivery-location aggregates for the world map
    locations = [{"country": c, "count": n} for c, n in loc_counter.most_common()]

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "hubs": [{"label": h["label"], "kind": h["kind"], "degree": h["degree"],
                  "risk": h["risk"]} for h in hubs],
        "locations": locations,
        "summary": {"vendors": sum(1 for n in nodes.values() if n["kind"] == "vendor"),
                    "fourth_parties": sum(1 for n in nodes.values() if n["kind"] == "fourth_party"),
                    "locations": len(locations),
                    "edges": len(edges)},
    }


def _watchlist_count(s) -> int:
    try:
        from app.features.domain import watchlist_service as _WL
        return _WL.summary(s).get("active", 0)
    except Exception:
        return 0


def risk_view(s: Session) -> dict:
    vendors = s.scalars(select(VendorRecord)).all()
    engs = s.scalars(select(EngagementRecord)).all()
    findings = s.scalars(select(FindingRecord)).all()
    fourth = s.scalars(select(FourthPartyRecord)).all()
    artefacts = s.scalars(select(ArtefactRecord).where(ArtefactRecord.is_current == True)).all()  # noqa: E712

    inherent = Counter(e.inherent_band for e in engs if e.inherent_band)
    residual = Counter(e.residual_band for e in engs if e.residual_band)
    sev = Counter(f.severity for f in findings if f.status != "Closed")
    cert_status = Counter(a.status for a in artefacts)

    high_residual = [
        {"engagement_id": e.engagement_id, "vendor_id": e.vendor_id,
         "title": e.title, "residual_band": e.residual_band}
        for e in engs if e.residual_band in ("HIGH", "ELEVATED")
    ]
    critical_vendors = [
        {"vendor_id": v.vendor_id, "legal_name": v.legal_name}
        for v in vendors if v.is_critical
    ]
    concentration = [
        {"fourth_party_id": f.fourth_party_id, "legal_name": f.legal_name}
        for f in fourth if f.concentration_flag
    ]
    return {
        "totals": {
            "vendors": len(vendors), "engagements": len(engs),
            "critical_vendors": len(critical_vendors),
            "open_findings": _count(s, FindingRecord, FindingRecord.status != "Closed"),
            "watchlisted_vendors": _watchlist_count(s),
        },
        "inherent_distribution": dict(inherent),
        "residual_distribution": dict(residual),
        "findings_by_severity": dict(sev),
        "certificate_status": dict(cert_status),
        "high_residual_engagements": high_residual,
        "critical_vendors": critical_vendors,
        "fourth_party_concentration": concentration,
        "open_issues": _count(s, IssueRecord, IssueRecord.status == "Open"),
    }


def ops_view(s: Session) -> dict:
    assessments = s.scalars(select(AssessmentRecord)).all()
    engs = s.scalars(select(EngagementRecord)).all()
    findings = s.scalars(select(FindingRecord)).all()

    asm_status = Counter(a.status for a in assessments)
    eng_status = Counter(e.status for e in engs)
    # assessor workload (open assessments per assessor)
    workload = Counter(a.assessor_user for a in assessments
                       if a.assessor_user and a.status != "Approved")
    awaiting_signoff = [
        {"assessment_id": a.assessment_id, "assessor_user": a.assessor_user,
         "inherent_band": a.inherent_band}
        for a in assessments
        if a.inherent_band == "HIGH" and not a.assessor_signed_off and a.status != "Approved"
    ]
    open_actions = _count(s, FindingRecord, FindingRecord.status != "Closed")
    closed_actions = _count(s, FindingRecord, FindingRecord.status == "Closed")
    return {
        "assessment_pipeline": dict(asm_status),
        "engagement_status": dict(eng_status),
        "assessor_workload": dict(workload),
        "awaiting_signoff": awaiting_signoff,
        "actions": {"open": open_actions, "closed": closed_actions,
                    "total": open_actions + closed_actions},
        "locked_assessments": _count(s, AssessmentRecord, AssessmentRecord.locked == True),  # noqa: E712
    }


def portfolio_context(s: Session) -> dict:
    """Compact, decision-grade snapshot of the live portfolio for the management
    chat AI: vendors, ACTIVE engagements, risks (residual) and findings."""
    from app.features.domain.registry_models import VendorRecord, EngagementRecord, FindingRecord
    rv = risk_view(s)
    vendors = list(s.scalars(select(VendorRecord)).all())
    by_tier = {}
    for v in vendors:
        by_tier[v.tier or "Unclassified"] = by_tier.get(v.tier or "Unclassified", 0) + 1
    engs = list(s.scalars(select(EngagementRecord)).all())

    def _active(e):
        st = (e.status or "").lower(); stg = (e.stage or "").lower()
        return stg not in ("terminate", "terminated", "exited") and \
            st not in ("terminated", "expired", "inactive", "closed")
    active = [e for e in engs if _active(e)]
    active_he = [{"engagement_id": e.engagement_id, "title": e.title,
                  "residual_band": e.residual_band, "value": e.annual_value}
                 for e in active if (e.residual_band or "") in ("HIGH", "ELEVATED")]
    return {
        "vendors": {"total": len(vendors), "critical": rv["totals"]["critical_vendors"],
                    "by_tier": by_tier},
        "active_engagements": {"count": len(active), "total_engagements": len(engs),
                               "high_elevated_residual": active_he[:15]},
        "risks": {"residual_distribution": rv["residual_distribution"],
                  "inherent_distribution": rv["inherent_distribution"],
                  "high_residual_engagements": rv["high_residual_engagements"][:15],
                  "critical_vendors": [v["legal_name"] for v in rv["critical_vendors"]][:20]},
        "findings": {"open": rv["totals"]["open_findings"],
                     "by_severity": rv["findings_by_severity"]},
        "fourth_party_concentration": rv["fourth_party_concentration"],
        "certificate_status": rv["certificate_status"],
    }


def management_answer(s: Session, question: str) -> dict:
    """Deterministic NL Q&A over the data. Matches the question to a known
    metric and returns a consultant-style answer + the supporting figures."""
    q = (question or "").lower()
    rv = risk_view(s)
    ov = ops_view(s)

    def ans(text, data):
        return {"answer": text, "data": data, "engine": "deterministic"}

    if any(k in q for k in ("critical", "tier 0")):
        cv = rv["critical_vendors"]
        return ans(
            f"{len(cv)} vendor(s) are designated critical (Tier 0): "
            + (", ".join(v["legal_name"] for v in cv) if cv else "none currently."),
            {"critical_vendors": cv})
    if any(k in q for k in ("expired", "certificate", "cert", "expir")):
        cs = rv["certificate_status"]
        return ans(
            f"Certificate exposure: {cs.get('Expired', 0)} expired, "
            f"{cs.get('Expiring', 0)} expiring within 7 days, {cs.get('Valid', 0)} valid. "
            f"{rv['open_issues']} open issue(s) in the log.",
            {"certificate_status": cs, "open_issues": rv["open_issues"]})
    if any(k in q for k in ("high", "residual", "exposure", "risk")):
        hr = rv["high_residual_engagements"]
        return ans(
            f"{len(hr)} engagement(s) sit at HIGH/ELEVATED residual risk. "
            f"Residual distribution: {rv['residual_distribution'] or 'none scored yet'}.",
            {"high_residual": hr, "residual_distribution": rv["residual_distribution"]})
    if any(k in q for k in ("finding", "action", "remediation", "open")):
        return ans(
            f"{ov['actions']['open']} open action(s) vs {ov['actions']['closed']} closed. "
            f"Open findings by severity: {rv['findings_by_severity'] or 'none'}.",
            {"actions": ov["actions"], "by_severity": rv["findings_by_severity"]})
    if any(k in q for k in ("assessor", "workload", "sign")):
        return ans(
            f"Assessor workload (open assessments): {ov['assessor_workload'] or 'none assigned'}. "
            f"{len(ov['awaiting_signoff'])} HIGH assessment(s) awaiting sign-off.",
            {"workload": ov["assessor_workload"], "awaiting_signoff": ov["awaiting_signoff"]})
    if any(k in q for k in ("concentration", "fourth", "sub-processor", "subprocessor")):
        cc = rv["fourth_party_concentration"]
        return ans(
            f"{len(cc)} fourth part(y/ies) flagged for concentration (behind ≥3 vendors)"
            + (": " + ", ".join(c["legal_name"] for c in cc) if cc else "."),
            {"concentration": cc})
    if any(k in q for k in ("pipeline", "assessment", "progress", "status")):
        return ans(
            f"Assessment pipeline: {ov['assessment_pipeline'] or 'no assessments yet'}. "
            f"Engagement status: {ov['engagement_status'] or 'none'}.",
            {"pipeline": ov["assessment_pipeline"], "engagements": ov["engagement_status"]})
    # default portfolio summary
    return ans(
        f"Portfolio: {rv['totals']['vendors']} vendors, {rv['totals']['engagements']} engagements, "
        f"{rv['totals']['critical_vendors']} critical, {rv['totals']['open_findings']} open findings, "
        f"{rv['open_issues']} open issues. Ask about critical vendors, residual exposure, "
        f"certificates, findings, assessor workload, concentration, or the assessment pipeline.",
        {"totals": rv["totals"]})


SUGGESTED_QUESTIONS = [
    "Which vendors are critical?",
    "What's our high residual exposure?",
    "Show certificate and issue exposure",
    "Open findings by severity?",
    "What's the assessor workload?",
    "Any fourth-party concentration?",
    "How's the assessment pipeline?",
]
