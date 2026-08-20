"""
BRO Risk Oracle — TPRM domain engine
Inherent scoring, residual scoring, tiering, routing, decisions.
Faithful to the Supplier Risk Assessment Methodology v2.0.
"""
import hashlib
import json

# ─── IRQ questions ──────────────────────────────────────────────────────────
IRQ_QUESTIONS = [
    {"id": "Q1", "text": "Sanctions / regulatory exposure?", "type": "yesno"},
    {"id": "Q2", "text": "Service criticality", "type": "select",
     "options": ["Standard", "Important", "Mission-critical"]},
    {"id": "Q3", "text": "Data types in scope", "type": "multi",
     "options": ["None", "Personal", "Customer/Client", "Confidential", "Restricted",
                 "Payment Card", "Health", "Special Category Personal"]},
    {"id": "Q4", "text": "Volume of records", "type": "select",
     "options": ["<10,000", "10,000–100,000", "100,000–1,000,000", ">1,000,000"]},
    {"id": "Q5", "text": "Cross-border data transfer?", "type": "yesno"},
    {"id": "Q6", "text": "Network / system connectivity?", "type": "yesno"},
    {"id": "Q7", "text": "Physical site access?", "type": "yesno"},
    {"id": "Q8", "text": "Substitutability", "type": "select",
     "options": ["Easy", "Difficult", "Sole source"]},
    {"id": "Q9", "text": "Customer-facing / brand exposure?", "type": "yesno"},
    {"id": "Q10", "text": "Supports a regulated process?", "type": "yesno"},
    {"id": "Q11", "text": "Specific regulatory regimes (free text)", "type": "text"},
    {"id": "Q12", "text": "AI / automated decision-making in scope?", "type": "yesno"},
]

DOMAIN_NAMES = {
    "infosec": "Information Security", "privacy": "Privacy & Data",
    "resilience": "Operational Resilience", "compliance": "Compliance",
    "physical": "Physical Security", "org": "Organisational",
    "reputation": "Reputation", "esg": "ESG",
}

DDQ_DOMAINS = [
    {"id": "infosec", "name": "Information Security", "questions": [
        {"id": "IS1", "text": "Access control & MFA", "critical": True},
        {"id": "IS2", "text": "Encryption at rest & in transit", "critical": True},
        {"id": "IS3", "text": "Vulnerability & patch management", "critical": False},
        {"id": "IS4", "text": "Security monitoring & incident response", "critical": True},
    ]},
    {"id": "privacy", "name": "Privacy & Data Protection", "questions": [
        {"id": "PR1", "text": "Lawful basis & DPA in place", "critical": True},
        {"id": "PR2", "text": "Data retention & deletion", "critical": False},
        {"id": "PR3", "text": "Cross-border transfer safeguards", "critical": True},
    ]},
    {"id": "resilience", "name": "Operational Resilience", "questions": [
        {"id": "OR1", "text": "Business continuity & DR plan", "critical": True},
        {"id": "OR2", "text": "Exit / transition plan", "critical": False},
        {"id": "OR3", "text": "Sub-processor governance", "critical": False},
    ]},
    {"id": "compliance", "name": "Compliance", "questions": [
        {"id": "CO1", "text": "Regulatory compliance attestations", "critical": True},
        {"id": "CO2", "text": "Anti-bribery & corruption", "critical": False},
        {"id": "CO3", "text": "Modern slavery / ethical sourcing", "critical": False},
    ]},
    {"id": "physical", "name": "Physical Security", "questions": [
        {"id": "PH1", "text": "Facility access controls", "critical": False},
    ]},
    {"id": "reputation", "name": "Reputation", "questions": [
        {"id": "RE1", "text": "Adverse media / litigation history", "critical": False},
    ]},
]

DDQ_RESPONSES = ["COMPLIANT", "PARTIAL", "MARGINAL", "N/A"]


def compute_tier(irq):
    data = irq.get("Q3", []) or []
    if isinstance(data, str):
        data = [data]
    if any(d in ["Restricted", "Payment Card", "Health", "Special Category Personal"] for d in data):
        return "Tier 1"
    if irq.get("Q2") == "Mission-critical" or irq.get("Q8") == "Sole source":
        return "Tier 1"
    if irq.get("Q2") == "Important" or "Personal" in data or "Customer/Client" in data:
        return "Tier 2"
    return "Tier 3"


