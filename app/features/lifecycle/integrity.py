"""Phase 1 — Data integrity & completion engine (point-in-time, no time-series).
Runs over the current record set: completeness scoring, LEI/format validation,
cross-field contradictions, stale-record detection, orphan detection and
duplicate/alias clustering. All checks are deterministic; AI enrichment is layered
on top via the endpoints (gated)."""
from __future__ import annotations
import re
from datetime import datetime, timezone

from sqlalchemy import select

# Risk-weighted completeness: (field, weight, label). Higher weight = matters more.
COMPLETENESS_FIELDS = [
    ("legal_name", 3, "Legal name"),
    ("lei", 3, "LEI"),
    ("registration_number", 2, "Registration number"),
    ("incorporation_country", 2, "Incorporation country"),
    ("hq_country", 2, "HQ country"),
    ("ultimate_parent", 2, "Ultimate parent"),
    ("legal_form", 1, "Legal form"),
    ("website", 1, "Website"),
    ("listing_status", 1, "Listing status"),
    ("status", 1, "Lifecycle status"),
]

_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "plc", "corp",
             "corporation", "co", "company", "gmbh", "sa", "ag", "sarl", "bv",
             "pte", "pty", "holdings", "group", "technologies", "technology",
             "services", "solutions", "international", "global", "the"}


def lei_valid(lei: str) -> bool:
    """ISO 17442 LEI = 20 alphanumerics validated by ISO 7064 MOD 97-10."""
    if not lei:
        return False
    s = lei.strip().upper()
    if len(s) != 20 or not re.fullmatch(r"[A-Z0-9]{20}", s):
        return False
    num = "".join(str(int(c, 36)) for c in s)  # A->10 ... Z->35, digits as-is
    try:
        return int(num) % 97 == 1
    except ValueError:
        return False


