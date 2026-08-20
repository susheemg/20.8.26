"""
Comprehensive enrichment of the demonstrator database (bro_demo.db).

Runs AFTER seed_demo.py. Fills every remaining form, table and child collection,
and enforces logical correlation so each data point connects:
  - all engagement-register groups populated (origination..lifecycle)
  - engagement children: deliverables, milestones, SLAs, obligations, personnel
  - vendor contacts + industries
  - full assessment IRQ/DDQ structured data
  - findings -> remediation plans; expired certs -> issues; breaches/adverse media/
    financial distress -> matching findings; SLA breaches -> performance findings
  - notifications, monitoring enrolment, performance-review meetings
Idempotent-ish: safe to re-run on a fresh seed.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("BRO_TRUST_HEADER", "1")
os.environ.pop("ANTHROPIC_API_KEY", None)

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

import app.bro_app as ba
from app.features import registry_service as RS
from app.features import master_service as MS
from app.features import master_ext as MX
from app.features import financial as FIN
from app.features import models_feature as MF
from app.features.models_feature import AuditLog
from app.features.bro_engine import chain_hash
from app.features.registry_models import (
    VendorRecord, EngagementRecord, AssessmentRecord, FindingRecord,
    IssueRecord, ArtefactRecord, FinMonitorRecord, RemediationRecord,
    IndustryMaster, VendorIndustry,
)
from app.features.master_data import ID_PREFIX

def _seed_upstream(S):
    """Seed a small ecosystem layer: some vendors are declared as fourth parties by
    other vendors, so War Room "upstream vendors" has data."""
    from app.features.registry_models import VendorRecord, FourthPartyRecord, FourthPartyVendor
    from app.features import registry_service as RS
    import hashlib
    vendors = [v.vendor_id for v in S.query(VendorRecord).all()]
    if len(vendors) < 20:
        return 0
    def h(*p):
        return int(hashlib.sha1("|".join(map(str, p)).encode()).hexdigest(), 16)
    providers = list(dict.fromkeys(vendors[(h("up-prov", i) % len(vendors))] for i in range(12)))[:12]
    existing_fp = {f.vendor_id: f.fourth_party_id for f in S.query(FourthPartyRecord)
                   .filter(FourthPartyRecord.vendor_id.isnot(None)).all()}
    links_seen = {(l.fourth_party_id, l.vendor_id) for l in S.query(FourthPartyVendor).all()}
    added = 0
    for pv in providers:
        vr = S.query(VendorRecord).filter_by(vendor_id=pv).first()
        fid = existing_fp.get(pv)
        if not fid:
            fid = RS.next_id(S, "fourth_party")
            S.add(FourthPartyRecord(fourth_party_id=fid, legal_name=(vr.legal_name if vr else pv),
                  service_provided="Shared platform / infrastructure", vendor_id=pv,
                  concentration_flag=True)); S.flush()
            existing_fp[pv] = fid
        n = 3 + (h("up-n", pv) % 4); used = 0
        for k in range(n * 3):
            uv = vendors[(h("up-link", pv, k) % len(vendors))]
            if uv == pv or (fid, uv) in links_seen:
                continue
            links_seen.add((fid, uv)); S.add(FourthPartyVendor(fourth_party_id=fid, vendor_id=uv))
            added += 1; used += 1
            if used >= n:
                break
    S.flush()
    return added


random.seed(7)
DB = "sqlite:///" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "bro_demo.db")


def off(days):
    from datetime import date, timedelta
    return (date.today() + timedelta(days=days)).isoformat()


def main():
    ba.create_app(DB)
    s = Session(create_engine(DB))

    vendors = list(s.scalars(select(VendorRecord)).all())
    vmap = {v.vendor_id: v for v in vendors}
    engs = list(s.scalars(select(EngagementRecord)).all())
    OWNERS = ["VRM Owner 1", "VRM Owner 2", "Sourcing Owner 1", "Sourcing Owner 2", "Resilience Owner 1", "Resilience Owner 2"]
    ASSESSORS = ["Risk Assessor 1", "Risk Assessor 2", "Risk Assessor 3"]
    industries = [row[0] for row in s.execute(select(IndustryMaster.id)).all()]

    GOV_FORUM = ["Quarterly Service Review", "Monthly Ops Forum", "Exec Steering Committee", "Annual Risk Review"]
    PRICING = ["Fixed fee", "Time & materials", "Consumption-based", "Subscription", "Per-transaction"]
    PAYTERMS = ["Net 30", "Net 45", "Net 60", "Net 90"]
    DATACLASS = ["Public", "Internal", "Confidential", "Restricted", "Highly Restricted"]
    SENT = ["Positive", "Neutral", "Strained", "At risk"]

    crit_vendor_ids = [v.vendor_id for v in vendors if v.is_critical]

    # =====================================================================
    # 1) FULL ENGAGEMENT REGISTER — every group, correlated to inherent band
    # =====================================================================
    sla_breach_engs = set()
    for e in engs:
        band = e.inherent_band or "MODERATE"
        v = vmap.get(e.vendor_id)
        hi = band in ("HIGH", "ELEVATED")
        ext = MS.get_or_create_eng_ext(s, e.engagement_id)
        crit_eng = _is_crit_eng(s, e.engagement_id)
        data = {
            # origination
            "business_justification": f"Procurement of {e.title.split(' #')[0].lower()} to support business operations.",
            "requested_by": random.choice(OWNERS), "procurement_category": v.tier if v else "Tier 3",
            "sourcing_route": random.choice(["Competitive tender", "Direct award", "Framework call-off", "Renewal"]),
            "competitive_flag": random.choice([True, False]),
            "competitive_rationale": "Selected on best value against evaluation criteria.",
            "requisition_ref": f"REQ-{random.randint(10000,99999)}", "business_case_ref": f"BC-{random.randint(1000,9999)}",
            # contract
            "contract_reference": f"CTR-{random.randint(10000,99999)}",
            "agreement_type": "MSA + SOW" if hi else random.choice(["Contract", "Order Form", "SOW"]),
            "signatories": f"{random.choice(OWNERS)} / {(v.legal_name if v else 'Vendor')} authorised signatory",
            "governing_law": random.choice(["England & Wales", "New York", "Ireland", "Singapore"]),
            "governing_language": "English",
            "execution_date": off(-random.randint(120, 900)), "effective_date": off(-random.randint(90, 800)),
            "initial_term": random.choice(["12 months", "24 months", "36 months"]),
            "renewal_type": random.choice(["Auto-renew", "Mutual", "None"]),
            "renewal_window": random.choice(["30 days", "60 days", "90 days"]),
            "notice_period": random.choice(["30 days", "60 days", "90 days"]),
            "termination_rights": "For cause and for convenience with notice.",
            "cure_period": random.choice(["15 days", "30 days"]), "change_of_control": True,
            "assignment_rights": "Not without prior written consent",
            "clause_flags": "Liability cap, audit rights, exit assistance, DP addendum",
            "contract_status": random.choice(["Executed", "Executed", "In renewal", "In negotiation"]),
            "contract_version": f"v{random.randint(1,4)}.0",
            # scope
            "scope_in": f"Provision, support and maintenance of {e.title.split(' #')[0].lower()}.",
            "scope_out": "Hardware procurement; third-party licences not listed.",
            "objectives": "Reliable, secure delivery meeting agreed service levels.",
            "assumptions": "Stable requirements; timely access provided.",
            "dependencies": "Network connectivity; identity provider integration.",
            "change_control_ref": f"CC-{random.randint(100,999)}",
            # service
            "service_type": ext.service_type or e.title.split(" #")[0],
            "supported_function": random.choice(["Trading", "Settlements", "Client Onboarding", "Finance", "HR", "Risk"]),
            "function_criticality": "Critical" if crit_eng else ("Important" if hi else "Standard"),
            "ict_flag": random.choice([True, True, False]),
            "integration_points": random.choice(["API", "SFTP", "SSO/SAML", "Direct DB", "File exchange"]),
            # financial
            "tcv": (e.annual_value or 100000) * random.choice([1, 2, 3]),
            "acv": e.annual_value or 100000, "pricing_model": random.choice(PRICING),
            "rate_card": "Agreed rate card v2", "indexation_terms": "CPI-linked, capped at 4%",
            "payment_terms": random.choice(PAYTERMS), "invoicing_frequency": random.choice(["Monthly", "Quarterly"]),
            "discounts": random.choice(["Volume tier", "Early payment 2%", "None"]),
            "fx_terms": "GBP/USD",
            "budget_allocation": random.choice(["OPEX", "CAPEX"]),
            "po_numbers": f"PO-{random.randint(100000,999999)}",
            "committed_spend": e.annual_value or 100000,
            "actual_spend": int((e.annual_value or 100000) * random.uniform(0.6, 1.05)),
            # governance
            "engagement_owner": e.owner_user or random.choice(OWNERS),
            "vendor_account_manager": f"{(v.legal_name.split()[0] if v else 'Vendor')} Account Team",
            "governance_forum": random.choice(GOV_FORUM),
            "governance_cadence": random.choice(["Monthly", "Quarterly", "Bi-annual"]),
            "escalation_path": "Engagement Owner → VRM Lead → Exec Sponsor",
            "raci": "Owner=A, Vendor=R, VRM=C, Exec=I",
            "relationship_sentiment": random.choice(SENT),
            "performance_reporting_cadence": random.choice(["Monthly", "Quarterly"]),
            # risk
            "data_classification": "Highly Restricted" if crit_eng else random.choice(DATACLASS),
            "data_volume": random.choice(["<10k", "10k-100k", "100k-1m", ">1m"]),
            "personal_data": bool(ext.personal_data) or hi,
            "data_subject_types": random.choice(["Employees", "Customers", "Both", "None"]),
            "system_access": random.choice(["None", "Read", "Read/Write", "Privileged"]),
            "physical_access": random.choice([True, False]),
            "mission_critical": hi, "cross_border": bool(ext.cross_border),
            "regulated_activity": random.choice([True, False]),
            "fourth_party_reliance": random.choice([True, True, False]),
            "concentration_contribution": "High" if crit_eng else random.choice(["Medium", "Low"]),
            # resilience
            "rto": random.choice(["2h", "4h", "8h", "24h"]), "rpo": random.choice(["15m", "1h", "4h"]),
            "bcp_dependency": random.choice(["Critical", "Important", "Standard"]),
            "exit_plan": "Documented and tested" if crit_eng else random.choice(["Documented", "Draft", "Not started"]),
            "exit_plan_tested": crit_eng or random.random() < 0.3,
            "transition_in_status": "Complete", "alternative_provider": random.choice(["Identified", "None", "In discovery"]),
            # compliance
            "dpa_in_place": bool(ext.personal_data) and random.random() < 0.85,
            "audit_rights": True, "audit_last_exercised": off(-random.randint(60, 700)),
            "required_clauses_present": random.choice([True, True, False]),
            "insurance_evidenced": random.random() < 0.8,
            "regulatory_notifications": random.choice(["N/A", "FCA notified", "Pending"]),
            # lifecycle
            "engagement_stage": e.status or "Active",
            "approval_status": random.choice(["Approved", "Approved", "Pending"]),
            "approver": random.choice(OWNERS), "approval_date": off(-random.randint(30, 400)),
            "go_live_date": off(-random.randint(30, 600)),
            "next_review_date": off(random.randint(20, 300)),
            "review_cadence": "Annual" if hi else "Biennial",
            "renewal_decision": random.choice(["Renew", "Renew", "Under review", "Exit"]),
            "end_date": off(random.randint(200, 1000)), "transition_status": "N/A",
            "data_steward": random.choice(OWNERS),
        }
        MS.update_eng_ext(s, e.engagement_id, data)

        # ---- engagement children (richer for critical/high) ----
        n_child = 3 if (crit_eng or hi) else 1
        for i in range(n_child):
            MS.add_eng_child(s, e.engagement_id, "deliverable", {
                "description": random.choice(["Service operational readiness", "Quarterly service report",
                                              "Implementation & integration", "Knowledge transfer pack"]),
                "due_date": off(random.randint(-200, 200)), "acceptance_criteria": "Signed-off by engagement owner",
                "accountable_owner": random.choice(OWNERS),
                "status": random.choice(["Complete", "Complete", "In progress", "Planned"])})
        MS.add_eng_child(s, e.engagement_id, "milestone", {
            "name": "Go-live", "due_date": off(-random.randint(10, 400)),
            "acceptance": "Production acceptance", "payment_trigger": 30.0,
            "status": "Achieved"})
        # SLAs — some breached (drives performance findings)
        breached = (random.random() < 0.22)
        if breached:
            sla_breach_engs.add((e.engagement_id, e.vendor_id))
        MS.add_eng_child(s, e.engagement_id, "sla", {
            "metric": "Availability", "target": "99.9%", "measurement_window": "Monthly",
            "calculation": "Uptime / total time", "credit_penalty": "5% monthly fee per 0.1% below",
            "current_value": "99.6%" if breached else "99.95%", "breach_flag": breached})
        MS.add_eng_child(s, e.engagement_id, "sla", {
            "metric": "P1 response time", "target": "15 min", "measurement_window": "Per incident",
            "calculation": "Time to acknowledge", "credit_penalty": "Service credit",
            "current_value": "12 min", "breach_flag": False})
        MS.add_eng_child(s, e.engagement_id, "obligation", {
            "description": "Provide annual SOC 2 report", "obligated_party": "Vendor",
            "obl_type": "Assurance", "due_date": off(random.randint(30, 300)), "recurrence": "Annual",
            "accountable_owner": random.choice(ASSESSORS), "status": "On track",
            "consequence": "Escalation; potential breach notice", "alert_rule": "30 days before due"})
        if crit_eng or hi:
            MS.add_eng_child(s, e.engagement_id, "obligation", {
                "description": "Notify of material subcontractor changes", "obligated_party": "Vendor",
                "obl_type": "Notification", "recurrence": "As required", "status": "On track",
                "accountable_owner": random.choice(OWNERS)})
        MS.add_eng_child(s, e.engagement_id, "personnel", {
            "name": random.choice(["A. Patel", "J. Murphy", "L. Schmidt", "R. Tan", "C. Rossi"]),
            "role": random.choice(["Service Delivery Manager", "Technical Lead", "Account Director"]),
            "key_personnel": True, "vetting_status": random.choice(["BPSS", "SC", "Completed"]),
            "access_level": random.choice(["Standard", "Privileged"]),
            "location": random.choice(["UK", "India", "US", "Ireland"]), "jml_status": "Active"})
    s.commit()
    print("engagement register + children: done")

    # =====================================================================
    # 2) VENDOR CONTACTS + INDUSTRIES + MONITORING ENROLMENT
    # =====================================================================
    for v in vendors:
        # industries
        if industries:
            s.add(VendorIndustry(vendor_id=v.vendor_id, industry_id=random.choice(industries)))
        # contacts (primary + secondary)
        first = v.legal_name.split()[0]
        RS.add_contact(s, owner_type="vendor", owner_id=v.vendor_id, name=f"{first} Relationship Lead",
                       is_primary=True, email=f"relationship@{_dom(v.legal_name)}",
                       phone_country_code="+1", phone_number=f"{random.randint(2000000000,9999999999)}",
                       designation="Account Director", country="United States")
        RS.add_contact(s, owner_type="vendor", owner_id=v.vendor_id, name=f"{first} Security Contact",
                       is_primary=False, email=f"security@{_dom(v.legal_name)}",
                       designation="CISO Office", country="United States")
        # ---- background research: monitoring + FDD + reputation for EVERY vendor ----
        mx = s.scalars(select(MX.VendorMasterExt).where(MX.VendorMasterExt.vendor_id == v.vendor_id)).first()
        # SYNTHETIC (demonstrator) FDD: coherent figures -> real FDD engine -> derived band
        if mx and mx.financial_health_band:
            fh = mx.financial_health_band
        else:
            _figs, _flags = _synth_financials(v.vendor_id, v.tier, getattr(v, "listing_status", None))
            try:
                _fin = FIN.assess_financials(_figs, _flags)
                MS.persist_fdd(s, v.vendor_id, _fin)
                fh = _fin.get("banding") or "Stable"
            except Exception:
                fh = random.choice(["Strong", "Healthy", "Stable", "Caution", "Weak"])
        # financial monitoring sweep record
        if not s.scalars(select(FinMonitorRecord).where(FinMonitorRecord.vendor_id == v.vendor_id)).first():
            res = "watch" if fh in ("Watch", "Distressed") else "stable"
            s.add(FinMonitorRecord(vendor_id=v.vendor_id, entity_name=v.legal_name,
                                   last_result=res, last_signal="financial_health",
                                   last_swept=off(-random.randint(1, 30))))
        # monitoring signals (cyber rating, financial health, adverse-media sweep)
        cy = s.scalars(select(MX.VendorCyber).where(MX.VendorCyber.vendor_id == v.vendor_id)).first()
        rating = (cy.rating if cy and getattr(cy, "rating", None) else None) or random.choice(["A", "A", "B", "B", "C"])
        for stype, sval, src in [
            ("cyber_rating", str(rating), "SecurityScorecard-style feed"),
            ("financial_health", fh, "RapidRatings-style feed"),
            ("adverse_media", ("clear" if random.random() < 0.82 else "flagged"), "Dow-Jones-style screening"),
        ]:
            s.add(MX.VendorMonitorSignal(vendor_id=v.vendor_id, signal_type=stype, value=sval,
                                      source=src, captured_at=off(-random.randint(1, 45))))
        # reputation verdict (baseline; screening-hit vendors are escalated later)
        rep_overall = random.randint(78, 95) if fh in ("Strong", "Adequate") else random.randint(55, 78)
        MS.persist_reputation(s, v.vendor_id,
                              {"verdict": "Acceptable" if rep_overall >= 70 else "Caution", "overall": rep_overall})
    s.commit()
    print("contacts + industries + monitoring + FDD + reputation (all 100 vendors): done")

    # ---- fourth-party detail (service / HQ / website) so the drill-down is complete ----
    from app.features.registry_models import FourthPartyRecord as _FPR
    _FP_DETAIL = {
        "aws": ("Cloud infrastructure (IaaS)", "United States", "aws.amazon.com"),
        "amazon web services": ("Cloud infrastructure (IaaS)", "United States", "aws.amazon.com"),
        "microsoft": ("Cloud platform (Azure)", "United States", "azure.microsoft.com"),
        "azure": ("Cloud platform (Azure)", "United States", "azure.microsoft.com"),
        "google": ("Cloud platform (GCP)", "United States", "cloud.google.com"),
        "equinix": ("Data-centre colocation", "United States", "equinix.com"),
        "twilio": ("Communications API / messaging", "United States", "twilio.com"),
        "cloudflare": ("CDN / edge security", "United States", "cloudflare.com"),
        "okta": ("Identity & access management", "United States", "okta.com"),
        "stripe": ("Payment processing", "United States", "stripe.com"),
    }
    for fp in s.scalars(select(_FPR)).all():
        nm = (fp.legal_name or "").lower()
        svc, hq, web = ("Specialist sub-processor", random.choice(["United States", "Ireland", "United Kingdom", "India"]), None)
        for kfrag, det in _FP_DETAIL.items():
            if kfrag in nm:
                svc, hq, web = det
                break
        fp.service_provided = fp.service_provided or svc
        fp.hq_country = fp.hq_country or hq
        if web and not fp.website:
            fp.website = web
        fp.listing_status = fp.listing_status or random.choice(["Public", "Private"])
    s.commit()
    print("fourth-party detail: done")

    # =====================================================================
    # CONTRACT & MSA DOCUMENTS — draft documents linked to engagements + MSAs to vendors
    # =====================================================================
    import base64 as _b64
    from app.features import documents as DOC
    from app.features.master_ext import ContractRecord as _CR

    OWNERS_SIG = ["Procurement Approver 1 (Procurement)", "Legal Approver 1 (Legal)", "Executive Approver 1 (COO)"]

    def _msa_text(v):
        return (f"MASTER SERVICES AGREEMENT\n\n"
                f"This Master Services Agreement ('Agreement') is entered into between "
                f"the Firm ('Customer') and {v.legal_name} ('Supplier').\n\n"
                f"1. SCOPE. This Agreement governs all Statements of Work and engagements "
                f"placed with the Supplier and establishes the master commercial and risk terms.\n"
                f"2. TERM. Initial term of 36 months, auto-renewing for successive 12-month periods "
                f"unless terminated on 90 days' notice.\n"
                f"3. GOVERNING LAW. England & Wales.\n"
                f"4. LIABILITY. Aggregate liability capped at 150% of annual charges; uncapped for "
                f"breach of confidentiality, data protection and IP indemnity.\n"
                f"5. DATA PROTECTION. UK GDPR Data Processing Addendum incorporated; international "
                f"transfers under valid transfer mechanism only.\n"
                f"6. AUDIT RIGHTS. Customer and its regulators may audit the Supplier on 30 days' notice.\n"
                f"7. RESILIENCE & EXIT. Supplier shall maintain a tested BCP and provide exit assistance "
                f"for a minimum of 6 months on termination.\n"
                f"8. SUBCONTRACTING. Material subcontractor changes require prior written notice.\n\n"
                f"Tier classification: {v.tier}. Criticality: {'CRITICAL' if v.is_critical else 'Standard'}.\n"
                f"Signed for the Customer: {random.choice(OWNERS_SIG)}\n"
                f"Signed for the Supplier: {v.legal_name.split()[0]} authorised signatory\n")

    def _contract_text(e, v, ext):
        band = e.inherent_band or "MODERATE"
        crit = ext and getattr(ext, "mission_critical", False)
        return (f"SERVICE AGREEMENT / STATEMENT OF WORK — DRAFT\n\n"
                f"Engagement: {e.title}\nSupplier: {v.legal_name} ({v.vendor_id})\n"
                f"Engagement reference: {e.engagement_id}\n\n"
                f"1. SERVICES. The Supplier shall provide {getattr(ext,'service_type',None) or e.title} "
                f"to the Customer as further described in the engagement record.\n"
                f"2. VALUE. Annual contract value GBP {e.annual_value or 0:,}. "
                f"Pricing model: {getattr(ext,'pricing_model',None) or 'Fixed fee'}. "
                f"Payment terms: {getattr(ext,'payment_terms',None) or 'Net 30'}.\n"
                f"3. TERM. Commencing {getattr(ext,'effective_date',None) or 'on execution'}; "
                f"initial term {getattr(ext,'initial_term',None) or '24 months'}.\n"
                f"4. SERVICE LEVELS. Availability target 99.9%; P1 response 15 minutes; "
                f"service credits apply for breach.\n"
                f"5. DATA. Classification: {getattr(ext,'data_classification',None) or 'Confidential'}; "
                f"personal data {'IS' if (ext and ext.personal_data) else 'is NOT'} processed; "
                f"cross-border transfer {'applies' if (ext and ext.cross_border) else 'does not apply'}.\n"
                f"6. RISK. Inherent risk band {band}; "
                f"{'mission-critical service — enhanced resilience and exit obligations apply' if crit else 'standard control set applies'}.\n"
                f"7. GOVERNING LAW. {getattr(ext,'governing_law',None) or 'England & Wales'}.\n"
                f"8. INCORPORATION. This SOW is governed by and incorporates the Master Services "
                f"Agreement between the parties.\n\n"
                f"Status: DRAFT for review. Prepared {off(0)} by BRO Risk Oracle.\n")

    n_msa = n_ctr = 0
    for v in vendors:
        # one MSA document per vendor
        raw = _msa_text(v).encode()
        doc = DOC.store_document(s, filename=f"MSA_{v.vendor_id}.txt", content_type="text/plain",
                                 data_b64=_b64.b64encode(raw).decode(),
                                 vendor_id=v.vendor_id, uploaded_by="VRM Owner 2", purpose="contract")
        link = f"/api/v2/documents/{doc.doc_id}"
        msa = s.scalars(select(_CR).where(_CR.vendor_id == v.vendor_id,
                                          _CR.contract_type == "MSA")).first()
        if msa:
            msa.doc_link = link
            msa.status = msa.status or "Executed"
        else:
            MS.create_contract(s, contract_type="MSA", vendor_id=v.vendor_id,
                               data={"title": "Master Services Agreement",
                                     "governing_law": "England & Wales", "doc_link": link,
                                     "status": "Executed", "is_critical": bool(v.is_critical)})
        n_msa += 1
    s.commit()

    for e in engs:
        v = vmap.get(e.vendor_id)
        if not v:
            continue
        ext = MS.get_or_create_eng_ext(s, e.engagement_id)
        raw = _contract_text(e, v, ext).encode()
        doc = DOC.store_document(s, filename=f"Contract_{e.engagement_id}.txt", content_type="text/plain",
                                 data_b64=_b64.b64encode(raw).decode(),
                                 engagement_id=e.engagement_id, vendor_id=e.vendor_id,
                                 uploaded_by="VRM Owner 1", purpose="contract")
        link = f"/api/v2/documents/{doc.doc_id}"
        ctr = s.scalars(select(_CR).where(_CR.engagement_id == e.engagement_id)).first()
        if ctr:
            ctr.doc_link = link
        else:
            msa = s.scalars(select(_CR).where(_CR.vendor_id == e.vendor_id,
                                              _CR.contract_type == "MSA")).first()
            MS.create_contract(s, contract_type="Contract", engagement_id=e.engagement_id,
                               parent_msa=(msa.contract_id if msa else None),
                               data={"title": f"Service Agreement — {e.title}",
                                     "governing_law": getattr(ext, "governing_law", None) or "England & Wales",
                                     "value": e.annual_value, "doc_link": link,
                                     "status": "Draft" if e.status == "Onboarding" else "Executed"})
        # reflect on engagement ext for the register
        MS.update_eng_ext(s, e.engagement_id, {"contract_doc_link": link, "contract_status": "Executed"})
        n_ctr += 1
    s.commit()
    print(f"contract documents: {n_msa} MSAs + {n_ctr} draft contracts (linked to vendors / engagements)")

    # =====================================================================
    # 3) FULL ASSESSMENT IRQ/DDQ — in the model's own schema, band DERIVED
    #    so scoring the stored IRQ reproduces the stored band (reconciles).
    # =====================================================================
    from app.features.bro_engine import (compute_inherent, compute_residual,
                                          compute_tier, decision_for,
                                          IRQ_QUESTIONS, DDQ_DOMAINS)
    Q4OPTS = next(q["options"] for q in IRQ_QUESTIONS if q["id"] == "Q4")  # exact dash strings
    VOL = {"low": Q4OPTS[0], "mod": Q4OPTS[1], "ele": Q4OPTS[2], "hi": Q4OPTS[3]}
    crit_ids = {v.vendor_id for v in vendors if v.is_critical}
    DDQ_QIDS = [(q["id"], d["id"], q.get("critical", False))
                for d in DDQ_DOMAINS for q in d["questions"]]

    def _irq_for(level, sanctions=False):
        if level == "hi":
            return {"Q1": "Yes" if sanctions else "No", "Q2": "Mission-critical",
                    "Q3": ["Personal", "Confidential", "Payment Card"], "Q4": VOL["hi"],
                    "Q5": "Yes", "Q6": "Yes", "Q7": random.choice(["Yes", "No"]),
                    "Q8": "Sole source", "Q9": "Yes", "Q10": "Yes",
                    "Q11": "DORA, UK GDPR, PCI-DSS", "Q12": random.choice(["Yes", "No"])}
        if level == "ele":
            return {"Q1": "No", "Q2": "Important", "Q3": ["Personal", "Confidential"],
                    "Q4": VOL["ele"], "Q5": "Yes", "Q6": "Yes", "Q7": "No",
                    "Q8": "Difficult", "Q9": random.choice(["Yes", "No"]), "Q10": "Yes",
                    "Q11": "UK GDPR", "Q12": "No"}
        if level == "mod":
            return {"Q1": "No", "Q2": "Important", "Q3": ["Personal"], "Q4": VOL["mod"],
                    "Q5": "No", "Q6": "Yes", "Q7": "No", "Q8": "Difficult", "Q9": "No",
                    "Q10": "No", "Q11": "", "Q12": "No"}
        return {"Q1": "No", "Q2": "Standard", "Q3": ["None"], "Q4": VOL["low"],
                "Q5": "No", "Q6": "No", "Q7": "No", "Q8": "Easy", "Q9": "No",
                "Q10": "No", "Q11": "", "Q12": "No"}

    def _ddq_for(band):
        # choose an overall control quality, then emit a flat {qid: response} that
        # produces a realistic residual: good -> residual == inherent;
        # some -> one notch worse; serious -> HIGH (critical control gap).
        roll = random.random()
        if band == "HIGH":       good, some = 0.50, 0.88
        elif band == "ELEVATED": good, some = 0.64, 0.94
        elif band == "MODERATE": good, some = 0.78, 0.97
        else:                    good, some = 0.90, 0.99
        quality = "good" if roll < good else "some" if roll < some else "serious"
        resp = {qid: "COMPLIANT" for qid, dom, isc in DDQ_QIDS}
        noncrit = [qid for qid, dom, isc in DDQ_QIDS if not isc]
        crit = [qid for qid, dom, isc in DDQ_QIDS if isc]
        if quality == "some":
            for qid in random.sample(noncrit, min(random.randint(1, 2), len(noncrit))):
                resp[qid] = "PARTIAL"
        elif quality == "serious":
            resp[random.choice(crit)] = "MARGINAL"        # forces HIGH residual
            for qid in random.sample(noncrit, min(2, len(noncrit))):
                resp[qid] = "PARTIAL"
        return resp

    eng_by_id = {e.engagement_id: e for e in s.scalars(select(EngagementRecord)).all()}
    asmts = list(s.scalars(select(AssessmentRecord)).all())
    sanction_quota = 4  # a few sanctions-exposed engagements (force HIGH via the model)
    for a in asmts:
        is_crit = a.vendor_id in crit_ids
        roll = random.random()
        if is_crit:
            level = "hi" if roll < 0.35 else "ele" if roll < 0.75 else "mod"
        else:
            level = "hi" if roll < 0.08 else "ele" if roll < 0.33 else "mod" if roll < 0.75 else "low"
        sanctions = False
        if level == "hi" and sanction_quota > 0 and random.random() < 0.5:
            sanctions = True; sanction_quota -= 1
        irq = _irq_for(level, sanctions)

        inh = compute_inherent(irq)            # <-- model derives the band
        tier = compute_tier(irq)
        band = inh["band"]
        ddq = _ddq_for(band)
        res = compute_residual(band, ddq)       # <-- model derives residual
        residual_band = res["band"]
        # logical clamp: residual is never worse than inherent (consistent everywhere)
        _ordr = ["LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL"]
        def _rr(b):
            b = (b or "").upper().replace("MEDIUM", "MODERATE")
            return _ordr.index(b) if b in _ordr else 0
        if _rr(residual_band) > _rr(band):
            residual_band = band
        dec = decision_for(residual_band, res["critical_marginal"])

        # write the DERIVED bands back to the assessment AND its engagement
        a.inherent_band = band
        a.residual_band = residual_band
        eng = eng_by_id.get(a.engagement_id)
        if eng:
            eng.inherent_band = band
            eng.residual_band = residual_band
            # record last assessment date (spread into the past) + next due auto-calculated
            # from the configured cadence rule (Low=3y, Medium=2y, Elevated/High/Critical=annual)
            from datetime import date as _date, timedelta as _td
            _last = _date.today() - _td(days=random.randint(20, 400))
            eng.last_assessment_date = _last.isoformat()
            eng.next_assessment_due = RS.add_months_iso(
                eng.last_assessment_date, RS.cadence_months_for(s, band))

        a.structured_json = json.dumps({
            "source": "assessment", "schema": "irq-v1",
            "irq": irq, "ddq": ddq,
            "tier": tier,
            "domain_scores": inh["domains"], "weighted_pct": inh["weighted_pct"],
            "inherent_band": band, "completeness_cls": inh["cls"],
            "residual": {"band": residual_band, "partial": res["partial"],
                         "marginal": res["marginal"], "critical_marginal": res["critical_marginal"]},
            "recommendation": dec["text"], "verdict": dec["text"], "route": dec["route"],
            "scope_summary": (f"{band} inherent → {residual_band} residual; "
                              f"{sum(1 for v in ddq.values() if v!='COMPLIANT')} control gap(s) across "
                              f"{len(DDQ_DOMAINS)} domains."),
        })
        a.engagement_owner = a.engagement_owner or random.choice(OWNERS)
        a.spoc_name = "Vendor SPOC"; a.spoc_email = "spoc@vendor.example"
        if band in ("HIGH", "ELEVATED") and not a.assessor_user:
            a.assessor_user = random.choice(ASSESSORS)
        if a.status == "Completed":
            a.assessor_signed_off = True; a.locked = random.random() < 0.6
            a.outcome = a.outcome or dec["text"]
    s.commit()
    print("assessment IRQ/DDQ (model schema, derived & reconciled bands): done")

    # =====================================================================
    # 4) CORRELATION PASS — make every signal produce its consequence
    # =====================================================================
    def add_finding(vid, title, sev, dom, eid=None, status="Open"):
        return RS.create_finding(s, title=title, severity=sev, vendor_id=vid,
                                 status=status, source="Correlation", domain=dom,
                                 engagement_id=eid)

    # (a) breach history -> InfoSec finding
    for v in vendors:
        cy = s.scalars(select(MX.VendorCyber).where(MX.VendorCyber.vendor_id == v.vendor_id)).first()
        if cy and cy.breach_history_flag:
            add_finding(v.vendor_id, "Disclosed security breach in vendor history — assurance review required",
                        "High", "infosec")
    # (b) adverse-media / sanctions screening hit -> reputation signal + finding
    for v in vendors:
        for sc in s.scalars(select(MX.VendorScreening).where(MX.VendorScreening.vendor_id == v.vendor_id)).all():
            if (sc.result or "").lower() == "hit":
                dom = "reputation" if "media" in (sc.screen_type or "") else "compliance"
                add_finding(v.vendor_id, f"Screening hit ({sc.screen_type}) requires disposition", "High", dom)
                MS.persist_reputation(s, v.vendor_id, {"verdict": "Adverse", "overall": random.randint(35, 55)})
    # (c) financial distress band -> FDD finding
    for v in vendors:
        mx = s.scalars(select(MX.VendorMasterExt).where(MX.VendorMasterExt.vendor_id == v.vendor_id)).first()
        if mx and (mx.financial_health_band or "") in ("Weak", "Distress", "Caution"):
            add_finding(v.vendor_id, f"Financial health {mx.financial_health_band} — enhanced monitoring", "Medium", "financial")
    # (d) SLA breaches -> performance finding (linked to engagement)
    for eid, vid in sla_breach_engs:
        add_finding(vid, "SLA availability breach in reporting period — service credits due", "Medium", "performance", eid=eid)
    s.commit()
    print("correlation findings: done")

    # =====================================================================
    # 5) EXPIRED CERTIFICATES -> ISSUES (via revalidation), + remediation plans
    # =====================================================================
    # backdate a slice of certificates to expired so the revalidation engine opens issues
    arts = list(s.scalars(select(ArtefactRecord)).all())
    for art in random.sample(arts, min(18, len(arts))):
        art.expiry_date = off(-random.randint(40, 200))
        art.status = "Expired"
    s.commit()
    res = RS.revalidation_run(s)
    s.commit()
    print(f"revalidation: {len(res.get('new_issues', []))} expired-cert issues opened")

    # remediation plans for ~all High + half Medium open findings
    findings = list(s.scalars(select(FindingRecord).where(FindingRecord.status.in_(["Open", "In remediation"]))).all())
    made = 0
    for f in findings:
        if f.remediation_id:
            continue
        if f.severity == "High" or (f.severity == "Medium" and random.random() < 0.5):
            rem = RS.create_remediation(s, finding_id=f.finding_id,
                                        plan=f"Remediate: {f.title[:60]}",
                                        owner=random.choice(OWNERS), target_date=off(random.randint(20, 120)),
                                        status=random.choice(["Open", "In progress", "In progress"]),
                                        progress_pct=random.choice([0, 25, 50, 75]),
                                        milestones_json=json.dumps([
                                            {"m": "Root cause", "done": True},
                                            {"m": "Vendor remediation", "done": random.random() < 0.5},
                                            {"m": "Evidence & verify", "done": False}]))
            f.remediation_id = rem.remediation_id
            f.status = "In remediation"
            made += 1
    s.commit()
    print(f"remediation plans: {made}")

    # =====================================================================
    # 6) PERFORMANCE-REVIEW MEETINGS (tied to scorecards) + NOTIFICATIONS
    # =====================================================================
    scorecards = list(s.scalars(select(MX.VendorScorecard)).all())
    for sc in scorecards:
        if random.random() < 0.7:
            s.add(MX.PerformanceReview(
                review_id=f"PRV-{sc.scorecard_id[-4:]}-{random.randint(100,999)}",
                vendor_id=sc.vendor_id, scorecard_id=sc.scorecard_id,
                review_date=off(-random.randint(10, 200)), cadence="Quarterly",
                attendees="Engagement Owner, VRM Lead, Vendor Account Director",
                summary="Service performing to expectations; minor actions agreed.",
                outcomes="Continue; address open SLA action.", vendor_acknowledged=True,
                vendor_ack_date=off(-random.randint(5, 180)), next_review_date=off(random.randint(30, 120))))
    # notifications: expiry notices, new issues, approvals
    for i in res.get("new_issues", [])[:20]:
        s.add(MF.Notification(audience="vrm", event=f"Issue opened: expired certificate ({i['vendor_id']})", is_read=False))
    for n in res.get("notify_7day", [])[:10]:
        s.add(MF.Notification(audience="vrm", event=f"Certificate expiring within 7 days ({n['vendor_id']})", is_read=False))
    for a in random.sample(asmts, min(15, len(asmts))):
        s.add(MF.Notification(audience="all", event=f"Assessment {a.assessment_id} {a.outcome or 'completed'}", is_read=random.random() < 0.5))
    for v in crit_vendor_ids:
        s.add(MF.Notification(audience="exec", event=f"Critical vendor review due: {vmap[v].legal_name}", is_read=False))
    s.commit()
    print("performance reviews + notifications: done")

    # =====================================================================
    # 7) AUDIT TRAIL — realistic, correctly hash-chained activity log
    # =====================================================================
    import json as _json
    last = s.scalars(select(AuditLog).order_by(AuditLog.seq.desc())).first()
    prev = last.entry_hash if last else "genesis"
    seq = (last.seq + 1) if last else 0
    def _audit(action, actor, detail):
        nonlocal prev, seq
        h = chain_hash(prev, action, actor, detail)
        s.add(AuditLog(seq=seq, action=action, actor=actor,
                       detail=_json.dumps(detail, sort_keys=True), prev_hash=prev, entry_hash=h))
        prev = h; seq += 1
    for v in vendors:
        _audit("vendor.created", "demo-seed", {"vendor_id": v.vendor_id, "name": v.legal_name})
    for v in vendors:
        if v.is_critical:
            _audit("vendor.criticality_override", "VRM Owner 1",
                   {"vendor_id": v.vendor_id, "is_critical": True})
    for e in engs[:120]:
        _audit("engagement.created", e.owner_user or "VRM Owner 1",
               {"engagement_id": e.engagement_id, "vendor_id": e.vendor_id})
    for a in asmts:
        _audit("assessment.captured", a.assessor_user or a.engagement_owner or "Risk Assessor 1",
               {"assessment_id": a.assessment_id, "inherent": a.inherent_band, "residual": a.residual_band})
        if a.locked:
            _audit("assessment.approved", "Approver 1",
                   {"assessment_id": a.assessment_id, "outcome": a.outcome})
    for art in s.scalars(select(ArtefactRecord)).all():
        _audit("certificate.ingested", "Risk Assessor 1",
               {"artefact_id": art.artefact_id, "vendor_id": art.vendor_id, "name": art.name})
    for f in s.scalars(select(FindingRecord)).all():
        _audit("finding.raised", "Risk Assessor 2",
               {"finding_id": f.finding_id, "severity": f.severity, "domain": f.domain})
    for i in s.scalars(select(IssueRecord)).all():
        _audit("issue.opened", "system", {"issue_id": i.issue_id, "kind": i.kind})
    s.commit()
    print("audit trail: chained entries written")

    # ---- vendor-level exit strategies (CMORG-aligned) + auto-trigger scan ----
    from app.features import exit_planning as EX
    n_exit = EX.seed_demo_plans(s, vendors)
    s.commit()
    fired = EX.scan_triggers(s)
    s.commit()
    print(f"exit strategies: {n_exit} vendor plans + {fired} auto-triggers")

    # refresh profiles so Vendor 360 + dashboards reconcile after new findings/signals
    for v in vendors:
        try:
            MS.refresh_risk_profile(s, v.vendor_id)
        except Exception:
            pass
    s.commit()

    # ---- prior historical assessments (subset) so engagement history shows multiple, latest-first ----
    import datetime as _dt
    for e in list(s.scalars(select(EngagementRecord)).all())[:60]:
        for j in range(random.choice([1, 1, 2])):
            aid = RS.next_id(s, "assessment")
            days_ago = 430 + j * 365 + random.randint(15, 150)
            rec = AssessmentRecord(assessment_id=aid, engagement_id=e.engagement_id,
                                   vendor_id=e.vendor_id, status="Completed",
                                   inherent_band=e.inherent_band, residual_band=e.residual_band,
                                   outcome=random.choice(["Approved", "Approved with findings", "Approved with conditions"]),
                                   engagement_owner=random.choice(OWNERS),
                                   assessor_signed_off=True, locked=True)
            rec.created_at = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)
            s.add(rec)
    s.commit()

    # ---- final logical-consistency pass: residual never worse than inherent ----
    s.expire_all()
    from app.features.registry_models import EngagementRecord as _ERc, AssessmentRecord as _ARc
    _ordc = ["LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL"]
    def _rkc(bd):
        b = (bd or "").upper().replace("MEDIUM", "MODERATE")
        return _ordc.index(b) if b in _ordc else 0
    fixed = 0
    for rec in list(s.query(_ERc).all()) + list(s.query(_ARc).all()):
        if rec.inherent_band and rec.residual_band and _rkc(rec.residual_band) > _rkc(rec.inherent_band):
            rec.residual_band = rec.inherent_band
            fixed += 1
    s.commit()
    print(f"residual normalised: {fixed} record(s) clamped to <= inherent")
    from app.features import pestle as PES
    n_pestle = PES.build_all(s)
    s.commit()
    print(f"PESTLE threat vectors: {len(PES.THREATS)} dimensions x {n_pestle} entities + overnight sweep")
    from app.features import oss as OSS
    oss_res = OSS.seed_all(s)
    s.commit()
    print(f"OSS register: {oss_res['components']} components, {oss_res['sboms']} SBOMs, {oss_res['usages']} usages tagged to engagements")
    _n_up = _seed_upstream(s)
    s.commit()
    print(f"Ecosystem: {_n_up} upstream fourth-party dependency links seeded")
    s.close()
    print("\nENRICHMENT COMPLETE")


def _synth_financials(seed_key, tier, listing):
    """Deterministic, coherent SYNTHETIC financials for a demonstrator vendor.
    NOT real filings — generated so the FDD engine derives a logical band."""
    rr = random.Random(hash((seed_key, "fdd")) & 0x7fffffff)
    scale = {"Tier 1": 1.2e10, "Tier 2": 3.0e9, "Tier 3": 5.0e8, "Tier 4": 8.0e7}.get(tier, 5.0e8)
    rev = scale * rr.uniform(0.55, 1.6)
    # posture: sound (most) / marginal (Watch tier) / stressed (small tail)
    roll = rr.random()
    marg_cut = 0.14 if tier in ("Tier 1", "Tier 2") else 0.20
    stress_cut = marg_cut + (0.05 if tier in ("Tier 1", "Tier 2") else 0.11)
    marginal = roll < marg_cut
    stressed = marg_cut <= roll < stress_cut
    if not marginal and not stressed:
        gm = rr.uniform(0.52, 0.80)
        ebitda = rev * rr.uniform(0.20, 0.40)
        ebit = ebitda * rr.uniform(0.80, 0.92)
        interest = abs(ebit) * rr.uniform(0.03, 0.12)
        ta = rev * rr.uniform(0.70, 1.25)
        eq = ta * rr.uniform(0.48, 0.72)
        cash = ta * rr.uniform(0.08, 0.20)
        ca = ta * rr.uniform(0.42, 0.60)
        cl = ta * rr.uniform(0.12, 0.22)
        re = eq * rr.uniform(0.45, 0.80)
    elif marginal:
        gm = rr.uniform(0.34, 0.50)
        ebitda = rev * rr.uniform(0.08, 0.16)
        ebit = ebitda * rr.uniform(0.65, 0.85)
        interest = abs(ebit) * rr.uniform(0.25, 0.55)
        ta = rev * rr.uniform(1.1, 1.8)
        eq = ta * rr.uniform(0.24, 0.40)
        cash = ta * rr.uniform(0.04, 0.10)
        ca = ta * rr.uniform(0.34, 0.46)
        cl = ta * rr.uniform(0.28, 0.40)
        re = eq * rr.uniform(0.15, 0.45)
    else:
        gm = rr.uniform(0.16, 0.36)
        ebitda = rev * rr.uniform(-0.04, 0.08)
        ebit = ebitda * rr.uniform(0.55, 0.85)
        interest = abs(rev) * rr.uniform(0.02, 0.05) + 1.0
        ta = rev * rr.uniform(1.5, 2.6)
        eq = ta * rr.uniform(0.04, 0.18)
        cash = ta * rr.uniform(0.01, 0.06)
        ca = ta * rr.uniform(0.22, 0.38)
        cl = ta * rr.uniform(0.30, 0.55)
        re = eq * rr.uniform(-0.20, 0.30)
    gp = rev * gm
    cogs = rev - gp
    net_profit = (ebit - interest) * rr.uniform(0.6, 0.9)
    tl = ta - eq
    debt = tl * rr.uniform(0.30, 0.70)
    inv = ca * rr.uniform(0.05, 0.30)
    rec = ca * rr.uniform(0.20, 0.50)
    pay = cl * rr.uniform(0.20, 0.50)
    figs = {"revenue": rev, "cogs": cogs, "grossProfit": gp, "ebit": ebit, "ebitda": ebitda,
            "netProfit": net_profit, "interest": interest, "currentAssets": ca,
            "currentLiabilities": cl, "inventory": inv, "cash": cash, "totalAssets": ta,
            "totalDebt": debt, "equity": eq, "receivables": rec, "payables": pay,
            "netDebt": debt - cash, "totalLiabilities": tl, "retainedEarnings": re}
    flags = {}
    if stressed and rr.random() < 0.5:
        flags["goingConcern"] = rr.random() < 0.35
        flags["auditQualified"] = rr.random() < 0.4
    return figs, flags


def _dom(name):
    base = "".join(ch for ch in name.lower().split(",")[0].split("(")[0] if ch.isalnum())[:18]
    return f"{base or 'vendor'}.com"


def _is_crit_eng(s, eid):
    rows = s.scalars(select(MX.CriticalityDesignation).where(
        MX.CriticalityDesignation.subject_type == "engagement",
        MX.CriticalityDesignation.subject_id == eid).order_by(MX.CriticalityDesignation.id)).all()
    state = False
    for r in rows:
        state = r.is_critical
    return state


if __name__ == "__main__":
    main()
