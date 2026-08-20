"""PESTLE threat-intelligence layer.

Attaches a 150-dimension PESTLE risk vector to every vendor and engagement.
Scores are derived from entity attributes (attribute-driven synthetic baseline)
and refreshed by a simulated overnight sweep that stands in for a real
News-stories + Reputation analysis pipeline. The sweep is date-seeded so a given
day's result is stable and reproducible (and clearly labelled synthetic).
"""
from __future__ import annotations
import hashlib, json
from datetime import date

# ---- taxonomy: 6 PESTLE categories x 25 threats = 150 dimensions ----
CATEGORIES = {
    "POL": {"name": "Political",      "color": "#B45309"},
    "ECO": {"name": "Economic",       "color": "#1E3A5C"},
    "SOC": {"name": "Social",         "color": "#7C3AED"},
    "TEC": {"name": "Technological",  "color": "#0E6E45"},
    "LEG": {"name": "Legal",          "color": "#8A2E3B"},
    "ENV": {"name": "Environmental",  "color": "#0E7490"},
}
_NAMES = {
"POL": ["Geopolitical conflict exposure","Sanctions & export controls","Trade war / tariffs",
 "Political instability (ops country)","Government change / policy reversal","State-sponsored cyber threat",
 "Nationalisation / expropriation","Foreign-ownership restrictions","Diplomatic tensions on supply",
 "Election-driven uncertainty","Corruption / bribery exposure","Civil unrest / protests",
 "Border / customs disruption","Labour-mobility / visa restriction","Critical-infrastructure designation",
 "Data-localisation mandates","Government surveillance exposure","Defence / dual-use scrutiny",
 "Regulatory capture / lobbying","Transfer-pricing politics","Sovereign-debt intervention",
 "Sector embargo","Political pressure on ESG","State control of telecoms","Public-sector dependency"],
"ECO": ["Vendor financial distress","Liquidity / cash-flow shortfall","Currency volatility (FX)",
 "Inflation / cost escalation","Interest-rate sensitivity","Recession / demand collapse",
 "Vendor customer concentration","Input-cost shock","Credit-rating downgrade",
 "Refinancing / debt-maturity wall","Margin compression","M&A / ownership disruption",
 "PE over-leverage","Pension / liability overhang","Commodity-price exposure",
 "Pricing-power erosion","Working-capital strain","Going-concern qualification",
 "Revenue concentration on us","Covenant breach / cross-default","Subsidy / grant dependency",
 "Market-share loss","Capex underinvestment","Sanctions hitting revenue","Financial-misstatement risk"],
"SOC": ["Reputational / brand damage","Negative media coverage","Social-media backlash",
 "Labour disputes / strikes","Key-person / skills shortage","Modern slavery in chain",
 "Poor labour conditions","DEI / discrimination controversy","Health & safety incidents",
 "Licence-to-operate loss","Customer-trust erosion","Workforce attrition","Cultural misalignment",
 "Whistleblower allegations","Activist / NGO campaigns","Talent-pipeline shift",
 "Public-health disruption","Targeted misinformation","Executive-conduct scandal",
 "Unethical-sourcing exposure","Accessibility / inclusion failure","Stakeholder contract pressure",
 "Consumer-behaviour shift","Regional social-licence loss","4th-party reputational contagion"],
"TEC": ["Cyberattack / data breach","Ransomware exposure","Legacy / unsupported tech",
 "Cloud-concentration / outage","Software supply-chain compromise","Unpatched critical CVEs",
 "Insider threat","AI / model risk & bias","Shadow IT / unmanaged assets",
 "Weak encryption / key mgmt","Identity & access weakness","Third-party API dependency",
 "Data-loss / backup failure","Availability / SLA failure","Tech obsolescence",
 "Weak change management","Quantum-crypto horizon","IoT / OT security gaps",
 "Open-source / licensing risk","Single point of technical failure","Inadequate logging / monitoring",
 "DDoS exposure","Generative-AI data leakage","Brittle integration / tech debt","R&D / innovation lag"],
"LEG": ["Regulatory non-compliance","GDPR / data-protection breach","DORA resilience gaps",
 "NIS2 / cyber-regulation exposure","Weak contractual terms","Litigation / disputes",
 "IP infringement / theft","Antitrust / competition probe","AML / financial-crime exposure",
 "Bribery (FCPA / UKBA)","Cross-border transfer (SCCs)","Licensing / authorisation lapse",
 "Sanctions-screening failure","Liability / indemnity gap","Regulatory fines / enforcement",
 "Sub-processor flow-down gap","Consumer-protection breach","Employment-law disputes",
 "Tax-compliance exposure","Records / e-discovery failure","Right-to-audit denied",
 "Insurance-coverage gap","ESG-disclosure non-compliance","Whistleblowing-law breach",
 "Governing-law conflict"],
"ENV": ["Acute physical climate risk","Chronic climate / heat stress","Flood exposure",
 "Wildfire exposure","Water scarcity / stress","Carbon-transition regulation",
 "Energy-supply disruption","Extreme-weather supply shock","Greenwashing / ESG misrep",
 "Pollution / contamination","Biodiversity / land-use harm","Waste / circularity failure",
 "Scope-3 emissions exposure","Seismic / disaster site risk","Rare-earth dependency",
 "Environmental-permit breach","Stranded-asset risk","Deforestation in chain",
 "Decarbonisation-cost burden","Data-centre energy intensity","Sea-level-rise site exposure",
 "Drought-driven ops risk","Hazardous-materials handling","Climate-litigation exposure",
 "Climate supply-route disruption"],
}
THREATS = []  # [{id, cat, name}]
for _cat, _lst in _NAMES.items():
    for _i, _nm in enumerate(_lst, 1):
        THREATS.append({"id": f"{_cat}-{_i:02d}", "cat": _cat, "name": _nm})
