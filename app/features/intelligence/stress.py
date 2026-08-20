"""Supply-chain stress radar — DEMONSTRATOR (point-in-time).
Scores each vendor on TODAY's signals (open high findings, recent incidents,
notification breaches, concentration, geopolitical exposure, worst residual band).
This is a transparent point-in-time score, NOT a predictive forecast — genuine
distress prediction requires a time-series history of these signals, which the
platform does not yet capture. The UI states this explicitly."""
from __future__ import annotations
from sqlalchemy import select

WEIGHTS = [
    {"key": "findings", "label": "Open high/critical findings", "max": 24},
    {"key": "incidents", "label": "Recent incidents", "max": 26},
    {"key": "breaches", "label": "Notification-SLA breaches", "max": 12},
    {"key": "concentration", "label": "Concentration / SPOF reliance", "max": 15},
    {"key": "geopolitical", "label": "Geopolitical / export-control exposure", "max": 12},
    {"key": "residual", "label": "Worst residual risk band", "max": 12},
]
_HI = {"HIGH", "CRITICAL"}
_BAND_RANK = {"LOW": 1, "MODERATE": 2, "MEDIUM": 2, "ELEVATED": 3, "HIGH": 4, "CRITICAL": 5}


def _band(score):
    return "Severe" if score >= 60 else "High" if score >= 40 else "Elevated" if score >= 20 else "Stable"


def radar(s) -> dict:
    from app.features.domain.registry_models import (VendorRecord, EngagementRecord, FindingRecord, IncidentRecord)
    from app.features.assessment import criticality as CRIT
    from app.features.intelligence import geopolitical as GEO
    vendors = s.scalars(select(VendorRecord)).all()
    engs = s.scalars(select(EngagementRecord)).all()
    finds = s.scalars(select(FindingRecord)).all()
    incs = s.scalars(select(IncidentRecord)).all()
    eng_by = {}
    for e in engs:
        eng_by.setdefault(e.vendor_id, []).append(e)
    find_by = {}
    for f in finds:
        if f.status != "Closed":
            find_by.setdefault(f.vendor_id, []).append(f)
    inc_by = {}
    for i in incs:
        inc_by.setdefault(i.vendor_id, []).append(i)
    spof_ids = CRIT._spof_vendor_ids(s)
    geo_ids = {f["vendor_id"] for f in GEO.exposure(s)["flagged_vendors"]}

    rows = []
    for v in vendors:
        vf = find_by.get(v.vendor_id, [])
        vi = inc_by.get(v.vendor_id, [])
        ve = eng_by.get(v.vendor_id, [])
        drivers = []
        # findings
        hi = sum(1 for f in vf if (f.severity or "") in ("High", "Critical"))
        p_find = min(hi * 8, 24)
        if p_find:
            drivers.append({"label": f"{hi} open high/critical finding(s)", "points": p_find})
        # incidents
        p_inc = min(len(vi) * 7, 19) + (7 if any(i.severity == "Critical" for i in vi) else 0)
        p_inc = min(p_inc, 26)
        if p_inc:
            drivers.append({"label": f"{len(vi)} recent incident(s)", "points": p_inc})
        # breaches
        br = sum(1 for i in vi if i.notification_compliant == "red")
        p_br = min(br * 6, 12)
        if p_br:
            drivers.append({"label": f"{br} notification-SLA breach(es)", "points": p_br})
        # concentration
        p_conc = 15 if v.vendor_id in spof_ids else 0
        if p_conc:
            drivers.append({"label": "Single-point-of-failure concentration", "points": p_conc})
        # geopolitical
        p_geo = 12 if v.vendor_id in geo_ids else 0
        if p_geo:
            drivers.append({"label": "Geopolitical / export-control exposure", "points": p_geo})
        # residual
        worst = max((_BAND_RANK.get(str(e.residual_band or "").upper(), 0) for e in ve), default=0)
        p_res = 12 if worst >= 5 else 8 if worst == 4 else 0
        if p_res:
            drivers.append({"label": f"Worst residual band: {'CRITICAL' if worst>=5 else 'HIGH'}", "points": p_res})
        score = min(p_find + p_inc + p_br + p_conc + p_geo + p_res, 100)
        if score <= 0:
            continue
        drivers.sort(key=lambda d: -d["points"])
        rows.append({"vendor_id": v.vendor_id, "legal_name": v.legal_name,
                     "is_critical": v.is_critical, "tier": v.tier,
                     "stress": score, "band": _band(score), "drivers": drivers})
    rows.sort(key=lambda r: (-r["stress"], -int(r["is_critical"])))
    dist = {"Severe": 0, "High": 0, "Elevated": 0, "Stable": 0}
    for r in rows:
        dist[r["band"]] += 1
    return {"demonstrator": True, "weights": WEIGHTS,
            "stats": {"scored": len(rows), **dist,
                      "watchlist": sum(1 for r in rows if r["band"] in ("Severe", "High"))},
            "vendors": rows}
