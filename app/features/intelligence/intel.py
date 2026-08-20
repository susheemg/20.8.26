"""
Group C: the four intelligence engines (Vera/Mira/Matt/Isaac).

Deterministic-LOCAL analysers by default — runs with no API key, exactly like
the uploaded app's local_analyze fallback. When a provider key is present, the
same call points route through our tested provider abstraction + verdict parser
(improve-in-port), but the local path is always a complete, working analyser so
the app is fully functional offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.features.assessment.bro_engine import CONTRACT_TERMS


@dataclass(frozen=True)
class IntelOutput:
    engine: str
    score: Optional[float]
    band: Optional[str]
    narrative: str
    signals: tuple[str, ...] = ()


def _band(score: float) -> str:
    if score >= 75:
        return "STRONG"
    if score >= 55:
        return "ADEQUATE"
    if score >= 35:
        return "WEAK"
    return "DISTRESSED"


def vera_financial(ratios: dict) -> IntelOutput:
    """Vera — financial DD. Simple deterministic health score from ratios."""
    current = ratios.get("current_ratio", 1.0)
    debt_equity = ratios.get("debt_equity", 1.0)
    margin = ratios.get("net_margin", 0.05)
    score = max(0.0, min(100.0,
        40 * min(current / 2.0, 1.0)
        + 30 * max(0.0, 1 - debt_equity / 3.0)
        + 30 * min(max(margin, 0) / 0.20, 1.0)))
    band = _band(score)
    signals = []
    if current < 1.0:
        signals.append("current ratio below 1.0 — short-term liquidity risk")
    if debt_equity > 2.0:
        signals.append("high leverage")
    if margin < 0:
        signals.append("negative net margin")
    return IntelOutput("financial", round(score, 1), band,
                       f"Financial health {band} ({score:.0f}/100).", tuple(signals))


def mira_reputation(flags: dict) -> IntelOutput:
    """Mira — reputation & ESG. Screens adverse signals across pillars."""
    pillars = ["adverse_media", "regulatory", "litigation", "cyber", "esg"]
    hits = sum(1 for p in pillars if flags.get(p))
    score = max(0.0, 100.0 - hits * 20.0)
    band = _band(score)
    signals = tuple(f"{p} flag" for p in pillars if flags.get(p))
    return IntelOutput("reputation", round(score, 1), band,
                       f"Reputation {band}; {hits} pillar flag(s).", signals)


def matt_contract(tier: str) -> IntelOutput:
    """Matt — contracts. Returns the tiered minimum-terms checklist."""
    applicable = []
    for label, terms in CONTRACT_TERMS.items():
        if tier == "Tier 1":
            applicable.extend(terms)
        elif tier == "Tier 2" and not label.startswith("Tier 1"):
            applicable.extend(terms)
        elif tier == "Tier 3" and label.startswith("Tier 3"):
            applicable.extend(terms)
    return IntelOutput("contract", float(len(applicable)), tier,
                       f"{len(applicable)} minimum terms apply for {tier}.",
                       tuple(applicable))


def isaac_evidence(extracted_text: str) -> IntelOutput:
    """Isaac — evidence check. Light parse of assurance-report text.
    In the full pipeline this delegates to our Phase 5 ingestion/classification;
    here it produces a quick scope/validity read."""
    t = (extracted_text or "").lower()
    is_soc2 = "soc 2" in t or "soc2" in t or "isae 3402" in t
    type_ii = "type ii" in t or "type 2" in t
    exceptions = t.count("exception")
    score = (60 if is_soc2 else 30) + (25 if type_ii else 0) - min(exceptions * 5, 25)
    score = max(0.0, min(100.0, float(score)))
    signals = []
    if is_soc2:
        signals.append("recognised assurance standard detected")
    if type_ii:
        signals.append("Type II (operating effectiveness)")
    if exceptions:
        signals.append(f"{exceptions} exception(s) noted")
    return IntelOutput("evidence", round(score, 1), _band(score),
                       "Assurance evidence parsed.", tuple(signals))
