"""Ask-anything portfolio copilot. A deterministic query engine over the live estate
that returns REAL matching records (with IDs for drill-through), so answers are always
grounded — never hallucinated. An AI narrative can be layered on top when available."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select

_COUNTRIES = ["united kingdom", "united states", "ireland", "germany", "india",
              "singapore", "china", "hong kong", "taiwan", "netherlands", "france",
              "japan", "brazil", "australia"]
_BUS = ["markets", "wealth management", "technology", "operations",
        "risk & compliance", "corporate banking"]


def _days_to(date_str):
    if not date_str:
        return None
    try:
        d = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (d - datetime.now(timezone.utc)).days
    except Exception:
        return None


def answer_query(s, question: str) -> dict:
    from app.features.domain.registry_models import (VendorRecord, EngagementRecord, FindingRecord,
                                  IncidentRecord, FourthPartyVendor)
    from app.features.assessment import criticality as CRIT
    from app.features.intelligence import geopolitical as GEO
    q = (question or "").lower()
    vendors = s.scalars(select(VendorRecord)).all()
    vmap = {v.vendor_id: v for v in vendors}
    engs = s.scalars(select(EngagementRecord)).all()
    finds = s.scalars(select(FindingRecord)).all()
    incs = s.scalars(select(IncidentRecord)).all()

    want_findings = any(w in q for w in ["finding", "issue", "gap"])
    want_incidents = any(w in q for w in ["incident", "outage", "breach event"])
    want_engagements = any(w in q for w in ["engagement", "contract", "renewal", "expir"])
    entity = ("findings" if want_findings else "incidents" if want_incidents
              else "engagements" if want_engagements else "vendors")

    crit_only = "critical" in q
    high_only = "high" in q
    open_only = "open" in q or "unresolved" in q
    spof = any(w in q for w in ["spof", "single point", "concentration"])
    geo = any(w in q for w in ["geopolit", "export", "sanction", "dual-use", "component"])
    country = next((c for c in _COUNTRIES if c in q), None)
    bu = next((b for b in _BUS if b in q), None)
    breach = "breach" in q or "late" in q or "sla" in q
    cust = "customer" in q

    spof_ids = CRIT._spof_vendor_ids(s) if (spof or entity == "vendors") else set()
    geo_ids = set()
    if geo or country:
        geo_ids = {f["vendor_id"] for f in GEO.exposure(s)["flagged_vendors"]}

    filt = []
    rows = []

    if entity == "vendors":
        out = vendors
        if crit_only:
            out = [v for v in out if v.is_critical]; filt.append("critical")
        if spof:
            out = [v for v in out if v.vendor_id in spof_ids]; filt.append("SPOF-exposed")
        if geo:
            out = [v for v in out if v.vendor_id in geo_ids]; filt.append("geopolitically exposed")
        if country:
            out = [v for v in out if (v.hq_country or "").lower() == country]; filt.append(country.title())
        for v in out[:50]:
            sub = " · ".join(x for x in [v.tier, "critical" if v.is_critical else None, v.hq_country] if x)
            rows.append({"type": "vendor", "id": v.vendor_id, "label": v.legal_name, "sublabel": sub})

    elif entity == "findings":
        out = finds
        if open_only or not ("closed" in q):
            out = [f for f in out if f.status != "Closed"]; filt.append("open")
        if crit_only:
            out = [f for f in out if (f.severity or "") == "Critical"]; filt.append("critical")
        elif high_only:
            out = [f for f in out if (f.severity or "") in ("High", "Critical")]; filt.append("high/critical")
        if bu:
            bu_v = {e.vendor_id for e in engs if (e.business_unit or "").lower() == bu}
            out = [f for f in out if f.vendor_id in bu_v]; filt.append(bu.title())
        for f in out[:50]:
            v = vmap.get(f.vendor_id)
            rows.append({"type": "finding", "id": f.finding_id, "label": f.title or f.finding_id,
                         "sublabel": " · ".join(x for x in [f.severity, f.status, (v.legal_name if v else f.vendor_id)] if x)})

    elif entity == "incidents":
        out = incs
        if open_only or ("open" in q):
            out = [i for i in out if i.status != "Closed"]; filt.append("open")
        if crit_only:
            out = [i for i in out if i.severity == "Critical"]; filt.append("critical")
        elif high_only:
            out = [i for i in out if i.severity in ("High", "Critical")]; filt.append("high/critical")
        if breach:
            out = [i for i in out if i.notification_compliant == "red"]; filt.append("notification breach")
        if cust:
            out = [i for i in out if i.customer_impacting]; filt.append("customer-impacting")
        for i in out[:50]:
            rows.append({"type": "incident", "id": i.incident_id,
                         "label": f"{i.incident_type or 'Incident'} · {i.vendor_name or i.vendor_id or ''}",
                         "sublabel": " · ".join(x for x in [i.severity, i.status,
                                     (("notification " + i.notification_compliant.upper()) if i.notification_compliant else None)] if x)})

    else:  # engagements
        out = engs
        if "expir" in q or "renewal" in q:
            out = [e for e in out if (lambda d: d is not None and d <= 120)(_days_to(e.end_date))]; filt.append("expiring ≤120d")
        if high_only or crit_only:
            out = [e for e in out if (e.inherent_band or "").upper() in ("HIGH", "CRITICAL")]; filt.append("high inherent")
        if bu:
            out = [e for e in out if (e.business_unit or "").lower() == bu]; filt.append(bu.title())
        for e in out[:50]:
            v = vmap.get(e.vendor_id)
            rows.append({"type": "engagement", "id": e.engagement_id, "vendor_id": e.vendor_id,
                         "label": f"{e.title or e.engagement_id}",
                         "sublabel": " · ".join(x for x in [e.inherent_band, e.business_unit, (v.legal_name if v else e.vendor_id)] if x)})

    count = len(rows)
    answer = (f"Found {count} {entity}" + (f" matching: {', '.join(filt)}" if filt else "") + ".")
    return {"entity": entity, "count": count, "filters": filt, "answer": answer, "rows": rows}
