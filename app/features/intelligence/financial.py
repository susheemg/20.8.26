"""
Financial Due Diligence engine (deterministic) — ported from the uploaded
BRO platform JSX. Works offline on supplied/procurement-fed figures; the
authoritative web-research auto-fill activates only when a live LLM key is set.

Pipeline: figures -> 17 ratios -> Altman Z' -> 5 pillar scores -> overall band,
with qualitative flags adjusting viability/solvency, plus Sara consistency checks.
"""
from __future__ import annotations

from typing import Optional


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_div(a, b) -> Optional[float]:
    return (a / b) if (b not in (0, None)) else None


def compute_ratios(f: dict) -> dict:
    rev, cogs = _num(f.get("revenue")), _num(f.get("cogs"))
    gp = _num(f["grossProfit"]) if f.get("grossProfit") not in (None, "") else rev - cogs
    ebit, ebitda = _num(f.get("ebit")), _num(f.get("ebitda"))
    np_, interest = _num(f.get("netProfit")), _num(f.get("interest"))
    ca, cl = _num(f.get("currentAssets")), _num(f.get("currentLiabilities"))
    inv, cash = _num(f.get("inventory")), _num(f.get("cash"))
    ta, debt = _num(f.get("totalAssets")), _num(f.get("totalDebt"))
    eq, rec = _num(f.get("equity")), _num(f.get("receivables"))
    pay = _num(f.get("payables"))
    net_debt = _num(f["netDebt"]) if f.get("netDebt") not in (None, "") else debt - cash
    tl = _num(f["totalLiabilities"]) if f.get("totalLiabilities") not in (None, "") else ta - eq
    re = _num(f.get("retainedEarnings"))
    return {
        "currentRatio": _safe_div(ca, cl),
        "quickRatio": _safe_div(ca - inv, cl),
        "cashRatio": _safe_div(cash, cl),
        "debtToEquity": _safe_div(debt, eq),
        "debtRatio": _safe_div(tl, ta),
        "netDebtEbitda": _safe_div(net_debt, ebitda),
        "interestCover": _safe_div(ebit, interest),
        "equityRatio": _safe_div(eq, ta),
        "grossMargin": _safe_div(gp, rev),
        "ebitMargin": _safe_div(ebit, rev),
        "netMargin": _safe_div(np_, rev),
        "ebitdaMargin": _safe_div(ebitda, rev),
        "roa": _safe_div(np_, ta),
        "roe": _safe_div(np_, eq),
        "assetTurnover": _safe_div(rev, ta),
        "receivableDays": (rec / rev) * 365 if rev else None,
        "payableDays": (pay / cogs) * 365 if cogs else None,
        "_raw": {"rev": rev, "cogs": cogs, "gp": gp, "ebit": ebit, "ebitda": ebitda,
                 "np": np_, "interest": interest, "ca": ca, "cl": cl, "inv": inv,
                 "cash": cash, "ta": ta, "debt": debt, "eq": eq, "rec": rec,
                 "pay": pay, "netDebt": net_debt, "tl": tl, "re": re},
    }


def altman_z(r: dict) -> dict:
    x = r["_raw"]
    if not x["ta"]:
        return {"z": None, "zone": "insufficient"}
    X1 = (x["ca"] - x["cl"]) / x["ta"]
    X2 = x["re"] / x["ta"]
    X3 = x["ebit"] / x["ta"]
    X4 = (x["eq"] / x["tl"]) if x["tl"] else 0
    X5 = x["rev"] / x["ta"]
    z = 0.717 * X1 + 0.847 * X2 + 3.107 * X3 + 0.420 * X4 + 0.998 * X5
    zone = "safe" if z > 2.9 else "grey" if z >= 1.23 else "distress"
    return {"z": z, "zone": zone, "X1": X1, "X2": X2, "X3": X3, "X4": X4, "X5": X5}


def _band(v, lo, hi, invert=False) -> Optional[float]:
    if v is None:
        return None
    s = (hi - v) / (hi - lo) if invert else (v - lo) / (hi - lo)
    return max(0.0, min(1.0, s)) * 100