THREAT_BY_ID = {t["id"]: t for t in THREATS}
assert len(THREATS) == 150, len(THREATS)

# ---- elevated-risk country lenses (synthetic, illustrative) ----
_GEO_HI = {"Russia", "Ukraine", "China", "Pakistan", "Nigeria", "Egypt", "Turkey", "Saudi Arabia"}
_GEO_MED = {"India", "United Arab Emirates", "Indonesia", "Philippines", "Vietnam", "Brazil",
            "Mexico", "South Africa", "Thailand", "Malaysia", "Israel", "Hong Kong"}
_ENV_HI = {"India", "China", "Pakistan", "Indonesia", "Philippines", "Nigeria", "Australia",
           "United Arab Emirates", "Saudi Arabia", "Egypt", "Brazil"}
_BAND_LIFT = {"LOW": -6, "MODERATE": 2, "ELEVATED": 8, "HIGH": 16, "CRITICAL": 22}
_FIN_LIFT = {"Strong": -8, "Adequate": 0, "Watch": 12, "Distressed": 24}


def _h(*parts):
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest(), 16)


def _noise(seed, lo=-16, hi=16):
    return lo + (_h(seed) % 10000) / 10000 * (hi - lo)


def _clamp(v, lo=4, hi=99):
    return int(max(lo, min(hi, round(v))))


def _geo(country):
    if country in _GEO_HI: return 26
    if country in _GEO_MED: return 13
    return 0


def category_bases(ctx):
    """Per-entity baseline level for each PESTLE category, from attributes."""
    hq = ctx.get("hq_country") or ""
    inc = ctx.get("incorporation_country") or hq
    tier = ctx.get("tier") or "Tier 3"
    t1 = "1" in tier
    crit = bool(ctx.get("is_critical"))
    band = (ctx.get("inherent_band") or "MODERATE").upper()
    fin = ctx.get("financial_band") or "Adequate"
    public = (ctx.get("listing_status") or "").lower().startswith("pub")
    lift = _BAND_LIFT.get(band, 2)
    return {
        "POL": 24 + _geo(hq) + _geo(inc) // 2 + (8 if crit else 0) + lift // 2,
        "ECO": 26 + _FIN_LIFT.get(fin, 0) + (8 if t1 else 0) + lift // 2 + (4 if public else 0),
        "SOC": 22 + (10 if public else 0) + (8 if crit else 0) + lift // 2,
        "TEC": 28 + (16 if crit else 0) + (10 if t1 else 0) + lift,
        "LEG": 25 + _geo(hq) // 2 + (10 if crit else 0) + lift // 2 + (6 if public else 0),
        "ENV": 20 + (18 if hq in _ENV_HI else 0) + lift // 3,
    }


