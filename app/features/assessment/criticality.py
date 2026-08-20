"""Critical Vendor Modelling — transparency.
Exposes a transparent, weighted criticality model derived from engagement-level
IRQ outcomes (inherent band/score) and impact data (financial materiality, business
unit, pervasiveness, substitutability/concentration). For every vendor it shows
which factors fired and by how much — so a reviewer can see exactly WHY a vendor is
critical, and for high-risk vendors that are not flagged, WHY they fall short of the
threshold."""
from __future__ import annotations
from sqlalchemy import select

# Transparent model — weights and thresholds are explicit and shown in the UI.
FACTORS = [
    {"key": "inherent", "label": "Service & inherent risk (IRQ)", "max": 4,
     "detail": "Highest inherent band across the vendor's engagements (IRQ outcome)."},
    {"key": "materiality", "label": "Financial materiality", "max": 3,
     "detail": "Total annual contract value across engagements."},
    {"key": "concentration", "label": "Substitutability / concentration", "max": 2,
     "detail": "Reliance on a shared sub-provider that is a single point of failure."},
    {"key": "bu", "label": "Business-unit importance", "max": 1,
     "detail": "Supports a front-office / core operational business unit."},
    {"key": "pervasiveness", "label": "Pervasiveness", "max": 1,
     "detail": "Breadth of engagements across the organisation."},
]
THRESHOLD = 6          # score >= THRESHOLD ⇒ model says Critical (max 11)
NEAR_MARGIN = 2        # within this of threshold ⇒ "near-miss"
_CORE_BUS = {"Technology", "Operations"}
_BAND_RANK = {"LOW": 1, "MODERATE": 2, "MEDIUM": 2, "ELEVATED": 3, "HIGH": 4, "CRITICAL": 5}


def _spof_vendor_ids(s) -> set:
    from app.features.domain.registry_models import FourthPartyVendor
    links = s.scalars(select(FourthPartyVendor)).all()
    cnt = {}
    for ln in links:
        cnt.setdefault(ln.fourth_party_id, []).append(ln.vendor_id)
    total = len({ln.vendor_id for ln in links}) or 1
    spof_fps = {fid for fid, v in cnt.items() if len(v) >= max(10, total * 0.15)}
    out = set()
    for fid in spof_fps:
        out.update(cnt[fid])
    return out


def _score(v, engs, spof_ids, threshold=THRESHOLD) -> dict:
    factors = {}
    # inherent
    worst = 0
    for e in engs:
        worst = max(worst, _BAND_RANK.get(str(e.inherent_band or "").upper(), 0))
    inh_pts = {5: 4, 4: 4, 3: 2, 2: 1}.get(worst, 0)
    worst_band = next((b for b, r in _BAND_RANK.items() if r == worst), "—")
    factors["inherent"] = (inh_pts, f"Worst inherent band: {worst_band}")
    # materiality
    spend = sum(float(e.annual_value or 0) for e in engs)
    mat_pts = 3 if spend > 5_000_000 else 2 if spend > 1_000_000 else 1 if spend > 250_000 else 0
    factors["materiality"] = (mat_pts, f"£{round(spend):,} total annual value")
    # concentration / substitutability
    conc = 2 if v.vendor_id in spof_ids else 0
    factors["concentration"] = (conc, "Relies on a single-point-of-failure sub-provider" if conc else "No SPOF sub-provider dependency")
    # BU importance
    bus = {e.business_unit for e in engs if e.business_unit}
    bu_pts = 1 if (bus & _CORE_BUS) else 0
    factors["bu"] = (bu_pts, ("Core BU: " + ", ".join(sorted(bus & _CORE_BUS))) if bu_pts else "No core front-office BU")
    # pervasiveness
    perv = 1 if len(engs) >= 3 else 0
    factors["pervasiveness"] = (perv, f"{len(engs)} engagement(s)")

    score = sum(p for p, _ in factors.values())
    breakdown = [{"key": f["key"], "label": f["label"], "max": f["max"],
                  "points": factors[f["key"]][0], "detail": factors[f["key"]][1],
                  "fired": factors[f["key"]][0] > 0} for f in FACTORS]
    return {"score": score, "max": sum(f["max"] for f in FACTORS), "factors": breakdown,
            "model_critical": score >= threshold}


def _eng_rows(engs):
    return [{"engagement_id": e.engagement_id, "title": e.title,
             "inherent_band": e.inherent_band, "inherent_score": e.inherent_score,
             "residual_band": e.residual_band, "business_unit": e.business_unit,
             "annual_value": round(float(e.annual_value or 0)),
             "deployment_model": e.deployment_model, "status": e.status}
            for e in engs]


def model(s) -> dict:
    from app.features.domain.registry_models import VendorRecord, EngagementRecord
    from app.features.domain.config_store import get_config
    threshold = get_config(s, "criticality.threshold", THRESHOLD)
    near_margin = get_config(s, "criticality.near_margin", NEAR_MARGIN)
    vendors = s.scalars(select(VendorRecord)).all()
    engs = s.scalars(select(EngagementRecord)).all()
    eng_by_vendor = {}
    for e in engs:
        eng_by_vendor.setdefault(e.vendor_id, []).append(e)
    spof_ids = _spof_vendor_ids(s)

    critical, subthreshold = [], []
    for v in vendors:
        ve = eng_by_vendor.get(v.vendor_id, [])
        sc = _score(v, ve, spof_ids, threshold)
        row = {"vendor_id": v.vendor_id, "legal_name": v.legal_name,
               "tier": v.tier, "is_critical": v.is_critical,
               "score": sc["score"], "max": sc["max"], "model_critical": sc["model_critical"],
               "factors": sc["factors"], "engagements": _eng_rows(ve)}
        if v.is_critical:
            critical.append(row)
        else:
            worst = max((_BAND_RANK.get(str(e.inherent_band or "").upper(), 0) for e in ve), default=0)
            spend = sum(float(e.annual_value or 0) for e in ve)
            high_risk = worst >= 3 or spend > 1_000_000 or v.vendor_id in spof_ids
            if high_risk:
                # why it falls short — the factors that did NOT fire / are below max
                gaps = [f["label"] for f in sc["factors"] if not f["fired"]]
                row["gap_to_threshold"] = max(0, threshold - sc["score"])
                row["near_miss"] = sc["score"] >= threshold - near_margin
                row["why_not"] = gaps
                subthreshold.append(row)

    critical.sort(key=lambda x: x["score"], reverse=True)
    subthreshold.sort(key=lambda x: x["score"], reverse=True)
    return {
        "threshold": threshold, "near_margin": near_margin,
        "factors_legend": FACTORS,
        "critical_vendors": critical,
        "subthreshold_high_risk": subthreshold,
        "stats": {"critical": len(critical), "subthreshold": len(subthreshold),
                  "model_flag_agree": sum(1 for r in critical if r["model_critical"]),
                  "near_miss": sum(1 for r in subthreshold if r.get("near_miss"))},
    }