def _avg(arr) -> Optional[float]:
    vals = [x for x in arr if x is not None]
    return sum(vals) / len(vals) if vals else None


def pillar_scores(r: dict, z: dict, flags: dict) -> dict:
    liquidity = _avg([_band(r["currentRatio"], 0.8, 2.0),
                      _band(r["quickRatio"], 0.5, 1.5),
                      _band(r["cashRatio"], 0.1, 0.6)])
    solvency = _avg([_band(r["debtToEquity"], 2.5, 0.3, True),
                     _band(r["debtRatio"], 0.85, 0.35, True),
                     _band(r["netDebtEbitda"], 5.0, 0.5, True),
                     _band(r["interestCover"], 1.0, 8.0),
                     _band(r["equityRatio"], 0.15, 0.6)])
    profitability = _avg([_band(r["grossMargin"], 0.10, 0.60),
                          _band(r["ebitMargin"], 0.0, 0.20),
                          _band(r["netMargin"], -0.05, 0.15),
                          _band(r["roa"], 0.0, 0.12),
                          _band(r["roe"], 0.0, 0.20)])
    efficiency = _avg([_band(r["assetTurnover"], 0.3, 1.5),
                       _band(r["receivableDays"], 120, 30, True),
                       _band(r["payableDays"], 15, 75)])
    viability = 50.0 if z["z"] is None else (
        88.0 if z["zone"] == "safe" else 58.0 if z["zone"] == "grey" else 22.0)
    if flags.get("auditQualified"):
        viability -= 30
    if flags.get("goingConcern"):
        viability -= 40
    if flags.get("negativeEquity"):
        solvency = min(solvency if solvency is not None else 100, 12)
        viability -= 25
    if flags.get("filingsOnTime") is False:
        viability -= 10
    viability = max(0.0, min(100.0, viability))
    return {"liquidity": liquidity, "solvency": solvency, "profitability": profitability,
            "efficiency": efficiency, "viability": viability}


def overall_health(p: dict, flags: dict) -> dict:
    w = {"liquidity": 0.20, "solvency": 0.25, "profitability": 0.25,
         "efficiency": 0.10, "viability": 0.20}
    score, wsum = 0.0, 0.0
    for k, wt in w.items():
        if p.get(k) is not None:
            score += p[k] * wt
            wsum += wt
    overall = (score / wsum) if wsum else None
    if flags.get("goingConcern") and overall is not None:
        overall = min(overall, 44)
    banding = ("—" if overall is None else "Strong" if overall >= 75 else
               "Adequate" if overall >= 60 else "Watch" if overall >= 45 else "Distressed")
    return {"overall": overall, "banding": banding}


def sara_fin_checks(f: dict, r: dict) -> list[dict]:
    out, x = [], r["_raw"]
    if f.get("grossProfit") not in (None, "") and x["rev"] and \
            abs((x["rev"] - x["cogs"]) - x["gp"]) > max(1, x["rev"] * 0.02):
        out.append({"tone": "warn", "text": "Gross profit ≠ Revenue − COGS. Reconcile before scoring."})
    if x["eq"] < 0 and not f.get("negativeEquity"):
        out.append({"tone": "crit", "text": "Equity is negative but the negative-equity flag is off."})
    if x["np"] > x["rev"] and x["rev"] > 0:
        out.append({"tone": "crit", "text": "Net profit exceeds revenue — implausible. Check inputs."})
    if x["ebit"] and x["ebitda"] and x["ebitda"] < x["ebit"]:
        out.append({"tone": "warn", "text": "EBITDA below EBIT — D&A should make EBITDA ≥ EBIT."})
    if r["interestCover"] is not None and r["interestCover"] < 1 and x["interest"] > 0:
        out.append({"tone": "crit", "text": "Interest cover below 1.0× — going-concern signal."})
    if r["netDebtEbitda"] is not None and r["netDebtEbitda"] > 5:
        out.append({"tone": "warn", "text": "Net debt / EBITDA above 5× — elevated leverage."})
    return out


