"""Phase 3 — Exposure & event linkage (point-in-time).
  • BU-level exposure profiles (vendors, criticality, spend, residual mix, open findings),
  • cross-BU shared-vendor view,
  • incident-to-issue matching (incident → open findings on the vendor + peers with the same gap).
No history required."""
from __future__ import annotations
import re
from sqlalchemy import select

_BAND_RANK = {"LOW": 1, "MODERATE": 2, "MEDIUM": 2, "ELEVATED": 3, "HIGH": 4, "CRITICAL": 5}
_STOP = set("the a an and or of for to in on with by is are this that our your their "
            "vendor service services provider system data at from as it its".split())


def _kw(text):
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _STOP}


def bu_exposure(s) -> dict:
    from app.features.domain.registry_models import (VendorRecord, EngagementRecord, FindingRecord)
    vmap = {v.vendor_id: v for v in s.scalars(select(VendorRecord)).all()}
    engs = s.scalars(select(EngagementRecord)).all()
    finds = s.scalars(select(FindingRecord)).all()
    open_find_by_vendor = {}
    for f in finds:
        if f.status != "Closed" and f.vendor_id:
            open_find_by_vendor.setdefault(f.vendor_id, []).append(f)

    bu = {}                      # bu -> aggregates
    vendor_bus = {}              # vendor_id -> set(bu)
    for e in engs:
        b = e.business_unit or "Unassigned"
        slot = bu.setdefault(b, {"business_unit": b, "engagements": 0, "vendors": set(),
                                 "critical": set(), "spend": 0.0,
                                 "residual": {"LOW": 0, "MODERATE": 0, "ELEVATED": 0, "HIGH": 0, "CRITICAL": 0}})
        slot["engagements"] += 1
        if e.vendor_id:
            slot["vendors"].add(e.vendor_id)
            vendor_bus.setdefault(e.vendor_id, set()).add(b)
            v = vmap.get(e.vendor_id)
            if v and v.is_critical:
                slot["critical"].add(e.vendor_id)
        slot["spend"] += float(getattr(e, "annual_value", 0) or 0)
        rb = str(getattr(e, "residual_band", "") or "").upper()
        if rb in slot["residual"]:
            slot["residual"][rb] += 1

    profiles = []
    for b, d in bu.items():
        open_findings = sum(len(open_find_by_vendor.get(vid, [])) for vid in d["vendors"])
        high_res = d["residual"]["HIGH"] + d["residual"]["CRITICAL"] + d["residual"]["ELEVATED"]
        exposure_score = len(d["critical"]) * 3 + high_res * 2 + open_findings
        profiles.append({
            "business_unit": b, "engagements": d["engagements"],
            "vendor_count": len(d["vendors"]), "critical_count": len(d["critical"]),
            "spend": round(d["spend"]), "residual": d["residual"],
            "open_findings": open_findings, "exposure_score": exposure_score,
        })
    profiles.sort(key=lambda x: x["exposure_score"], reverse=True)

    cross = []
    for vid, bus in vendor_bus.items():
        if len(bus) > 1:
            v = vmap.get(vid)
            cross.append({"vendor_id": vid, "legal_name": v.legal_name if v else vid,
                          "is_critical": v.is_critical if v else False,
                          "business_units": sorted(bus), "bu_count": len(bus)})
    cross.sort(key=lambda x: x["bu_count"], reverse=True)

    return {"business_units": profiles, "cross_bu_shared_vendors": cross[:40],
            "bu_count": len(profiles), "shared_vendor_count": len(cross)}


def incident_match(s, vendor_id: str, description: str, domain: str | None = None) -> dict:
    """Match an incident to the vendor's open findings, and to peers carrying the same gap."""
    from app.features.domain.registry_models import VendorRecord, FindingRecord
    vmap = {v.vendor_id: v for v in s.scalars(select(VendorRecord)).all()}
    finds = s.scalars(select(FindingRecord)).all()
    kw = _kw(description) | ({domain.lower()} if domain else set())

    def score(f):
        fkw = _kw((f.title or "") + " " + (f.description or "") + " " + (f.suggested_remediation or ""))
        overlap = len(kw & fkw)
        if domain and f.domain and domain.lower() in (f.domain or "").lower():
            overlap += 3
        return overlap

    own = [f for f in finds if f.vendor_id == vendor_id and f.status != "Closed"]
    matched = sorted(own, key=score, reverse=True)
    matched_out = [{"finding_id": f.finding_id, "title": f.title, "severity": f.severity,
                    "status": f.status, "domain": f.domain, "match": score(f)} for f in matched]
    # domains/keywords of the matched (or incident) to find peer exposure
    domains = {(f.domain or "").lower() for f in matched if f.domain}
    if domain:
        domains.add(domain.lower())
    peers = {}
    for f in finds:
        if f.vendor_id == vendor_id or f.status == "Closed" or not f.vendor_id:
            continue
        d = (f.domain or "").lower()
        if (d and d in domains) or (score(f) >= 2):
            v = vmap.get(f.vendor_id)
            slot = peers.setdefault(f.vendor_id, {"vendor_id": f.vendor_id,
                    "legal_name": v.legal_name if v else f.vendor_id,
                    "is_critical": v.is_critical if v else False, "findings": []})
            slot["findings"].append({"finding_id": f.finding_id, "title": f.title,
                                     "domain": f.domain, "severity": f.severity})
    peer_list = sorted(peers.values(), key=lambda x: (not x["is_critical"], -len(x["findings"])))
    return {"vendor_id": vendor_id, "vendor": (vmap.get(vendor_id).legal_name if vendor_id in vmap else vendor_id),
            "matched_findings": matched_out, "peer_exposure": peer_list[:30],
            "peer_count": len(peer_list)}
