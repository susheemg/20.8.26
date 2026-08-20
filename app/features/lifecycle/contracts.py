"""
Contract Management engine (Matt) — ported & extended from the uploaded BRO platform.

- Tiered minimum terms (Tier 1 Regulatory mandatory ... Tier 4 Commercial),
  **scaled to the engagement's inherent risk band + exposure flags** so the
  recommended set tightens for higher-risk engagements.
- Gap report: which required terms are present / missing / weak in a drafted
  contract (text), with severity + suggested remediation wording.
- Existing-vs-to-add diff: cross-reference prior contracts already in the system
  so only genuine gaps are recommended.

Deterministic clause library works offline; an LLM key enriches wording.
"""
from __future__ import annotations

from typing import Optional

# Clause library. Each: key, name, tier (1-4), basis, and the minimum
# inherent band at which it becomes required.
# tier 1 = regulatory mandatory, 2 = market standard, 3 = best practice,
# 4 = commercial preference.
_CLAUSES = [
    # always-on baseline (any engagement)
    {"key": "parties_scope", "name": "Parties & scope of services", "tier": 2,
     "basis": "Contract certainty", "min_band": "LOW"},
    {"key": "term_termination", "name": "Term & termination for convenience/cause", "tier": 2,
     "basis": "Market standard", "min_band": "LOW"},
    {"key": "fees", "name": "Fees, invoicing & payment terms", "tier": 4,
     "basis": "Commercial preference", "min_band": "LOW"},
    {"key": "confidentiality", "name": "Confidentiality", "tier": 2,
     "basis": "Market standard", "min_band": "LOW"},
    # moderate+ exposure
    {"key": "data_protection", "name": "Data protection / DPA (GDPR Art.28)", "tier": 1,
     "basis": "UK GDPR Art. 28", "min_band": "MODERATE"},
    {"key": "info_security", "name": "Information security schedule", "tier": 1,
     "basis": "Regulatory outsourcing expectation", "min_band": "MODERATE"},
    {"key": "audit_rights", "name": "Audit & inspection rights", "tier": 1,
     "basis": "FCA SYSC 8 / DORA Art. 30", "min_band": "MODERATE"},
    {"key": "liability", "name": "Limitation of liability & indemnities", "tier": 2,
     "basis": "Market standard", "min_band": "MODERATE"},
    {"key": "sub_processing", "name": "Sub-processing / fourth-party controls", "tier": 1,
     "basis": "UK GDPR Art. 28(2); DORA", "min_band": "MODERATE"},
    # elevated/high exposure
    {"key": "business_continuity", "name": "Business continuity & disaster recovery", "tier": 1,
     "basis": "FCA SYSC 8 outsourcing", "min_band": "ELEVATED"},
    {"key": "exit_step_in", "name": "Exit plan & step-in rights", "tier": 1,
     "basis": "DORA Art. 28(8) / FCA outsourcing", "min_band": "ELEVATED"},
    {"key": "incident_notification", "name": "Incident & breach notification (timelines)", "tier": 1,
     "basis": "UK GDPR Art. 33; DORA", "min_band": "ELEVATED"},
    {"key": "cross_border", "name": "Cross-border transfer safeguards (SCCs/IDTA)", "tier": 1,
     "basis": "UK GDPR Ch. V", "min_band": "ELEVATED"},
    {"key": "concentration", "name": "Concentration & substitutability provisions", "tier": 3,
     "basis": "Best practice (systemic dependency)", "min_band": "HIGH"},
    {"key": "regulator_access", "name": "Regulator direct access & cooperation", "tier": 1,
     "basis": "DORA Art. 30(3)", "min_band": "HIGH"},
    {"key": "source_code_escrow", "name": "Source code / data escrow", "tier": 3,
     "basis": "Best practice (resilience)", "min_band": "HIGH"},
]

_BAND_RANK = {"LOW": 0, "MODERATE": 1, "ELEVATED": 2, "HIGH": 3}
_TIER_SEVERITY = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}


def required_terms(inherent_band: str = "MODERATE",
                   exposure: Optional[dict] = None) -> list[dict]:
    """Return the minimum terms required for this engagement's inherent risk +
    exposure profile. Higher band -> broader, more stringent set."""
    exposure = exposure or {}
    rank = _BAND_RANK.get((inherent_band or "MODERATE").upper(), 1)
    out = []
    for c in _CLAUSES:
        if _BAND_RANK[c["min_band"]] <= rank:
            out.append(c)
    # exposure flags can pull specific clauses in even at a lower band
    keys = {c["key"] for c in out}
    flag_map = {
        "personal_data": ["data_protection", "incident_notification"],
        "cross_border": ["cross_border"],
        "mission_critical": ["business_continuity", "exit_step_in"],
        "fourth_party": ["sub_processing", "concentration"],
        "regulated": ["audit_rights", "regulator_access"],
    }
    for flag, clause_keys in flag_map.items():
        if exposure.get(flag):
            for ck in clause_keys:
                if ck not in keys:
                    clause = next((c for c in _CLAUSES if c["key"] == ck), None)
                    if clause:
                        out.append(clause); keys.add(ck)
    out.sort(key=lambda c: (c["tier"], c["name"]))
    return out


def gap_report(contract_text: str, inherent_band: str = "MODERATE",
               exposure: Optional[dict] = None) -> dict:
    """Compare a drafted contract's text against the required terms. A clause is
    'present' if its name tokens appear in the text; otherwise 'missing'."""
    req = required_terms(inherent_band, exposure)
    text = (contract_text or "").lower()
    present, gaps = [], []
    for c in req:
        # crude but deterministic presence test: any significant token of the
        # clause name (or its key) present in the contract text
        tokens = [t for t in c["name"].lower().replace("/", " ").split()
                  if len(t) > 4] + [c["key"].replace("_", " ")]
        hit = any(t in text for t in tokens)
        if hit:
            present.append({"clause": c["name"], "tier": c["tier"]})
        else:
            gaps.append({
                "clause": c["name"], "tier": c["tier"],
                "severity": _TIER_SEVERITY[c["tier"]],
                "basis": c["basis"],
                "remediation": f"Add a '{c['name']}' clause ({c['basis']}).",
            })
    crit = sum(1 for g in gaps if g["severity"] == "Critical")
    verdict = ("Not ready — critical regulatory gaps" if crit else
               "Conditionally ready — non-critical gaps" if gaps else
               "Ready — all required terms present")
    return {"required_count": len(req), "present": present, "gaps": gaps,
            "critical_gaps": crit, "verdict": verdict}


def existing_vs_to_add(inherent_band: str, exposure: Optional[dict],
                       prior_contract_texts: list[str]) -> dict:
    """Cross-reference prior contracts already in the system: report
    'terms already existing' vs 'terms to be added' for this engagement."""
    req = required_terms(inherent_band, exposure)
    combined = " \n ".join(prior_contract_texts or []).lower()
    existing, to_add = [], []
    for c in req:
        tokens = [t for t in c["name"].lower().replace("/", " ").split()
                  if len(t) > 4] + [c["key"].replace("_", " ")]
        if combined and any(t in combined for t in tokens):
            existing.append({"clause": c["name"], "tier": c["tier"]})
        else:
            to_add.append({"clause": c["name"], "tier": c["tier"],
                           "severity": _TIER_SEVERITY[c["tier"]], "basis": c["basis"]})
    return {"prior_contracts": len(prior_contract_texts or []),
            "terms_already_existing": existing, "terms_to_be_added": to_add}
