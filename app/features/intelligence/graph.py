"""Phase 2 — Entity / ownership graph, concentration & contagion (point-in-time).
Builds a structural graph over the current estate:
  • common-ownership clusters (vendors sharing an ultimate parent or vendor group),
  • shared fourth parties (sub-providers serving many vendors → single points of failure),
  • contagion ("if this entity fails, who falls over").
No history required."""
from __future__ import annotations
from sqlalchemy import select


def _norm(s):
    return (s or "").strip().lower()


def build_graph(s) -> dict:
    from app.features.domain.registry_models import (VendorRecord, EngagementRecord, VendorGroup,
                                  FourthPartyRecord, FourthPartyVendor)
    vendors = s.scalars(select(VendorRecord)).all()
    vmap = {v.vendor_id: v for v in vendors}
    total = len(vendors) or 1
    groups = {g.group_id: g for g in s.scalars(select(VendorGroup)).all()}
    engs = s.scalars(select(EngagementRecord)).all()
    eng_by_vendor = {}
    for e in engs:
        eng_by_vendor.setdefault(e.vendor_id, []).append(e)
    fps = {f.fourth_party_id: f for f in s.scalars(select(FourthPartyRecord)).all()}
    links = s.scalars(select(FourthPartyVendor)).all()

    # ---- common-ownership clusters ----
    by_owner = {}  # key -> {"label":, "kind":, "vendors":[]}
    for v in vendors:
        key = None; label = None; kind = None
        if v.ultimate_parent:
            key = "UP:" + _norm(v.ultimate_parent); label = v.ultimate_parent; kind = "ultimate parent"
        elif v.group_id:
            g = groups.get(v.group_id)
            label = (g.name if g else v.group_id); key = "GR:" + v.group_id; kind = "vendor group"
        if not key:
            continue
        slot = by_owner.setdefault(key, {"label": label, "kind": kind, "vendors": []})
        slot["vendors"].append({"vendor_id": v.vendor_id, "legal_name": v.legal_name,
                                "is_critical": v.is_critical})
    ownership = [{"owner": o["label"], "kind": o["kind"],
                  "vendor_count": len(o["vendors"]),
                  "critical_count": sum(1 for x in o["vendors"] if x["is_critical"]),
                  "vendors": o["vendors"]}
                 for o in by_owner.values() if len(o["vendors"]) > 1]
    ownership.sort(key=lambda x: x["vendor_count"], reverse=True)

    # ---- shared fourth parties ----
    fp_vendors = {}
    for ln in links:
        fp_vendors.setdefault(ln.fourth_party_id, []).append(ln.vendor_id)
    shared = []
    for fid, vids in fp_vendors.items():
        if len(vids) <= 1:
            continue
        f = fps.get(fid)
        crit = sum(1 for vid in vids if vmap.get(vid) and vmap[vid].is_critical)
        reach = round(len(vids) / total * 100)
        shared.append({"fourth_party_id": fid,
                       "legal_name": f.legal_name if f else fid,
                       "service": (f.service_provided if f else None),
                       "hq_country": (f.hq_country if f else None),
                       "vendor_count": len(vids), "critical_count": crit,
                       "reach_pct": reach,
                       "spof": len(vids) >= max(10, total * 0.15)})
    shared.sort(key=lambda x: x["vendor_count"], reverse=True)

    stats = {
        "vendors": len(vendors),
        "multi_vendor_owners": len(ownership),
        "shared_fourth_parties": len(shared),
        "max_fanout": shared[0]["vendor_count"] if shared else 0,
        "max_fanout_pct": shared[0]["reach_pct"] if shared else 0,
        "spof_count": sum(1 for x in shared if x["spof"]),
    }
    return {"ownership_clusters": ownership, "shared_fourth_parties": shared, "stats": stats}


def contagion(s, node_type: str, node_id: str) -> dict:
    """If this entity degrades, which vendors and engagements are exposed?"""
    from app.features.domain.registry_models import (VendorRecord, EngagementRecord, VendorGroup,
                                  FourthPartyRecord, FourthPartyVendor)
    vmap = {v.vendor_id: v for v in s.scalars(select(VendorRecord)).all()}
    engs = s.scalars(select(EngagementRecord)).all()
    eng_by_vendor = {}
    for e in engs:
        eng_by_vendor.setdefault(e.vendor_id, []).append(e)

    affected = []  # vendor_ids
    label = node_id
    if node_type == "fourth_party":
        f = s.scalars(select(FourthPartyRecord).where(
            FourthPartyRecord.fourth_party_id == node_id)).first()
        label = f.legal_name if f else node_id
        affected = [ln.vendor_id for ln in s.scalars(select(FourthPartyVendor).where(
            FourthPartyVendor.fourth_party_id == node_id)).all()]
    elif node_type == "owner":
        # node_id is the owner label; match ultimate_parent or group name
        g = s.scalars(select(VendorGroup).where(VendorGroup.name == node_id)).first()
        gid = g.group_id if g else None
        affected = [v.vendor_id for v in vmap.values()
                    if _norm(v.ultimate_parent) == _norm(node_id)
                    or (gid and v.group_id == gid)]
    elif node_type == "vendor":
        affected = [node_id]
        label = vmap[node_id].legal_name if node_id in vmap else node_id

    vendors_out, eng_count, bus = [], 0, set()
    for vid in dict.fromkeys(affected):
        v = vmap.get(vid)
        if not v:
            continue
        ve = eng_by_vendor.get(vid, [])
        eng_count += len(ve)
        for e in ve:
            if getattr(e, "business_unit", None):
                bus.add(e.business_unit)
        vendors_out.append({"vendor_id": vid, "legal_name": v.legal_name,
                            "is_critical": v.is_critical, "engagements": len(ve)})
    vendors_out.sort(key=lambda x: (not x["is_critical"], -x["engagements"]))
    return {"node_type": node_type, "node_id": node_id, "label": label,
            "affected_vendors": vendors_out, "vendor_count": len(vendors_out),
            "engagement_count": eng_count, "critical_count": sum(1 for x in vendors_out if x["is_critical"]),
            "business_units": sorted(bus)}


