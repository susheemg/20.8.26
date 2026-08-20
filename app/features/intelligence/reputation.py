"""
Reputation & ESG engine (deterministic) — ported from the uploaded BRO platform.

Seven pillars: Regulatory, Litigation, Cyber, ESG-Environmental, ESG-Social,
ESG-Governance, Media. Each scored 0-100 (100 = clean). Works offline by scoring
operator-supplied adverse events; the authoritative web-research auto-fill (Mira
+ Rex) activates only when a live LLM key is set.

Scoring model: each pillar starts clean (100) and is reduced by the severity of
recorded adverse events in that pillar. Overall = weighted blend, with a
customer-facing (brand transfer) multiplier amplifying media/conduct exposure.
"""
from __future__ import annotations

from typing import Optional

PILLARS = ["regulatory", "litigation", "cyber", "esg_environmental",
           "esg_social", "esg_governance", "media"]

PILLAR_LABELS = {
    "regulatory": "Regulatory & Enforcement",
    "litigation": "Litigation & Disputes",
    "cyber": "Cyber & Data Breach",
    "esg_environmental": "ESG — Environmental",
    "esg_social": "ESG — Social",
    "esg_governance": "ESG — Governance",
    "media": "Adverse Media & Conduct",
}

# weights used for the overall reputation score (sum = 1.0)
PILLAR_WEIGHTS = {
    "regulatory": 0.22, "litigation": 0.15, "cyber": 0.18,
    "esg_environmental": 0.10, "esg_social": 0.10,
    "esg_governance": 0.13, "media": 0.12,
}

# severity -> points deducted from a pillar's clean 100
_SEVERITY_HIT = {"critical": 55, "high": 35, "medium": 18, "low": 7}


def _verdict(score: Optional[float]) -> str:
    if score is None:
        return "—"
    if score >= 80:
        return "Clean"
    if score >= 65:
        return "Minor concerns"
    if score >= 45:
        return "Elevated concerns"
    return "Serious concerns"


def assess_reputation(events: Optional[list[dict]] = None,
                      customer_facing: bool = False) -> dict:
    """
    events: list of {pillar, severity (critical/high/medium/low), title, date, source}
    Returns per-pillar scores (0-100), an adverse-event timeline, and an overall.
    """
    events = events or []
    # start every pillar clean
    pillar_scores = {p: 100.0 for p in PILLARS}
    pillar_findings: dict[str, list] = {p: [] for p in PILLARS}

    for ev in events:
        p = ev.get("pillar")
        if p not in pillar_scores:
            continue
        sev = (ev.get("severity") or "medium").lower()
        hit = _SEVERITY_HIT.get(sev, 18)
        pillar_scores[p] = max(0.0, pillar_scores[p] - hit)
        pillar_findings[p].append({
            "title": ev.get("title", "(adverse event)"),
            "severity": sev, "date": ev.get("date"), "source": ev.get("source"),
        })

    # customer-facing engagements carry brand-transfer risk: amplify media &
    # conduct exposure (deduct a little more where those pillars are already hit)
    if customer_facing:
        for p in ("media", "esg_social", "esg_governance"):
            if pillar_scores[p] < 100:
                pillar_scores[p] = max(0.0, pillar_scores[p] - 8)

    pillars_out = []
    for p in PILLARS:
        sc = round(pillar_scores[p], 1)
        pillars_out.append({
            "pillar": p, "label": PILLAR_LABELS[p], "score": sc,
            "verdict": _verdict(sc), "findings": pillar_findings[p],
        })

    overall = round(sum(pillar_scores[p] * PILLAR_WEIGHTS[p] for p in PILLARS), 1)

    # timeline: events sorted by date (None last)
    timeline = sorted(
        [{"date": e.get("date"), "pillar": e.get("pillar"),
          "severity": (e.get("severity") or "medium").lower(),
          "title": e.get("title"), "source": e.get("source")} for e in events],
        key=lambda x: (x["date"] is None, x["date"] or ""),
    )

    return {
        "pillars": pillars_out,
        "overall": overall,
        "verdict": _verdict(overall),
        "customer_facing": customer_facing,
        "event_count": len(events),
        "timeline": timeline,
    }
