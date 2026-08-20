"""
Entity resolution + live financial research for the analysis sections.

resolve_entity() lets every analysis section (FDD, Reputation, Monitoring,
Contracts) target either a REGISTERED vendor (by Vendor ID or name) or an
unregistered entity typed into an "Other" free-text field. Outputs always carry
{vendor_id, vendor_name} so results link back to the register where possible.

research_financials() performs authoritative web research for published
financials when a live LLM key is configured; otherwise it returns a clear
"manual entry required" result so the deterministic engine still runs offline.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session


def _balanced_json_objects(s: str) -> list:
    """Return every top-level, brace-balanced {...} span in ``s`` that parses as
    JSON, in order. String-aware, so braces inside quoted values don't confuse it.
    Robust to web-search narration, citations and trailing prose around the JSON."""
    out = []
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        out.append(json.loads(s[start:i + 1]))
                    except Exception:
                        pass
                    start = None
    return out


def _extract_json_obj(text: str) -> Optional[dict]:
    """Best-effort extraction of the answer JSON object from noisy model output.

    Web-search responses interleave the model's narration and search results with
    the final JSON, and may wrap it in one of several markdown fences. We prefer the
    LAST balanced object that parses (the final answer), checking fenced blocks first
    and then the whole text, so leading prose or stray braces can't derail parsing.
    Returns a dict, or None if nothing parseable is present (genuinely unparseable /
    truncated output)."""
    if not text:
        return None
    import re as _re
    candidates = [f.strip() for f in _re.findall(r"```(?:json)?\s*(.*?)```", text, _re.DOTALL)]
    candidates.append(text)  # also scan the raw text
    for cand in candidates:
        objs = _balanced_json_objects(cand)
        if objs:
            # the answer is the last complete object; prefer one that looks like a result
            for obj in reversed(objs):
                if isinstance(obj, dict):
                    return obj
    return None

from app.features.domain.registry_models import VendorRecord


def resolve_entity(s: Session, *, vendor_id: Optional[str] = None,
                   other_name: Optional[str] = None) -> dict:
    """Resolve to {vendor_id, vendor_name, registered}.
    Priority: explicit vendor_id -> match by name -> 'Other' free text."""
    if vendor_id:
        v = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vendor_id)).first()
        if v:
            return {"vendor_id": v.vendor_id, "vendor_name": v.legal_name, "registered": True}
    if other_name:
        # try to match an existing vendor by (case-insensitive) name first
        nm = other_name.strip().lower()
        for v in s.scalars(select(VendorRecord)).all():
            if v.legal_name.strip().lower() == nm:
                return {"vendor_id": v.vendor_id, "vendor_name": v.legal_name, "registered": True}
        # unregistered entity (the "Other" path)
        return {"vendor_id": None, "vendor_name": other_name.strip(), "registered": False}
    return {"vendor_id": None, "vendor_name": "(unspecified)", "registered": False}


# ---- live financial research (LLM + web) ----
_RESEARCH_SYSTEM = (
    "You are Vera+Rex inside a TPRM platform: a financial research + extraction unit. "
    "Locate the most recent PUBLISHED financial statements for the named entity from "
    "AUTHORITATIVE sources only (UK Companies House/FCA; US SEC EDGAR 10-K/10-Q/20-F; "
    "EU/other national registries + audited annual reports). Reputable press may "
    "corroborate but never be the sole source. Never estimate or fabricate — return null "
    "for any figure you cannot substantiate. Report all monetary figures in MILLIONS of "
    "the reporting currency as plain numbers. Return ONLY a JSON object with this shape: "
    '{"matched":bool,"entity":{"legalName":str,"identifier":str|null,"jurisdiction":str|null},'
    '"period":str,"currency":str,"unit":"millions","figures":{"revenue":num|null,"cogs":num|null,'
    '"grossProfit":num|null,"ebit":num|null,"ebitda":num|null,"netProfit":num|null,"interest":num|null,'
    '"currentAssets":num|null,"currentLiabilities":num|null,"inventory":num|null,"cash":num|null,'
    '"totalAssets":num|null,"totalDebt":num|null,"equity":num|null,"receivables":num|null,'
    '"payables":num|null,"netDebt":num|null,"totalLiabilities":num|null,"retainedEarnings":num|null},'
    '"flags":{"auditQualified":bool,"goingConcern":bool,"negativeEquity":bool,"filingsOnTime":bool},'
    '"sources":[{"name":str,"type":str,"date":str,"url":str}],"confidence":"high"|"medium"|"low",'
    '"limitations":str}'
)


_WEB_RESEARCH_SYSTEM = (
    "You are Vera+Rex+Mira inside a TPRM platform with LIVE WEB SEARCH. Research the "
    "named third party on the open internet and return a combined FINANCIAL DUE DILIGENCE "
    "and REPUTATION assessment. Use web search to find: (a) the most recent PUBLISHED "
    "financial statements from AUTHORITATIVE sources (Companies House/FCA; SEC EDGAR "
    "10-K/10-Q/20-F; national registries; audited annual reports); (b) reputation and "
    "conduct signals from reputable news, regulators, courts and sanctions/PEP lists. "
    "RULES: use only what you actually find via search; never estimate or fabricate a "
    "figure — return null if unsubstantiated. Every material claim must trace to a real "
    "source URL you retrieved. Report monetary figures in MILLIONS of the reporting "
    "currency as plain numbers. Return ONLY a JSON object with this shape: "
    '{"matched":bool,"entity":{"legalName":str,"identifier":str|null,"jurisdiction":str|null},'
    '"financials":{"period":str|null,"currency":str|null,"figures":{"revenue":num|null,'
    '"cogs":num|null,"grossProfit":num|null,"ebit":num|null,"ebitda":num|null,"netProfit":num|null,'
    '"interest":num|null,"currentAssets":num|null,"currentLiabilities":num|null,"inventory":num|null,'
    '"cash":num|null,"totalAssets":num|null,"totalDebt":num|null,"equity":num|null,"receivables":num|null,'
    '"payables":num|null,"retainedEarnings":num|null},"flags":{"auditQualified":bool,'
    '"goingConcern":bool,"negativeEquity":bool,"filingsOnTime":bool},"healthCommentary":str},'
    '"reputation":{"verdict":"Positive"|"Neutral"|"Caution"|"Adverse","adverseMedia":bool,'
    '"sanctionsOrPEP":bool,"litigation":bool,"signals":[{"category":str,"severity":"low"|"medium"|"high",'
    '"summary":str,"date":str|null}]},"sources":[{"title":str,"type":str,"date":str|null,"url":str}],'
    '"confidence":"high"|"medium"|"low","limitations":str}'
)


def web_research_fdd_reputation(company: str, jurisdiction: str = "UK",
                                identifier: str = "", methodology: str = "", mode: str = "both",
                                deep: bool = False) -> dict:
    """Live internet research for combined FDD + reputation. Requires an AI key
    AND a web-search-capable provider; otherwise returns a clear unavailable note
    so the deterministic engines remain the offline path."""
    from app.agents import llm_config
    st = llm_config.status()
    if not st.get("live_ready"):
        return {"matched": False, "available": False,
                "limitations": ("Live internet research needs an AI key AND the provider "
                                "library installed (Settings → AI provider must show "
                                "'LIVE AI READY'). Otherwise enter figures manually to run "
                                "the deterministic engine.")}
    focus = {"fdd": " Focus on FINANCIAL DUE DILIGENCE; reputation may be brief.",
             "reputation": " Focus on REPUTATION & CONDUCT; financials may be brief.",
             "both": ""}.get(mode, "")
    system = _WEB_RESEARCH_SYSTEM + (("\n\n" + methodology) if methodology else "")
    instruction = (f'Third party: "{company}"'
                   + (f" (identifier/ticker: {identifier})" if identifier else "")
                   + (f", jurisdiction: {jurisdiction}" if jurisdiction else "")
                   + "." + focus
                   + " Search the web now, then return the combined FDD + reputation JSON "
                     "object only, with a real source URL for every material claim.")
    _rt = float(os.environ.get("BRO_RESEARCH_TIMEOUT", "90"))
    _rtd = float(os.environ.get("BRO_RESEARCH_TIMEOUT_DEEP", "300"))
    text = llm_config.complete(system, instruction,
                               domain="finance", web_search=True,
                               review=bool(deep), timeout_s=(_rtd if deep else _rt))
    if not text:
        reason = llm_config.last_error() or "the provider returned nothing"
        return {"matched": False, "available": True,
                "limitations": ("AI research did not complete: " + reason +
                                ". Check the AI provider/key/model and web-search entitlement "
                                "in Settings → AI, then retry.")}
    out = _extract_json_obj(text)
    if isinstance(out, dict):
        out["available"] = True
        return out
    return {"matched": False, "available": True, "raw": text[:1200],
            "limitations": "Could not parse research output; see raw text."}


def research_financials(company: str, jurisdiction: str = "UK",
                        identifier: str = "", year: str = "") -> dict:
    """Authoritative financials research. Requires a live LLM key; returns a
    structured 'manual entry' result otherwise so the engine still works offline."""
    from app.agents import llm_config
    if not llm_config.is_enabled():
        return {"matched": False, "available": False,
                "limitations": "Live research needs an AI key (ANTHROPIC_API_KEY / "
                               "OPENAI_API_KEY). Enter the figures manually to run the "
                               "deterministic engine."}
    instruction = (f'Entity: "{company}"'
                   + (f" (identifier/ticker: {identifier})" if identifier else "")
                   + (f", jurisdiction: {jurisdiction}" if jurisdiction else "")
                   + (f", target year: {year}" if year else "")
                   + ". Find the latest authoritative published financials and return the "
                     "JSON object only. If you cannot confidently match an authoritative "
                     'filing, set "matched": false and explain in "limitations".')
    text = llm_config.complete(_RESEARCH_SYSTEM, instruction, domain="finance")
    if not text:
        return {"matched": False, "available": True,
                "limitations": "Research call returned nothing; enter figures manually."}
    parsed = _extract_json_obj(text)
    if isinstance(parsed, dict):
        return parsed
    return {"matched": False, "available": True,
            "limitations": "Could not parse research output; enter figures manually."}