def norm_name(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    toks = [t for t in s.split() if t and t not in _SUFFIXES]
    return " ".join(toks)


def _name_tokens(s: str):
    return set(norm_name(s).split())


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def completeness(v) -> tuple[int, list[str]]:
    total = sum(w for _, w, _ in COMPLETENESS_FIELDS)
    got, missing = 0, []
    for field, w, label in COMPLETENESS_FIELDS:
        val = getattr(v, field, None)
        if val not in (None, "", "—"):
            got += w
        else:
            missing.append(label)
    # criticality weights missing data more heavily
    score = round(got / total * 100)
    if getattr(v, "is_critical", False) and missing:
        score = max(0, score - 10)
    return score, missing


def _days_since(dt) -> int | None:
    if not dt:
        return None
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


# inherent/residual band severity ordering (higher = worse)
_BAND_RANK = {"LOW": 1, "MODERATE": 2, "MEDIUM": 2, "ELEVATED": 3, "HIGH": 4, "CRITICAL": 5}


def run_sweep(s, limit: int | None = None, vendor_ids: list[str] | None = None) -> dict:
    from app.features.domain.registry_models import (VendorRecord, EngagementRecord,
                                  AssessmentRecord, FindingRecord)
    vendors = s.scalars(select(VendorRecord)).all()
    if vendor_ids:
        vendors = [v for v in vendors if v.vendor_id in vendor_ids]
    if limit:
        vendors = vendors[:limit]
    engs = s.scalars(select(EngagementRecord)).all()
    asmts = s.scalars(select(AssessmentRecord)).all()
    finds = s.scalars(select(FindingRecord)).all()

    eng_by_vendor = {}
    for e in engs:
        eng_by_vendor.setdefault(e.vendor_id, []).append(e)
    asm_by_vendor = {}
    for a in asmts:
        asm_by_vendor.setdefault(a.vendor_id, []).append(a)
    eng_ids = {e.engagement_id for e in engs}
    vendor_ids_all = {v.vendor_id for v in vendors}

    issues = []
    iid = 0

    def add(typ, sev, vendor, vid, msg, field=None, fix=None, fix_kind=None, extra=None):
        nonlocal iid
        iid += 1
        issues.append({"id": f"DQ-{iid:04d}", "type": typ, "severity": sev,
                       "vendor": vendor, "vendor_id": vid, "message": msg,
                       "field": field, "suggested_fix": fix, "fix_kind": fix_kind,
                       **(extra or {})})

    comp_scores = []
    for v in vendors:
        score, missing = completeness(v)
        comp_scores.append(score)
        # completeness gaps (one issue per vendor, listing missing weighted fields)
        if missing:
            sev = "high" if (v.is_critical and score < 70) else ("medium" if score < 70 else "low")
            add("completeness", sev, v.legal_name, v.vendor_id,
                f"{len(missing)} field(s) missing ({score}% complete): " + ", ".join(missing[:6]),
                extra={"missing": missing, "score": score})
        # LEI validation
        if v.lei and not lei_valid(v.lei):
            add("validation", "medium", v.legal_name, v.vendor_id,
                f"LEI '{v.lei}' fails ISO 17442 format/checksum.", field="lei",
                fix_kind="clear", fix="")
        # contradictions
        v_engs = eng_by_vendor.get(v.vendor_id, [])
        v_asms = asm_by_vendor.get(v.vendor_id, [])
        if v.is_critical and not v_asms:
            add("contradiction", "high", v.legal_name, v.vendor_id,
                "Marked critical but has no assessment on record.")
        if v.is_critical and getattr(v, "tier", "") in ("Tier 3", "Tier 4"):
            add("contradiction", "medium", v.legal_name, v.vendor_id,
                f"Marked critical but tiered '{v.tier}'.", field="tier",
                fix_kind="set", fix="Tier 1")
        if getattr(v, "status", "") == "Active" and not v_engs:
            add("contradiction", "low", v.legal_name, v.vendor_id,
                "Active vendor with no engagement linked.")
        # residual better than inherent without rationale
        for a in v_asms:
            ib = _BAND_RANK.get(str(getattr(a, "inherent_band", "") or "").upper(), 0)
            rb = _BAND_RANK.get(str(getattr(a, "residual_band", "") or "").upper(), 0)
            if ib and rb and rb < ib - 1:
                add("contradiction", "medium", v.legal_name, v.vendor_id,
                    f"Assessment {a.assessment_id}: residual ({a.residual_band}) far below "
                    f"inherent ({a.inherent_band}) — verify rationale.")
                break
        # stale
        if not v_asms and getattr(v, "status", "") == "Active":
            add("stale", "medium" if v.is_critical else "low", v.legal_name, v.vendor_id,
                "Active vendor never assessed.")
        else:
            newest = None
            for a in v_asms:
                d = _days_since(getattr(a, "created_at", None))
                if d is not None and (newest is None or d < newest):
                    newest = d
            if newest is not None and newest > 365:
                add("stale", "medium" if v.is_critical else "low", v.legal_name, v.vendor_id,
                    f"Last assessment {newest} days ago — overdue for refresh.")

    # orphans
    for e in engs:
        if e.vendor_id and e.vendor_id not in vendor_ids_all:
            add("orphan", "high", e.title or e.engagement_id, e.vendor_id,
                f"Engagement {e.engagement_id} references a vendor not in the register.")
    for f in finds:
        if f.vendor_id and f.vendor_id not in vendor_ids_all:
            add("orphan", "high", f.title or f.finding_id, f.vendor_id,
                f"Finding {f.finding_id} references a vendor not in the register.")
    for a in asmts:
        if a.engagement_id and a.engagement_id not in eng_ids:
            add("orphan", "medium", a.assessment_id, a.vendor_id,
                f"Assessment {a.assessment_id} references a missing engagement.")

    # duplicate / alias clusters
    seen, clusters = set(), []
    toks = {v.vendor_id: _name_tokens(v.legal_name) for v in vendors}
    vlist = list(vendors)
    for i, v in enumerate(vlist):
        if v.vendor_id in seen:
            continue
        group = [v]
        for w in vlist[i + 1:]:
            if w.vendor_id in seen:
                continue
            n1, n2 = norm_name(v.legal_name), norm_name(w.legal_name)
            if n1 and (n1 == n2 or _jaccard(toks[v.vendor_id], toks[w.vendor_id]) >= 0.8):
                group.append(w)
                seen.add(w.vendor_id)
        if len(group) > 1:
            seen.add(v.vendor_id)
            clusters.append([{"vendor_id": g.vendor_id, "legal_name": g.legal_name,
                              "is_critical": g.is_critical, "engagements": len(eng_by_vendor.get(g.vendor_id, []))}
                             for g in group])
    for cl in clusters:
        names = ", ".join(g["legal_name"] for g in cl)
        add("duplicate", "medium", cl[0]["legal_name"], cl[0]["vendor_id"],
            f"Possible duplicate/alias cluster: {names}", fix_kind="merge",
            extra={"cluster": cl})

    by_type = {}
    for it in issues:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    by_sev = {}
    for it in issues:
        by_sev[it["severity"]] = by_sev.get(it["severity"], 0) + 1

    avg_comp = round(sum(comp_scores) / len(comp_scores)) if comp_scores else 100
    # overall data-health: completeness minus a penalty for open integrity issues
    penalty = min(40, by_sev.get("high", 0) * 4 + by_sev.get("medium", 0) * 2 + by_sev.get("low", 0))
    health = max(0, min(100, avg_comp - penalty))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vendors_checked": len(vendors),
        "health": {"overall": health, "completeness": avg_comp,
                   "by_type": by_type, "by_severity": by_sev, "issue_count": len(issues)},
        "issues": issues,
        "duplicate_clusters": clusters,
    }


# Expected-but-missing evidence by vendor profile (deterministic baseline for the chaser)
def expected_evidence(v) -> list[str]:
    want = []
    if getattr(v, "is_critical", False):
        want += ["SOC 2 Type II report", "Business continuity / DR test evidence",
                 "Information-security policy", "Latest financial statements"]
    else:
        want += ["Security questionnaire", "Insurance certificate"]
    return want