def compute_inherent(irq):
    data = irq.get("Q3", []) or []
    if isinstance(data, str):
        data = [data]
    domains = {}

    s = 0
    if any(d in ["Restricted", "Confidential", "Payment Card", "Health", "Special Category Personal"] for d in data):
        s += 2
    elif "Personal" in data:
        s += 1
    if irq.get("Q6") == "Yes":
        s += 1
    if irq.get("Q7") == "Yes":
        s += 1
    domains["infosec"] = min(4, s)

    s = 0
    if any(d in ["Special Category Personal", "Health", "Payment Card"] for d in data):
        s += 2
    elif any(d in ["Personal", "Customer/Client"] for d in data):
        s += 1
    if irq.get("Q5") == "Yes":
        s += 1
    if irq.get("Q4") in [">1,000,000", "100,000–1,000,000"]:
        s += 1
    domains["privacy"] = min(4, s)

    s = 0
    if irq.get("Q2") == "Mission-critical":
        s += 2
    elif irq.get("Q2") == "Important":
        s += 1
    if irq.get("Q8") == "Sole source":
        s += 2
    elif irq.get("Q8") == "Difficult":
        s += 1
    if irq.get("Q10") == "Yes":
        s += 1
    domains["resilience"] = min(4, s)

    s = 0
    if irq.get("Q1") == "Yes":
        s += 3
    if (irq.get("Q11") or "").strip():
        s += 1
    if irq.get("Q12") == "Yes":
        s += 1
    domains["compliance"] = min(4, s)

    s = 0
    if irq.get("Q7") == "Yes":
        s += 2
    if irq.get("Q6") == "Yes":
        s += 1
    domains["physical"] = min(4, s)

    s = 3 if irq.get("Q1") == "Yes" else 0
    domains["org"] = min(4, s)

    s = 0
    if irq.get("Q9") == "Yes":
        s += 2
    if irq.get("Q1") == "Yes":
        s += 2
    domains["reputation"] = min(4, s)

    s = 0
    if irq.get("Q4") in [">1,000,000", "100,000–1,000,000"]:
        s += 1
    if irq.get("Q2") == "Mission-critical":
        s += 1
    domains["esg"] = min(4, s)

    weights = {"infosec": 30, "privacy": 20, "resilience": 15, "compliance": 10,
               "physical": 10, "org": 5, "reputation": 5, "esg": 5}
    weighted = sum((domains[k] / 4) * weights[k] for k in weights)

    band = "LOW"
    if weighted >= 70:
        band = "HIGH"
    elif weighted >= 50:
        band = "ELEVATED"
    elif weighted >= 30:
        band = "MODERATE"

    tier1_floor = (irq.get("Q2") == "Mission-critical"
                   and any(d in ["Restricted", "Confidential", "Personal", "Payment Card", "Health", "Special Category Personal"] for d in data)
                   and irq.get("Q5") == "Yes")
    if tier1_floor and band not in ["HIGH", "ELEVATED"]:
        band = "ELEVATED"
    if irq.get("Q1") == "Yes":
        band = "HIGH"

    answered = sum(1 for q in IRQ_QUESTIONS
                   if irq.get(q["id"]) and (irq.get(q["id"]) if not isinstance(irq.get(q["id"]), list) else len(irq.get(q["id"]))))
    completeness = answered / len(IRQ_QUESTIONS)
    cls = 5 if completeness >= 0.95 else 4 if completeness >= 0.85 else 3 if completeness >= 0.70 else 2 if completeness >= 0.50 else 1

    return {"domains": domains, "weighted_pct": round(weighted, 1), "band": band, "cls": cls}


def compute_residual(inherent_band, ddq):
    critical_marginal = partial = marginal = 0
    all_q = {q["id"]: q for d in DDQ_DOMAINS for q in d["questions"]}
    for qid, resp in (ddq or {}).items():
        if resp == "MARGINAL":
            marginal += 1
            if all_q.get(qid, {}).get("critical"):
                critical_marginal += 1
        elif resp == "PARTIAL":
            partial += 1
    bands = ["LOW", "MODERATE", "ELEVATED", "HIGH"]
    idx = bands.index(inherent_band) if inherent_band in bands else 0
    if partial >= 1:
        idx = min(idx + 1, 3)
    if partial >= 4:
        idx = min(idx + 1, 3)
    if marginal >= 1:
        idx = min(idx + 1, 3)
    if critical_marginal >= 1:
        idx = 3
    return {"band": bands[idx], "critical_marginal": critical_marginal,
            "partial": partial, "marginal": marginal}


