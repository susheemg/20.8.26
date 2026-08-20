"""Phase 4 — Export-control / geopolitical sensor (point-in-time + AI live scan).
Maps a deterministic country-risk baseline (sanctions, export controls, dual-use,
component-shortage exposure) onto vendor domiciles and sub-processor geographies,
and flags exposed vendors. The AI scan (gated) brings live actions on top.
Wired to Global Regulations (sanctions / dual-use are regulatory instruments)."""
from __future__ import annotations
from sqlalchemy import select

# Demonstrator baseline. Levels: low / moderate / elevated / high.
COUNTRY_RISK = {
    "Russia": {"level": "high", "drivers": ["comprehensive sanctions", "export bans (dual-use)"], "component": False},
    "Iran": {"level": "high", "drivers": ["comprehensive sanctions"], "component": False},
    "China": {"level": "elevated", "drivers": ["US/EU advanced-semiconductor & equipment export controls",
                                              "dual-use scrutiny", "data localisation"], "component": True},
    "Hong Kong": {"level": "elevated", "drivers": ["re-export / diversion risk", "alignment with PRC controls"], "component": True},
    "Taiwan": {"level": "moderate", "drivers": ["semiconductor concentration", "cross-strait tension"], "component": True},
    "India": {"level": "low", "drivers": ["data localisation (DPDP)"], "component": False},
    "Singapore": {"level": "low", "drivers": ["transhipment scrutiny"], "component": False},
    "United States": {"level": "low", "drivers": ["origin of many export-control regimes"], "component": False},
    "United Kingdom": {"level": "low", "drivers": [], "component": False},
    "Ireland": {"level": "low", "drivers": [], "component": False},
    "Germany": {"level": "low", "drivers": ["EU dual-use regime"], "component": False},
    "Netherlands": {"level": "low", "drivers": ["lithography export controls (ASML)"], "component": True},
}
_LEVEL_RANK = {"low": 0, "moderate": 1, "elevated": 2, "high": 3}


def _crisk(country):
    return COUNTRY_RISK.get((country or "").strip(), {"level": "low", "drivers": [], "component": False})


def exposure(s) -> dict:
    from app.features.domain.registry_models import (VendorRecord, FourthPartyRecord, FourthPartyVendor)
    vendors = s.scalars(select(VendorRecord)).all()
    fps = {f.fourth_party_id: f for f in s.scalars(select(FourthPartyRecord)).all()}
    fp_by_vendor = {}
    for ln in s.scalars(select(FourthPartyVendor)).all():
        fp_by_vendor.setdefault(ln.vendor_id, []).append(ln.fourth_party_id)

    juris = {}   # country -> {vendors, sub_providers, level, drivers, component}
    flagged = []
    for v in vendors:
        own_c = v.hq_country or v.incorporation_country
        geos = []  # (country, via)
        if own_c:
            geos.append((own_c, "domicile"))
        sub_geos = []
        for fid in fp_by_vendor.get(v.vendor_id, []):
            f = fps.get(fid)
            if f and f.hq_country:
                sub_geos.append((f.hq_country, f.legal_name))
                geos.append((f.hq_country, f"sub-processor {f.legal_name}"))
        # tally jurisdictions
        for c, via in geos:
            r = _crisk(c)
            slot = juris.setdefault(c, {"country": c, "level": r["level"], "drivers": r["drivers"],
                                        "component": r["component"], "vendors": set(), "as_subprocessor": 0})
            if via == "domicile":
                slot["vendors"].add(v.vendor_id)
            else:
                slot["as_subprocessor"] += 1
        # flag the vendor on its worst geography
        worst = None
        for c, via in geos:
            r = _crisk(c)
            if worst is None or _LEVEL_RANK[r["level"]] > _LEVEL_RANK[worst[1]["level"]]:
                worst = (c, r, via)
        if worst and _LEVEL_RANK[worst[1]["level"]] >= 1:  # moderate+
            c, r, via = worst
            component_flag = r["component"] and (v.is_critical or "sub-processor" in via)
            flagged.append({
                "vendor_id": v.vendor_id, "legal_name": v.legal_name, "is_critical": v.is_critical,
                "country": c, "via": via, "level": r["level"], "drivers": r["drivers"],
                "component_shortage_risk": component_flag,
            })
    flagged.sort(key=lambda x: (-_LEVEL_RANK[x["level"]], not x["is_critical"]))

    juris_out = []
    for c, d in juris.items():
        juris_out.append({"country": c, "level": d["level"], "drivers": d["drivers"],
                          "component": d["component"], "vendor_count": len(d["vendors"]),
                          "as_subprocessor": d["as_subprocessor"]})
    juris_out.sort(key=lambda x: (-_LEVEL_RANK[x["level"]], -x["vendor_count"]))

    stats = {
        "vendors": len(vendors),
        "exposed_vendors": len(flagged),
        "component_shortage_vendors": sum(1 for f in flagged if f["component_shortage_risk"]),
        "high_risk_jurisdictions": sum(1 for j in juris_out if _LEVEL_RANK[j["level"]] >= 2),
    }
    return {"stats": stats, "jurisdictions": juris_out, "flagged_vendors": flagged}
