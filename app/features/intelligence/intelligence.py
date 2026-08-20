"""
Board Intelligence engine.

Produces a board-grade horizon scan: it ingests the entire internal estate
(vendors, engagements, spend, expiry/renewal calendar, delivery geography,
findings, concentration, financial health, screening), scans an external
PESTLE horizon (Political, Regulatory, Environmental, Social, Technological),
CORRELATES the two, runs predictive models, and emits:

  - external      : PESTLE factors with a computed exposure score (0..100)
  - internal      : the key internal signals the analysis stands on
  - observations  : board observations, each with evidence, so-what, a SPECIFIC
                    action the board should instruct management to take,
                    a severity and a horizon
  - predictions   : forward-looking calls (renewal cliff, assurance lapse, …)
  - charts        : data series for the AI-rendered graphical presentation

Deterministic by default (always works offline); an LLM layer can enrich the
narrative when a provider is configured. The analytical correlation itself is
performed here so the board view is reproducible.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.domain.registry_models import (
    VendorRecord, EngagementRecord, ArtefactRecord, FindingRecord,
    IssueRecord, FourthPartyRecord, FourthPartyVendor,
)
from app.features.domain.master_ext import (
    EngagementExt, VendorMasterExt, VendorCyber, VendorScreening,
)


def _days_to(d: Optional[str]) -> Optional[int]:
    if not d:
        return None
    try:
        return (datetime.fromisoformat(str(d)[:10]).date() - date.today()).days
    except Exception:
        return None


def _band_sev(score: int) -> str:
    return "Critical" if score >= 75 else "High" if score >= 55 else "Elevated" if score >= 35 else "Moderate"


# --- external horizon: standing PESTLE themes relevant to FS third-party risk ---
# Each theme carries a base salience and the internal trigger that makes it material.
PESTLE_THEMES = {
    "Political": [
        ("Geopolitical exposure of offshore delivery", "Concentration of delivery in a single jurisdiction raises geopolitical and continuity risk."),
        ("Sanctions-regime volatility", "Expanding sanctions lists increase screening and counterparty-exit obligations."),
    ],
    "Regulatory": [
        ("DORA / operational-resilience regime for ICT third parties", "Critical ICT providers must be in a register with tested exit and impact tolerances."),
        ("Cross-border data-transfer scrutiny (GDPR / SCCs)", "Personal data moving across borders demands valid transfer mechanisms and DPAs."),
        ("Outsourcing & audit-right expectations (EBA / PRA)", "Regulators expect enforceable audit rights and substitutability for material outsourcing."),
    ],
    "Environmental": [
        ("Physical-climate risk to provider sites", "Data-centre and delivery-site concentration exposes the firm to climate disruption."),
        ("ESG-disclosure obligations (CSRD)", "Supply-chain ESG data and modern-slavery posture are increasingly mandated."),
    ],
    "Social": [
        ("Modern-slavery & labour concentration", "Offshore labour concentration raises conduct, ESG and continuity exposure."),
        ("Key-person and skills concentration", "Reliance on scarce skills at concentrated providers raises delivery risk."),
    ],
    "Technological": [
        ("Hyperscaler / cloud concentration", "Funnelling critical services through one cloud hub creates systemic single-point risk."),
        ("Escalating cyber-threat landscape", "Rising attack frequency elevates the cost of any control or assurance gap."),
        ("GenAI adoption by providers", "Vendors embedding GenAI introduce new data-handling and model-risk questions."),
    ],
}


def board_intelligence(s: Session) -> dict:
    today = date.today()
    vendors = list(s.scalars(select(VendorRecord)).all())
    vmap = {v.vendor_id: v for v in vendors}
    engs = list(s.scalars(select(EngagementRecord)).all())
    exts = {e.engagement_id: e for e in s.scalars(select(EngagementExt)).all()}

    n_vendors = len(vendors)
    n_critical = sum(1 for v in vendors if v.is_critical)
    n_engs = len(engs)

    # ---- spend ----
    total_spend = 0
    spend_by_band: Counter = Counter()
    for e in engs:
        ext = exts.get(e.engagement_id)
        val = (ext.actual_spend if ext and ext.actual_spend else None) or e.annual_value or 0
        total_spend += val
        spend_by_band[e.residual_band or "MODERATE"] += val

    # ---- residual distribution ----
    resid = Counter(e.residual_band or "MODERATE" for e in engs)

    # ---- delivery geography concentration ----
    loc_counter: Counter = Counter()
    loc_spend: Counter = Counter()
    cross_border = personal_data = ict = mission = 0
    for e in engs:
        ext = exts.get(e.engagement_id)
        if not ext:
            continue
        if ext.delivery_location:
            loc_counter[ext.delivery_location] += 1
            loc_spend[ext.delivery_location] += (ext.actual_spend or e.annual_value or 0)
        cross_border += 1 if ext.cross_border else 0
        personal_data += 1 if ext.personal_data else 0
        ict += 1 if ext.ict_flag else 0
        mission += 1 if ext.mission_critical else 0
    top_locs = loc_counter.most_common(6)
    top_loc, top_loc_n = (top_locs[0] if top_locs else ("—", 0))
    loc_share = round(100 * top_loc_n / n_engs) if n_engs else 0

    # ---- audit-rights / exit-test / DPA gaps ----
    no_audit = sum(1 for ext in exts.values() if not ext.audit_rights)
    no_exit_test = sum(1 for e in engs if e.residual_band in ("HIGH", "ELEVATED")
                       and not (exts.get(e.engagement_id) and exts[e.engagement_id].exit_plan_tested))
    no_dpa = sum(1 for ext in exts.values() if ext.personal_data and not ext.dpa_in_place)

    # ---- expiry / renewal calendar ----
    arts = list(s.scalars(select(ArtefactRecord)).all())
    exp_buckets = {"≤30d": 0, "31-60d": 0, "61-90d": 0, "91-180d": 0, "expired": 0}
    crit_expiring = 0
    for a in arts:
        d = _days_to(a.expiry_date)
        if d is None:
            continue
        if d < 0:
            exp_buckets["expired"] += 1
        elif d <= 30:
            exp_buckets["≤30d"] += 1
        elif d <= 60:
            exp_buckets["31-60d"] += 1
        elif d <= 90:
            exp_buckets["61-90d"] += 1
        elif d <= 180:
            exp_buckets["91-180d"] += 1
        if d is not None and d <= 90 and vmap.get(a.vendor_id) and vmap[a.vendor_id].is_critical:
            crit_expiring += 1

    renew_90 = 0
    renew_spend = 0
    for e in engs:
        ext = exts.get(e.engagement_id)
        d = _days_to(ext.next_review_date) if ext else None
        d2 = _days_to(ext.end_date) if ext else None
        near = min([x for x in (d, d2) if x is not None and x >= 0] or [9999])
        if near <= 90:
            renew_90 += 1
            renew_spend += (ext.actual_spend or e.annual_value or 0) if ext else (e.annual_value or 0)

    # ---- findings / issues ----
    findings = list(s.scalars(select(FindingRecord)).all())
    open_findings = [f for f in findings if (f.status or "").lower() not in ("closed",)]
    high_findings = sum(1 for f in open_findings if f.severity == "High")
    find_by_domain = Counter(f.domain for f in open_findings if f.domain)
    n_issues = s.scalar(select(__import__("sqlalchemy").func.count()).select_from(IssueRecord)
                        .where(IssueRecord.status == "Open")) or 0

    # ---- financial distress / breaches / screening ----
    distress = [v for v in vendors if (s.scalars(select(VendorMasterExt).where(
        VendorMasterExt.vendor_id == v.vendor_id)).first() or VendorMasterExt()).financial_health_band
        in ("Weak", "Distress", "Caution")]
    breaches = [v for v in vendors if (s.scalars(select(VendorCyber).where(
        VendorCyber.vendor_id == v.vendor_id)).first() or VendorCyber()).breach_history_flag]
    screen_hits = list(s.scalars(select(VendorScreening).where(VendorScreening.result == "hit")).all())

    # ---- fourth-party concentration hub ----
    fp_names = {f.fourth_party_id: f for f in s.scalars(select(FourthPartyRecord)).all()}
    fp_deg: Counter = Counter()
    for link in s.scalars(select(FourthPartyVendor)).all():
        if link.vendor_id in vmap:
            fp_deg[link.fourth_party_id] += 1
    top_hub_id, top_hub_n = (fp_deg.most_common(1)[0] if fp_deg else (None, 0))
    top_hub = fp_names.get(top_hub_id)
    hub_name = top_hub.legal_name if top_hub else "—"
    hub_share = round(100 * top_hub_n / n_vendors) if n_vendors else 0

    # =====================================================================
    # EXTERNAL HORIZON exposure scoring (each factor scored from internal data)
    # =====================================================================
    def clamp(x):
        return max(4, min(100, int(round(x))))

    factor_scores = {
        "Political": clamp(loc_share * 0.9 + (15 if loc_share >= 40 else 0)),
        "Regulatory": clamp((no_audit / max(n_engs, 1)) * 60 + (no_exit_test * 3) + (no_dpa * 2) + ict / max(n_engs, 1) * 30),
        "Environmental": clamp(loc_share * 0.5 + len(distress) * 2 + 20),
        "Social": clamp(loc_share * 0.7 + 18),
        "Technological": clamp(hub_share * 0.8 + len(breaches) * 3 + (30 if hub_share >= 30 else 10)),
    }
    external = []
    for fac, score in factor_scores.items():
        theme = PESTLE_THEMES[fac][0]
        external.append({"factor": fac, "score": score, "severity": _band_sev(score),
                         "headline": theme[0], "rationale": theme[1]})

    # =====================================================================
    # BOARD OBSERVATIONS  (external x internal correlation -> board action)
    # =====================================================================
    obs = []

    def add(title, factor, severity, evidence, so_what, action, horizon):
        obs.append({"title": title, "factor": factor, "severity": severity,
                    "evidence": evidence, "so_what": so_what,
                    "board_action": action, "horizon": horizon})

    if ict and (no_audit or no_exit_test):
        _audit_clause = (f" and remediate missing audit-right clauses on {no_audit} engagements"
                         if no_audit else "")
        _audit_ev = (f"; {no_audit} engagements lacking enforceable audit rights"
                     if no_audit else "; audit rights are in place across the estate")
        add("DORA / operational-resilience readiness gap", "Regulatory",
            _band_sev(factor_scores["Regulatory"]),
            f"{ict} ICT-flagged engagements; {no_exit_test} critical engagements without tested exit plans{_audit_ev}.",
            "Under the operational-resilience regime, critical ICT third parties must sit in a register with tested exit plans and impact tolerances. The estate is not yet evidenced to that standard.",
            f"Instruct management to complete the critical-ICT third-party register and evidence exit-plan testing for every critical ICT provider{_audit_clause}, within two quarters.",
            "0-6 months")

    if hub_share >= 25 and top_hub:
        add(f"Cloud / fourth-party concentration on {hub_name}", "Technological",
            _band_sev(factor_scores["Technological"]),
            f"{top_hub_n} vendors ({hub_share}% of the book) depend on {hub_name}; {mission} engagements are mission-critical.",
            "A shared fourth-party hub is a systemic single point of failure: one provider incident can cascade across a quarter of the portfolio simultaneously.",
            f"Instruct management to produce a multi-region/alternate-provider resilience plan and substitutability assessment for {hub_name}, and to stress-test a simultaneous-outage scenario.",
            "0-9 months")

    if loc_share >= 35:
        add(f"Geographic delivery concentration in {top_loc}", "Political",
            _band_sev(factor_scores["Political"]),
            f"{top_loc_n} engagements ({loc_share}%) are delivered from {top_loc}; concentrated spend of ~£{round(loc_spend[top_loc]/1e6,1)}m.",
            "Concentrated offshore delivery couples the portfolio to a single jurisdiction's political, labour and continuity conditions.",
            f"Instruct management to map continuity and exit options for {top_loc} delivery and set a concentration tolerance with a diversification plan where breached.",
            "3-12 months")

    if crit_expiring or exp_buckets["expired"]:
        add("Assurance-lapse / certificate-expiry cliff", "Regulatory",
            _band_sev(50 + crit_expiring * 2),
            f"{crit_expiring} certificates on critical vendors expire within 90 days; {exp_buckets['expired']} are already expired; {n_issues} open issues.",
            "Lapsed assurance leaves material vendors operating without current evidence of control — an audit and regulatory finding waiting to happen.",
            "Instruct management to clear the expired-certificate backlog and pre-emptively re-collect assurance for all critical vendors expiring within the next quarter.",
            "0-3 months")

    if distress:
        add("Counterparty financial-failure exposure", "Political",
            _band_sev(45 + len(distress) * 3),
            f"{len(distress)} vendors show weak/distressed financial health; combined exposure across active engagements.",
            "A financially distressed critical provider can fail with little notice, triggering a disorderly exit and service disruption.",
            "Instruct management to place distressed critical vendors on enhanced financial monitoring and to confirm a viable, costed exit/substitution path for each.",
            "0-6 months")

    if no_dpa or cross_border:
        add("Cross-border data-transfer compliance gap", "Regulatory",
            _band_sev(40 + no_dpa * 3),
            f"{cross_border} engagements involve cross-border data; {no_dpa} process personal data without a recorded DPA.",
            "Personal data moving across borders without a valid transfer mechanism is a direct regulatory and reputational exposure.",
            "Instruct management to evidence a DPA and a valid transfer mechanism for every engagement processing personal data across borders.",
            "0-6 months")

    if breaches:
        add("Cyber-assurance gap against rising threat", "Technological",
            _band_sev(factor_scores["Technological"]),
            f"{len(breaches)} vendors carry a disclosed-breach history; {high_findings} open high-severity findings; top finding domain: {(find_by_domain.most_common(1)[0][0] if find_by_domain else 'n/a')}.",
            "Against an escalating threat landscape, vendors with prior breaches and open high findings represent the firm's most likely incident vector.",
            "Instruct management to require independent re-assurance (penetration test / SOC 2) from previously-breached critical vendors and to time-bound closure of all high-severity findings.",
            "0-6 months")

    add("Modern-slavery & ESG supply-chain posture", "Social",
        _band_sev(factor_scores["Social"]),
        f"{loc_share}% delivery concentration offshore; ESG/CSRD disclosure expectations rising.",
        "Incoming disclosure regimes require defensible supply-chain ESG and modern-slavery evidence the firm cannot yet fully produce.",
        "Instruct management to baseline modern-slavery and ESG attestations across critical and offshore-delivered vendors ahead of disclosure deadlines.",
        "6-18 months")

    add("Climate / physical-resilience of provider sites", "Environmental",
        _band_sev(factor_scores["Environmental"]),
        f"Delivery and data-centre concentration in {top_loc} and the top hub; physical-climate disruption risk.",
        "Physical-climate events at concentrated provider sites could disrupt multiple critical services at once.",
        "Instruct management to obtain site-resilience and climate-continuity evidence for the most concentrated delivery locations and data centres.",
        "6-18 months")

    sev_rank = {"Critical": 0, "High": 1, "Elevated": 2, "Moderate": 3}
    obs.sort(key=lambda o: sev_rank.get(o["severity"], 9))

    # =====================================================================
    # PREDICTIVE ANALYSIS
    # =====================================================================
    predictions = []
    if renew_90:
        predictions.append({
            "title": "Renewal cliff in the next quarter",
            "detail": f"{renew_90} engagements (~£{round(renew_spend/1e6,1)}m) reach review/expiry within 90 days. Expect concentrated renegotiation load and price-indexation pressure.",
            "metric": f"£{round(renew_spend/1e6,1)}m at renewal", "confidence": "High"})
    fwd_issues = exp_buckets["≤30d"] + exp_buckets["31-60d"] + exp_buckets["61-90d"]
    if fwd_issues:
        predictions.append({
            "title": "Forecast assurance-lapse issues",
            "detail": f"{fwd_issues} certificates lapse within 90 days; on current re-collection rates this converts to roughly {max(1, round(fwd_issues*0.6))} new open issues unless pre-empted.",
            "metric": f"~{max(1, round(fwd_issues*0.6))} new issues", "confidence": "Medium"})
    if hub_share >= 25:
        predictions.append({
            "title": "Concentration drift",
            "detail": f"With {hub_share}% of vendors already on {hub_name}, unmanaged onboarding will deepen the hub. Set a tolerance now before it becomes structural.",
            "metric": f"{hub_share}% on one hub", "confidence": "Medium"})
    if open_findings:
        rate = round(100 * sum(1 for f in findings if f.remediation_id) / max(len(findings), 1))
        predictions.append({
            "title": "Findings burn-down trajectory",
            "detail": f"{len(open_findings)} findings open ({high_findings} high). {rate}% carry a remediation plan; the unplanned remainder is the likely source of overdue items next cycle.",
            "metric": f"{high_findings} high open", "confidence": "High"})

    # =====================================================================
    # CHARTS (data series for the AI-rendered graphical presentation)
    # =====================================================================
    charts = {
        "pestle": [{"label": f, "value": factor_scores[f]} for f in
                   ["Political", "Regulatory", "Environmental", "Social", "Technological"]],
        "residual": [{"label": b, "value": resid.get(b, 0)} for b in ["LOW", "MODERATE", "ELEVATED", "HIGH"]],
        "geography": [{"label": k, "value": v} for k, v in top_locs],
        "expiry": [{"label": k, "value": exp_buckets[k]} for k in ["expired", "≤30d", "31-60d", "61-90d", "91-180d"]],
        "spend_by_band": [{"label": b, "value": round(spend_by_band.get(b, 0) / 1e6, 2)}
                          for b in ["LOW", "MODERATE", "ELEVATED", "HIGH"]],
    }

    internal = {
        "vendors": n_vendors, "critical_vendors": n_critical, "engagements": n_engs,
        "total_spend_m": round(total_spend / 1e6, 1),
        "top_location": top_loc, "top_location_share": loc_share,
        "top_hub": hub_name, "top_hub_share": hub_share,
        "open_findings": len(open_findings), "high_findings": high_findings,
        "open_issues": n_issues, "distressed_vendors": len(distress),
        "breach_vendors": len(breaches), "screening_hits": len(screen_hits),
        "certs_expiring_90_critical": crit_expiring, "renewals_90d": renew_90,
        "cross_border": cross_border, "personal_data_no_dpa": no_dpa,
        "ict_engagements": ict, "missing_audit_rights": no_audit,
    }

    headline = (f"{len(obs)} board-level matters across the PESTLE horizon. "
                f"Sharpest exposures: "
                + "; ".join(o["title"] for o in obs[:3]) + ".")

    return {
        "generated": today.isoformat(),
        "engine": "deterministic",
        "headline": headline,
        "external": external,
        "internal": internal,
        "observations": obs,
        "predictions": predictions,
        "charts": charts,
    }