def assess_financials(figures: dict, flags: Optional[dict] = None) -> dict:
    """Full deterministic FDD pass."""
    flags = flags or {}
    r = compute_ratios(figures)
    z = altman_z(r)
    p = pillar_scores(r, z, flags)
    o = overall_health(p, flags)
    ratios = {k: v for k, v in r.items() if k != "_raw"}
    return {"ratios": ratios, "altman": {"z": z["z"], "zone": z["zone"]},
            "pillars": p, "overall": o["overall"], "banding": o["banding"],
            "flags": flags, "sara_checks": sara_fin_checks(figures, r)}


# Sector median ratios for peer benchmarking (illustrative defaults, from JSX)
SECTOR_MEDIANS = {
    "tech":    {"grossMargin": 0.72, "netMargin": 0.10, "currentRatio": 1.80, "debtToEquity": 0.50, "roe": 0.14, "interestCover": 8.0, "netDebtEbitda": 1.0},
    "mfg":     {"grossMargin": 0.32, "netMargin": 0.06, "currentRatio": 1.60, "debtToEquity": 0.90, "roe": 0.11, "interestCover": 5.0, "netDebtEbitda": 2.2},
    "retail":  {"grossMargin": 0.38, "netMargin": 0.04, "currentRatio": 1.20, "debtToEquity": 1.10, "roe": 0.13, "interestCover": 4.0, "netDebtEbitda": 2.5},
    "finserv": {"grossMargin": 0.55, "netMargin": 0.18, "currentRatio": 1.10, "debtToEquity": 2.50, "roe": 0.11, "interestCover": 3.0, "netDebtEbitda": 3.0},
    "health":  {"grossMargin": 0.45, "netMargin": 0.08, "currentRatio": 1.70, "debtToEquity": 0.70, "roe": 0.12, "interestCover": 6.0, "netDebtEbitda": 1.8},
    "prof":    {"grossMargin": 0.40, "netMargin": 0.12, "currentRatio": 1.50, "debtToEquity": 0.40, "roe": 0.20, "interestCover": 10.0, "netDebtEbitda": 0.6},
    "other":   {"grossMargin": 0.40, "netMargin": 0.08, "currentRatio": 1.50, "debtToEquity": 0.80, "roe": 0.12, "interestCover": 5.0, "netDebtEbitda": 2.0},
}

SECTORS = [
    {"id": "tech", "label": "Technology / SaaS"},
    {"id": "mfg", "label": "Manufacturing / Industrial"},
    {"id": "retail", "label": "Retail / Consumer"},
    {"id": "finserv", "label": "Financial services"},
    {"id": "health", "label": "Healthcare / Pharma"},
    {"id": "prof", "label": "Professional services"},
    {"id": "other", "label": "Other"},
]


def peer_benchmark(ratios: dict, sector: str = "other") -> list[dict]:
    """Compare computed ratios to sector medians. 'better' logic matches the JSX:
    for debt ratios lower is better; otherwise higher is better."""
    med = SECTOR_MEDIANS.get(sector, SECTOR_MEDIANS["other"])
    rows = []
    labels = {"grossMargin": ("Gross margin", "%"), "netMargin": ("Net margin", "%"),
              "currentRatio": ("Current ratio", "x"), "debtToEquity": ("Debt / equity", "x"),
              "roe": ("Return on equity", "%"), "interestCover": ("Interest cover", "x"),
              "netDebtEbitda": ("Net debt / EBITDA", "x")}
    for k, (label, unit) in labels.items():
        v = ratios.get(k)
        m = med.get(k)
        if v is None:
            verdict = "—"
        elif k in ("debtToEquity", "netDebtEbitda"):
            verdict = "favourable" if v < m else "below peers"
        else:
            verdict = "favourable" if v > m else "below peers"
        rows.append({"metric": label, "unit": unit, "company": v, "median": m, "verdict": verdict})
    return rows
