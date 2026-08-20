"""Scenario simulator / digital twin. Simulate the loss of a shared sub-provider,
a vendor, or a geography for a duration, and cascade the impact across the estate:
affected vendors → engagements → business units → spend-at-risk → SLA exposure.
Grounded in the real dependency graph; deterministic."""
from __future__ import annotations
from sqlalchemy import select


def options(s) -> dict:
    from app.features.domain.registry_models import (VendorRecord, FourthPartyVendor, FourthPartyRecord)
    links = s.scalars(select(FourthPartyVendor)).all()
    cnt = {}
    for ln in links:
        cnt.setdefault(ln.fourth_party_id, []).append(ln.vendor_id)
    fps = {f.fourth_party_id: f for f in s.scalars(select(FourthPartyRecord)).all()}
    fourth = sorted(({"id": fid, "name": (fps[fid].legal_name if fid in fps else fid),
                      "vendor_count": len(v)} for fid, v in cnt.items()),
                    key=lambda x: -x["vendor_count"])[:15]
    vendors = s.scalars(select(VendorRecord)).all()
    crit = [{"id": v.vendor_id, "name": v.legal_name} for v in vendors if v.is_critical][:20]
    ctry = {}
    for v in vendors:
        if v.hq_country:
            ctry[v.hq_country] = ctry.get(v.hq_country, 0) + 1
    countries = sorted(({"id": k, "name": k, "vendor_count": n} for k, n in ctry.items()),
                       key=lambda x: -x["vendor_count"])
    return {"fourth_parties": fourth, "vendors": crit, "countries": countries}


_HI = {"HIGH", "CRITICAL"}


def simulate(s, node_type: str, node_id: str, hours: int) -> dict:
    from app.features.domain.registry_models import (VendorRecord, EngagementRecord, FourthPartyVendor,
                                  FourthPartyRecord)
    hours = int(hours or 24)
    vendors = {v.vendor_id: v for v in s.scalars(select(VendorRecord)).all()}
    label = node_id
    if node_type == "fourth_party":
        affected_ids = [ln.vendor_id for ln in s.scalars(select(FourthPartyVendor).where(
            FourthPartyVendor.fourth_party_id == node_id)).all()]
        fp = s.scalars(select(FourthPartyRecord).where(FourthPartyRecord.fourth_party_id == node_id)).first()
        label = (fp.legal_name if fp else node_id)
    elif node_type == "country":
        affected_ids = [vid for vid, v in vendors.items() if (v.hq_country or "") == node_id]
        label = node_id
    else:  # vendor
        affected_ids = [node_id]
        label = (vendors[node_id].legal_name if node_id in vendors else node_id)
    affected_ids = list(dict.fromkeys(affected_ids))

    engs = s.scalars(select(EngagementRecord)).all()
    aff_engs = [e for e in engs if e.vendor_id in set(affected_ids)]
    bus = {}
    for e in aff_engs:
        b = e.business_unit or "Unassigned"
        d = bus.setdefault(b, {"business_unit": b, "engagements": 0, "spend": 0.0,
                               "critical_engagements": 0, "vendors": set()})
        d["engagements"] += 1
        d["spend"] += float(e.annual_value or 0)
        d["vendors"].add(e.vendor_id)
        if (e.inherent_band or "").upper() in _HI:
            d["critical_engagements"] += 1
    bu_list = sorted(({**v, "vendors": len(v["vendors"]), "spend": round(v["spend"])}
                      for v in bus.values()), key=lambda x: -x["spend"])

    spend_at_risk = round(sum(float(e.annual_value or 0) for e in aff_engs))
    crit_vendors = sum(1 for vid in affected_ids if vendors.get(vid) and vendors[vid].is_critical)
    sla_sensitive = sum(1 for e in aff_engs if (e.inherent_band or "").upper() in _HI)
    # duration → estimated SLA breaches
    factor = 1.0 if hours >= 48 else 0.5 if hours >= 24 else 0.25
    est_breaches = round(sla_sensitive * factor)
    # severity
    score = crit_vendors * 3 + (3 if spend_at_risk > 50_000_000 else 2 if spend_at_risk > 10_000_000 else 1) \
        + (2 if hours >= 48 else 1 if hours >= 24 else 0)
    sev = "Severe" if score >= 9 else "High" if score >= 6 else "Moderate" if score >= 3 else "Low"

    aff_vendor_rows = []
    for vid in affected_ids:
        v = vendors.get(vid)
        ve = [e for e in aff_engs if e.vendor_id == vid]
        aff_vendor_rows.append({"vendor_id": vid, "legal_name": (v.legal_name if v else vid),
                                "is_critical": (v.is_critical if v else False),
                                "engagements": len(ve),
                                "spend": round(sum(float(e.annual_value or 0) for e in ve))})
    aff_vendor_rows.sort(key=lambda x: (-int(x["is_critical"]), -x["spend"]))

    brief = (f"Simulated loss of {label} for {hours}h cascades to {len(affected_ids)} vendor(s) "
             f"({crit_vendors} critical), {len(aff_engs)} engagement(s) across {len(bu_list)} business unit(s). "
             f"£{spend_at_risk:,} of annual contract value is exposed; {sla_sensitive} SLA-sensitive engagement(s), "
             f"~{est_breaches} likely to breach at this duration. Estimated severity: {sev}.")
    return {
        "scenario": {"node_type": node_type, "node_id": node_id, "label": label, "hours": hours},
        "severity": sev,
        "stats": {"vendors_affected": len(affected_ids), "critical_vendors": crit_vendors,
                  "engagements_affected": len(aff_engs), "bus_affected": len(bu_list),
                  "spend_at_risk": spend_at_risk, "sla_sensitive": sla_sensitive,
                  "est_sla_breaches": est_breaches},
        "business_units": bu_list,
        "affected_vendors": aff_vendor_rows[:40],
        "brief": brief,
    }