def decision_for(residual_band, critical_marginal):
    if critical_marginal > 0 or residual_band == "HIGH":
        return {"text": "DO NOT PROCEED", "route": "CISO + Legal + CRO", "tone": "red", "requires_vrm": True}
    if residual_band == "ELEVATED":
        return {"text": "ESCALATE — Conditional", "route": "TPRM Lead + CISO", "tone": "amber", "requires_vrm": True}
    if residual_band == "MODERATE":
        return {"text": "APPROVE WITH CONDITIONS", "route": "TPRM Lead (6-month review)", "tone": "blue", "requires_vrm": False}
    return {"text": "APPROVE", "route": "TPRM Analyst (annual)", "tone": "green", "requires_vrm": False}


def compute_route(irq, inherent, tier):
    data = irq.get("Q3", []) or []
    if isinstance(data, str):
        data = [data]
    special = any(d in ["Special Category Personal", "Health", "Payment Card", "Restricted"] for d in data)
    sanctions = irq.get("Q1") == "Yes"
    cross_border = irq.get("Q5") == "Yes"
    ai = irq.get("Q12") == "Yes"
    band = inherent["band"]

    blockers = []
    if sanctions:
        blockers.append("Sanctions / regulatory exposure")
    if special:
        blockers.append("Special-category / restricted data")
    if band == "HIGH":
        blockers.append("Inherent band HIGH")
    if tier == "Tier 1":
        blockers.append("Tier-1 critical engagement")

    cautions = []
    if cross_border:
        cautions.append("Cross-border transfer")
    if ai:
        cautions.append("AI / automated decision-making")
    if band == "ELEVATED":
        cautions.append("Inherent band ELEVATED")
    if tier == "Tier 2":
        cautions.append("Tier-2 engagement")

    if band == "LOW" and tier == "Tier 3" and not blockers and not cross_border and not ai:
        return {"route": "AUTO-APPROVE", "color": "#2A6B3C", "human_touch": False,
                "reason": "LOW band · Tier-3 · no special-category data · no sanctions · no cross-border · no AI. Cleared against the standard condition set with zero human touch.",
                "blockers": [], "cautions": cautions, "condition_set": "STANDARD"}
    if not blockers:
        return {"route": "FAST-TRACK", "color": "#C47820", "human_touch": True,
                "reason": "No hard blockers. Reduced DDQ subset covering only elevated domains; reviewer sees exceptions only.",
                "blockers": [], "cautions": cautions, "condition_set": "STANDARD+"}
    return {"route": "FULL DILIGENCE", "color": "#B23020", "human_touch": True,
            "reason": "One or more blockers require full assessment across all applicable domains with VRM sign-off.",
            "blockers": blockers, "cautions": cautions, "condition_set": "BESPOKE"}


SEVERITY_SLA = {"critical": 7, "high": 14, "medium": 30, "low": 60}
# DB-05: the engine previously kept its own lower-case vocabulary, which reached the
# database and diverged from every other module. It now uses the canonical set.
from app.features.domain.vocab import FINDING_STATUSES  # noqa: E402
STAGES = ["Context", "Intake", "IRQ", "Rating", "Scoping", "DDQ", "Residual", "Decision"]


def chain_hash(prev_hash, action, actor, detail):
    body = json.dumps({"action": action, "actor": actor, "detail": detail}, sort_keys=True)
    return hashlib.sha256(((prev_hash or "genesis") + body).encode()).hexdigest()[:16]


# ─── Offboarding checklist (8 steps) ────────────────────────────────────────
OFFBOARDING_STEPS = [
    ("notice", "Termination notice served per contract notice period"),
    ("access", "All system / data access revoked (leaver process)"),
    ("datareturn", "Data returned to organisation in agreed format"),
    ("destroy", "Residual data destroyed; certified destruction attestation received"),
    ("exit", "Exit plan executed against documented exit strategy"),
    ("knowledge", "Knowledge transfer / transition assistance completed"),
    ("fourthp", "Sub-processor / 4th-party access terminated"),
    ("final", "Final invoice reconciled; commercial close-out"),
]