def baseline_vector(ctx, entity_key):
    """150-dim baseline: category base + per-threat deterministic variation."""
    bases = category_bases(ctx)
    vec = {}
    for t in THREATS:
        vec[t["id"]] = _clamp(bases[t["cat"]] + _noise((entity_key, t["id"])))
    return vec


def apply_sweep(base_vec, entity_key, as_of):
    """Simulated overnight News + Reputation sweep: move ~18% of dimensions by a
    small date-seeded delta. Returns (current_vec, movers)."""
    cur, movers = {}, []
    for tid, b in base_vec.items():
        hh = _h("news", entity_key, tid, as_of)
        delta = 0
        if hh % 100 < 18:                     # ~18% of threats "move" today
            delta = ((hh // 100) % 17) - 8     # -8..+8
        nv = _clamp(b + delta)
        cur[tid] = nv
        if abs(delta) >= 5:
            movers.append({"id": tid, "delta": nv - b})
    movers.sort(key=lambda m: -abs(m["delta"]))
    return cur, movers[:6]


def rollups(vec):
    cats = {}
    for c in CATEGORIES:
        vals = [vec[t["id"]] for t in THREATS if t["cat"] == c]
        cats[c] = round(sum(vals) / len(vals), 1)
    # overall weighted slightly toward the two worst categories
    ordered = sorted(cats.values(), reverse=True)
    overall = round(sum(ordered) / 6 * 0.6 + sum(ordered[:2]) / 2 * 0.4, 1)
    top = sorted(({"id": tid, "score": s, "name": THREAT_BY_ID[tid]["name"],
                   "cat": THREAT_BY_ID[tid]["cat"]} for tid, s in vec.items()),
                 key=lambda x: -x["score"])[:8]
    return cats, overall, top


def build_profile(ctx, entity_key, as_of):
    base = baseline_vector(ctx, entity_key)
    cur, movers = apply_sweep(base, entity_key, as_of)
    cats, overall, top = rollups(cur)
    return {"base": base, "vector": cur, "cats": cats, "overall": overall,
            "top": top, "movers": movers, "refreshed_at": as_of}


# ============ DB-facing service ============
def _fin_band_map(s):
    try:
        from app.features.domain.master_ext import VendorMasterExt
        rows = s.query(VendorMasterExt).all()
        return {getattr(r, "vendor_id", None): getattr(r, "financial_health_band", None) for r in rows}
    except Exception:
        return {}


def _contexts(s):
    """Return list of (entity_type, entity_id, label, ctx) for all vendors + engagements."""
    from app.features.domain.registry_models import VendorRecord, EngagementRecord
    fin = _fin_band_map(s)
    vmap = {}
    out = []
    for v in s.query(VendorRecord).all():
        ctx = {"hq_country": v.hq_country, "incorporation_country": v.incorporation_country,
               "tier": v.tier, "is_critical": v.is_critical, "listing_status": v.listing_status,
               "financial_band": fin.get(v.vendor_id)}
        vmap[v.vendor_id] = (v.legal_name, ctx)
        out.append(("vendor", v.vendor_id, v.legal_name, ctx))
    for e in s.query(EngagementRecord).all():
        vn, vctx = vmap.get(e.vendor_id, (e.vendor_id, {}))
        ctx = dict(vctx); ctx["inherent_band"] = e.inherent_band; ctx["business_unit"] = e.business_unit
        out.append(("engagement", e.engagement_id, (e.title or e.engagement_id), ctx))
    return out


def build_all(s, as_of=None):
    """Compute baseline + first sweep for every vendor & engagement; store profiles + summary."""
    from app.features.domain.registry_models import PestleProfile
    as_of = as_of or date.today().isoformat()
    s.query(PestleProfile).delete()
    existing = {}
    for etype, eid, label, ctx in _contexts(s):
        p = build_profile(ctx, eid, as_of)
        existing[(etype, eid)] = (label, p)
        s.add(PestleProfile(entity_type=etype, entity_id=eid, label=label,
              base_json=json.dumps(p["base"]), vector_json=json.dumps(p["vector"]),
              cats_json=json.dumps(p["cats"]), overall=p["overall"],
              top_json=json.dumps(p["top"]), movers_json=json.dumps(p["movers"]),
              refreshed_at=as_of))
    s.flush()
    _build_summary(s, as_of)
    return len(existing)


def refresh_all(s, as_of=None):
    """Re-run the overnight sweep against stored baselines (news + reputation stand-in)."""
    from app.features.domain.registry_models import PestleProfile
    as_of = as_of or date.today().isoformat()
    n = 0
    for p in s.query(PestleProfile).all():
        try:
            base = json.loads(p.base_json)
        except Exception:
            continue
        cur, movers = apply_sweep(base, p.entity_id, as_of)
        cats, overall, top = rollups(cur)
        p.vector_json = json.dumps(cur); p.cats_json = json.dumps(cats)
        p.overall = overall; p.top_json = json.dumps(top)
        p.movers_json = json.dumps(movers); p.refreshed_at = as_of
        n += 1
    s.flush()
    summary = _build_summary(s, as_of)
    return {"entities": n, "as_of": as_of, "movers": summary.get("movers", [])[:8]}


def _build_summary(s, as_of):
    from app.features.domain.registry_models import PestleProfile
    from app.features.domain import config_store as CFG
    rows = s.query(PestleProfile).all()
    n = max(1, len(rows))
    tsum = {t["id"]: 0 for t in THREATS}
    dsum = {t["id"]: 0 for t in THREATS}
    exposed = {t["id"]: [] for t in THREATS}
    for p in rows:
        try:
            vec = json.loads(p.vector_json); base = json.loads(p.base_json)
        except Exception:
            continue
        for tid, v in vec.items():
            tsum[tid] += v
            dsum[tid] += (v - base.get(tid, v))
            exposed[tid].append((v, p.entity_type, p.entity_id, p.label))
    threat_means = {tid: round(tsum[tid] / n, 1) for tid in tsum}
    cat_means = {}
    for c in CATEGORIES:
        vals = [threat_means[t["id"]] for t in THREATS if t["cat"] == c]
        cat_means[c] = round(sum(vals) / len(vals), 1)
    top_threats = sorted(({"id": tid, "score": threat_means[tid], "cat": THREAT_BY_ID[tid]["cat"],
                           "name": THREAT_BY_ID[tid]["name"]} for tid in threat_means),
                         key=lambda x: -x["score"])[:24]
    movers = sorted(({"id": tid, "delta": round(dsum[tid] / n, 2), "cat": THREAT_BY_ID[tid]["cat"],
                      "name": THREAT_BY_ID[tid]["name"]} for tid in dsum),
                    key=lambda x: -abs(x["delta"]))[:10]
    top_exposed = {}
    for tid in [t["id"] for t in top_threats] + [t["id"] for t in THREATS]:
        if tid in top_exposed:
            continue
        lst = sorted(exposed[tid], reverse=True)[:10]
        top_exposed[tid] = [{"score": sc, "kind": k, "id": i, "label": l} for sc, k, i, l in lst]
        if len(top_exposed) >= 60:
            break
    summary = {"as_of": as_of, "entities": len(rows), "cat_means": cat_means,
               "threat_means": threat_means, "top_threats": top_threats,
               "movers": movers, "top_exposed": top_exposed}
    CFG.upsert_json(s, "pestle.summary", summary)
    CFG.upsert_json(s, "pestle.refreshed_at", {"as_of": as_of})
    return summary


def get_summary(s):
    from app.features.domain import config_store as CFG
    return CFG.get_json(s, "pestle.summary", None)


def get_profile(s, entity_type, entity_id):
    from app.features.domain.registry_models import PestleProfile
    p = s.query(PestleProfile).filter_by(entity_type=entity_type, entity_id=entity_id).first()
    if not p:
        return None
    return {"entity_type": p.entity_type, "entity_id": p.entity_id, "label": p.label,
            "overall": p.overall, "cats": json.loads(p.cats_json or "{}"),
            "vector": json.loads(p.vector_json or "{}"), "top": json.loads(p.top_json or "[]"),
            "movers": json.loads(p.movers_json or "[]"), "refreshed_at": p.refreshed_at}


# ============ knowledge-graph builder ============
def _cat_node(c):
    return {"id": f"cat:{c}", "kind": "cat", "label": CATEGORIES[c]["name"], "cat": c, "score": 100}


def graph(s, focus_type="portfolio", focus_id=None, min_score=55, limit=8):
    """Build an interactive knowledge-graph payload (nodes + edges)."""
    summ = get_summary(s)
    if not summ:
        return {"nodes": [], "edges": [], "meta": {"empty": True}}
    nodes, edges, seen = {}, [], set()

    def add(node):
        nodes.setdefault(node["id"], node)

    def link(a, b, w):
        edges.append({"source": a, "target": b, "weight": round(w, 1)})

    def add_threat(tid, score):
        c = THREAT_BY_ID[tid]["cat"]
        add(_cat_node(c))
        add({"id": f"th:{tid}", "kind": "threat", "label": THREAT_BY_ID[tid]["name"],
             "cat": c, "score": score})
        link(f"th:{tid}", f"cat:{c}", 60)

    def add_exposed(tid, k):
        for ex in (summ["top_exposed"].get(tid, [])[:k]):
            if ex["score"] < min_score:
                continue
            nid = f"{ex['kind']}:{ex['id']}"
            add({"id": nid, "kind": ex["kind"], "label": ex["label"], "cat": None, "score": ex["score"]})
            link(nid, f"th:{tid}", ex["score"])

    if focus_type == "portfolio":
        for c in CATEGORIES:
            add(_cat_node(c))
        for t in summ["top_threats"][:max(6, limit + 4)]:
            add_threat(t["id"], t["score"]); add_exposed(t["id"], 3)
    elif focus_type == "category" and focus_id in CATEGORIES:
        add(_cat_node(focus_id))
        tm = summ["threat_means"]
        cat_threats = sorted((t for t in THREATS if t["cat"] == focus_id),
                             key=lambda t: -tm.get(t["id"], 0))[:15]
        for t in cat_threats:
            add_threat(t["id"], tm.get(t["id"], 0)); add_exposed(t["id"], 3)
    elif focus_type == "threat" and focus_id in THREAT_BY_ID:
        add_threat(focus_id, summ["threat_means"].get(focus_id, 0)); add_exposed(focus_id, 12)
    elif focus_type in ("vendor", "engagement") and focus_id:
        prof = get_profile(s, focus_type, focus_id)
        if prof:
            nid = f"{focus_type}:{focus_id}"
            add({"id": nid, "kind": focus_type, "label": prof["label"], "cat": None,
                 "score": prof["overall"] or 0})
            for t in prof["top"][:10]:
                add_threat(t["id"], t["score"]); link(nid, f"th:{t['id']}", t["score"])
    # degree
    deg = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for nid, nd in nodes.items():
        nd["degree"] = deg.get(nid, 0)
    return {"nodes": list(nodes.values()), "edges": edges,
            "meta": {"focus_type": focus_type, "focus_id": focus_id, "as_of": summ["as_of"],
                     "node_count": len(nodes), "edge_count": len(edges)}}