def network(s, max_nodes: int = 500) -> dict:
    """Node-link graph over the live estate for the interactive brain map:
    vendors, shared fourth parties, common-ownership clusters and business units.
    Read-only; built straight from the database each call."""
    from app.features.domain.registry_models import (VendorRecord, EngagementRecord, VendorGroup,
                                  FourthPartyRecord, FourthPartyVendor)
    vendors = s.scalars(select(VendorRecord)).all()
    groups = {g.group_id: g for g in s.scalars(select(VendorGroup)).all()}
    engs = s.scalars(select(EngagementRecord)).all()
    fps = {f.fourth_party_id: f for f in s.scalars(select(FourthPartyRecord)).all()}
    links_fp = s.scalars(select(FourthPartyVendor)).all()

    nodes, links = [], []
    seen = set()

    def add_node(nid, ntype, label, **meta):
        if nid in seen or len(nodes) >= max_nodes:
            return False
        seen.add(nid)
        nodes.append({"id": nid, "type": ntype, "label": label, **meta})
        return True

    eng_by_vendor = {}
    for e in engs:
        eng_by_vendor.setdefault(e.vendor_id, []).append(e)

    def _d(x):
        x = (x or "").strip()
        return x[:10] if len(x) >= 10 and x[:4].isdigit() else None

    # temporal signal: a vendor "arrives" with its earliest engagement start_date
    v_since = {}
    for vid, es in eng_by_vendor.items():
        ds = sorted(d for d in (_d(e.start_date) for e in es) if d)
        if ds:
            v_since[vid] = ds[0]

    for v in vendors:
        add_node("V:" + v.vendor_id, "vendor", v.legal_name,
                 vendor_id=v.vendor_id, critical=bool(v.is_critical),
                 country=getattr(v, "hq_country", None),
                 engagements=len(eng_by_vendor.get(v.vendor_id, [])),
                 since=v_since.get(v.vendor_id))

    # fourth parties + links (spof flag mirrors build_graph threshold)
    total = len(vendors) or 1
    fp_vendors = {}
    for ln in links_fp:
        fp_vendors.setdefault(ln.fourth_party_id, []).append(ln.vendor_id)
    for fid, vids in fp_vendors.items():
        f = fps.get(fid)
        fsince = sorted(d for d in (v_since.get(v) for v in vids) if d)
        add_node("F:" + fid, "fourth_party", (f.legal_name if f else fid),
                 fourth_party_id=fid, service=(f.service_provided if f else None),
                 spof=len(vids) >= max(10, total * 0.15), shared=len(vids) > 1,
                 since=(fsince[0] if fsince else None))
        for vid in vids:
            if ("V:" + vid) in seen and ("F:" + fid) in seen:
                links.append({"s": "F:" + fid, "t": "V:" + vid, "k": "supplies",
                              "since": v_since.get(vid)})

    # ownership clusters (only multi-vendor owners, mirroring build_graph)
    by_owner = {}
    for v in vendors:
        key = None; label = None
        if v.ultimate_parent:
            key = "UP:" + _norm(v.ultimate_parent); label = v.ultimate_parent
        elif v.group_id:
            g = groups.get(v.group_id)
            key = "GR:" + v.group_id; label = (g.name if g else v.group_id)
        if key:
            by_owner.setdefault(key, {"label": label, "vendors": []})["vendors"].append(v.vendor_id)
    for key, o in by_owner.items():
        if len(o["vendors"]) <= 1:
            continue
        osince = sorted(d for d in (v_since.get(v) for v in o["vendors"]) if d)
        add_node("O:" + key, "owner", o["label"], owner=o["label"],
                 since=(osince[0] if osince else None))
        for vid in o["vendors"]:
            if ("V:" + vid) in seen and ("O:" + key) in seen:
                links.append({"s": "O:" + key, "t": "V:" + vid, "k": "owns",
                              "since": v_since.get(vid)})

    # business units (from engagements)
    bu_vendors = {}
    bu_link_since = {}
    for e in engs:
        if e.business_unit:
            bu = e.business_unit.strip()
            bu_vendors.setdefault(bu, set()).add(e.vendor_id)
            d = _d(e.start_date)
            if d:
                k = (bu, e.vendor_id)
                if k not in bu_link_since or d < bu_link_since[k]:
                    bu_link_since[k] = d
    for bu, vids in bu_vendors.items():
        bsince = sorted(d for d in (bu_link_since.get((bu, v)) for v in vids) if d)
        add_node("B:" + _norm(bu), "bu", bu, since=(bsince[0] if bsince else None))
        for vid in vids:
            if ("V:" + vid) in seen and ("B:" + _norm(bu)) in seen:
                links.append({"s": "B:" + _norm(bu), "t": "V:" + vid, "k": "consumes",
                              "since": bu_link_since.get((bu, vid))})

    all_dates = sorted(d for d in ([n.get("since") for n in nodes] +
                                   [l.get("since") for l in links]) if d)
    return {"nodes": nodes, "links": links,
            "timeline": {"min": all_dates[0], "max": all_dates[-1]} if all_dates else None,
            "counts": {"vendors": len(vendors),
                       "fourth_parties": len(fp_vendors),
                       "owners": sum(1 for o in by_owner.values() if len(o["vendors"]) > 1),
                       "business_units": len(bu_vendors),
                       "links": len(links)},
            "truncated": len(nodes) >= max_nodes}