# ─── Tier-based periodic reassessment cadence ───────────────────────────────
TIER_REASSESS_MONTHS = {"Tier 1": 12, "Tier 2": 24, "Tier 3": 36}

# ─── Delta reassessment triggers → affected domains ─────────────────────────
DELTA_TRIGGERS = [
    ("newdata", "New data type / flow", ["infosec", "privacy"]),
    ("newjuris", "New jurisdiction", ["privacy", "compliance"]),
    ("newsub", "New sub-processor / 4th party", ["resilience", "infosec"]),
    ("newservice", "Expanded service scope", ["resilience", "compliance", "reputation"]),
    ("newai", "New AI / automation", ["compliance", "reputation"]),
    ("incident", "Security / privacy incident", ["infosec", "privacy", "reputation"]),
]

# ─── Contract minimum terms — tiered, regulation-grounded ───────────────────
CONTRACT_TERMS = {
    "Tier 1 — Regulatory mandatory": [
        "Data Processing Agreement (GDPR Art. 28) with documented instructions",
        "DORA Art. 28 contractual requirements for ICT services",
        "Audit & inspection rights (FCA SYSC 8.1 / EBA GL outsourcing)",
        "Sub-processor approval & flow-down obligations",
        "Security incident notification within defined window",
        "Exit & transition assistance clause",
    ],
    "Tier 2 — Market standard": [
        "Confidentiality & non-disclosure",
        "Defined SLAs with service credits",
        "Data deletion / return on termination",
        "Liability cap & indemnities",
        "Business continuity & disaster recovery commitments",
    ],
    "Tier 3 — Best practice": [
        "Personnel vetting & background checks",
        "Right to conduct security testing",
        "Benchmarking / continuous-improvement clause",
        "Insurance (cyber & professional indemnity) evidence",
    ],
}


def contract_terms_for(contract_type, has_data, is_outsourcing):
    """Return the tiered checklist relevant to this contract."""
    out = {}
    out["Tier 1 — Regulatory mandatory"] = list(CONTRACT_TERMS["Tier 1 — Regulatory mandatory"])
    out["Tier 2 — Market standard"] = list(CONTRACT_TERMS["Tier 2 — Market standard"])
    out["Tier 3 — Best practice"] = list(CONTRACT_TERMS["Tier 3 — Best practice"])
    if not has_data:
        out["Tier 1 — Regulatory mandatory"] = [t for t in out["Tier 1 — Regulatory mandatory"]
                                                if "Data Processing" not in t and "Sub-processor" not in t]
    return out


def fdd_local_score(fin):
    """Compute a financial-health score (0-100) + band from entered ratios.
    fin: dict possibly containing current_ratio, debt_equity, net_margin, interest_cover."""
    score, n = 0, 0
    def band_pts(v, good, ok):
        return 100 if v >= good else 60 if v >= ok else 25
    if fin.get("current_ratio") is not None:
        score += band_pts(fin["current_ratio"], 1.5, 1.0); n += 1
    if fin.get("net_margin") is not None:
        score += band_pts(fin["net_margin"], 10, 2); n += 1
    if fin.get("interest_cover") is not None:
        score += band_pts(fin["interest_cover"], 3, 1.5); n += 1
    if fin.get("debt_equity") is not None:
        de = fin["debt_equity"]
        score += (100 if de <= 1 else 60 if de <= 2 else 25); n += 1
    if n == 0:
        return None, "UNRATED"
    s = round(score / n)
    band = "STRONG" if s >= 80 else "ADEQUATE" if s >= 65 else "WATCH" if s >= 45 else "ELEVATED" if s >= 30 else "DISTRESSED"
    return s, band


def next_reassess_date(tier, last_iso=None):
    from datetime import datetime, timedelta
    months = TIER_REASSESS_MONTHS.get(tier, 24)
    base = datetime.fromisoformat(last_iso) if last_iso else datetime.now()
    # approx month math
    return (base + timedelta(days=months * 30)).strftime("%Y-%m-%d")
