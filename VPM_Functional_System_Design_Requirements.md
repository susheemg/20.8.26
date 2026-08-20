# Vendor Performance Management — Functional System Design Requirements

**Module:** Vendor Performance Management (VPM)
**Platform:** BRO Risk Oracle (Enterprise TPRM)
**Scope of application:** Critical vendors (and the critical engagements beneath them)
**Document type:** Functional System Design Requirements
**Status:** Specification for build — not yet implemented
**Version:** 1.0

---

## 1. Purpose and scope

### 1.1 Purpose

This document specifies the functional and system design requirements for a Vendor Performance Management (VPM) capability within BRO Risk Oracle. VPM operationalises accountability for the vendors that matter most: it measures multi-dimensional performance against agreed targets, governs the periodic review cycle, drives a closed-loop improvement process when performance falls short, and feeds the resulting performance signal into the vendor's consolidated risk profile.

The design follows the three principles that distinguish best-in-class practice from a conventional scorecard. Performance is managed continuously rather than as a periodic event; it is proportionate to vendor importance rather than uniform; and it is closed-loop and data-continuous, so that each stage of the lifecycle feeds the next.

### 1.2 Scope

VPM applies to vendors that the Critical Vendors module has designated as critical, and to the critical engagements that drive that designation. The critical designation produced by that module is the authoritative trigger for VPM: when a vendor is designated critical, a performance scorecard is established for it; when the designation is removed, active performance management is stood down but the historical record is retained.

This scoping is deliberate. Applying a full multi-dimensional performance regime uniformly across the entire vendor population is a recognised anti-pattern; the effort is concentrated where the operational dependency and risk exposure are greatest. Non-critical vendors remain out of scope for this module in its initial release, though the data model does not preclude a later lightweight tier.

### 1.3 Relationship to existing modules

VPM is explicitly not a standalone silo. It is the layer that reads from and writes to the surrounding capabilities already present in the platform:

- It **reads** Service Level Agreements and current performance from the Engagement Register (`EngagementSLA`, and the `current_performance` and `sla_breach_history` fields on `EngagementExt`).
- It **reads** the critical designation from the Critical Vendors module (the authoritative `is_critical` flag on `VendorRecord`).
- It **reads** financial-health signals from the Financial Due Diligence and Financial Monitoring engines, and certification status from the Vendor Attribute Database.
- It **reuses** the remediation and action infrastructure (`RemediationRecord` and the Action Plan) for closed-loop corrective actions, rather than creating a parallel task system.
- It **writes** the computed performance result back into the consolidated risk profile, populating the performance-rollup fields that already exist but are currently unpopulated on `VendorRiskProfile`: `sla_summary`, `incident_count`, `dispute_history`, `performance_score`, `review_cadence`, and `last_review`.

---

## 2. Definitions

**Critical vendor.** A vendor designated critical by the Critical Vendors module, on the basis of one or more critical engagements.

**Scorecard.** The structured, periodic assessment of a critical vendor's performance across all weighted dimensions for a defined measurement period, producing a composite score and band.

**Dimension.** A top-level category of performance (for example, Operational Performance). Each dimension carries a weight and aggregates one or more KPIs.

**KPI.** An individual key performance indicator within a dimension, with a metric definition, target, measurement window, calculation method, and data source.

**Composite score.** The weighted aggregate of dimension scores, expressed on a defined scale and mapped to a performance band.

**Performance review.** A governed, periodic meeting (typically a Quarterly Business Review) at which the scorecard is reviewed jointly with the vendor.

**Corrective action / Performance Improvement Plan (PIP).** A tracked remediation item raised against a performance gap, carrying a root cause, plan, owner, due date, escalation path, and verification of effectiveness.

**Closed loop.** The discipline whereby a performance gap leads to a corrective action whose effectiveness is subsequently measured and confirmed, rather than assumed.

---

## 3. Functional requirements

Functional requirements are enumerated with the prefix `FR-VPM` for traceability.

### 3.1 Scope and designation control

**FR-VPM-001.** The system shall establish a performance management profile automatically for any vendor designated critical by the Critical Vendors module.

**FR-VPM-002.** The system shall stand down active performance management when a vendor's critical designation is removed, while retaining all historical scorecards, reviews, and actions for that vendor.

**FR-VPM-003.** The system shall prevent the creation of a scorecard for a vendor that is not designated critical, returning a clear, actionable message rather than a silent failure.

**FR-VPM-004.** The system shall associate every scorecard with the specific critical engagement or engagements that contributed to the vendor's criticality, so that performance can be traced to the dependency that justifies the scrutiny.

### 3.2 Scorecard model — dimensions and KPIs

**FR-VPM-010.** The system shall support a multi-dimensional scorecard covering, at minimum, the following dimensions: Operational Performance; Financial and Commercial Value; Relationship and Collaboration; Compliance and Risk; Financial Stability; and Sustainability and ESG. An Innovation and Strategic Contribution dimension shall be supported and applied at the assessor's discretion for the most strategic relationships.

**FR-VPM-011.** The system shall allow each dimension to carry a configurable weight, such that the weights across active dimensions sum to one hundred percent for a given scorecard.

**FR-VPM-012.** The system shall allow each dimension to contain one or more KPIs, where each KPI carries a metric name, a definition, a target or benchmark, a measurement window, a calculation method, a data source, and a weight within its dimension.

**FR-VPM-013.** The system shall provide a default KPI library for each dimension as a starting template, while allowing KPIs to be added, removed, or amended per vendor or per engagement to reflect what was actually agreed.

**FR-VPM-014.** The system shall support the following representative KPIs as defaults, without limiting the set: on-time delivery and schedule adherence, SLA attainment, quality and defect or error rate, and responsiveness under Operational Performance; cost savings, billing accuracy, and pricing adherence under Financial and Commercial Value; responsiveness, proactivity, flexibility, and governance participation under Relationship and Collaboration; contractual adherence, certification status, and audit findings under Compliance and Risk; credit rating and financial-health band under Financial Stability; and carbon disclosure, labour standards, and environmental certification under Sustainability and ESG.

### 3.3 Targets, agreement, and transparency

**FR-VPM-020.** The system shall require that a scorecard's KPIs, targets, weights, and review cadence are defined before the first measurement period begins.

**FR-VPM-021.** The system shall support an explicit "agreed with vendor" state on a scorecard definition, recording that the criteria and weighting were shared with the vendor in advance, together with the date and the acknowledging party. A scorecard is intended as a roadmap for performance, not a measure applied retrospectively without the vendor's knowledge.

**FR-VPM-022.** The system shall make the agreed scorecard definition visible to authorised internal users and shall support exporting it for sharing with the vendor.

### 3.4 Scoring and weighting engine

**FR-VPM-030.** The system shall score each KPI on a consistent, configurable rating scale (defaulting to one-to-five), with a clear textual descriptor for each scale point so that scoring is repeatable rather than subjective.

**FR-VPM-031.** The system shall compute a dimension score as the weighted aggregate of its KPI scores, and a composite vendor score as the weighted aggregate of dimension scores.

**FR-VPM-032.** The scoring computation shall be deterministic: identical inputs shall always produce an identical composite score and band, independent of any external service or network connectivity.

**FR-VPM-033.** The system shall map the composite score to a performance band (for example, Strong, Adequate, Watch, Underperforming) using configurable thresholds, and shall surface the band alongside the numeric score.

**FR-VPM-034.** Where a KPI cannot be scored for a period because data is unavailable, the system shall exclude it from the weighted aggregation and re-normalise the remaining weights, rather than scoring it as zero, and shall flag the exclusion.

### 3.5 Data capture

**FR-VPM-040.** The system shall capture KPI actuals from three sources: automatically from existing platform data where it exists; from internal stakeholder input; and from vendor self-reported data where applicable. The source of each KPI actual shall be recorded.

**FR-VPM-041.** The system shall source operational KPIs automatically from the Engagement Register, including SLA attainment and breach history from `EngagementSLA` and the engagement extension, so that contracted service levels feed performance without re-keying.

**FR-VPM-042.** The system shall source the Financial Stability dimension automatically from the Financial Due Diligence health band and the Financial Monitoring signal for the vendor.

**FR-VPM-043.** The system shall source the Compliance and Risk dimension from the Vendor Attribute Database, including current certification status and open findings.

**FR-VPM-044.** The system shall allow manual entry and override of any KPI actual by an authorised user, recording the actor, timestamp, and any supporting note, while preserving the automatically sourced value for comparison.

### 3.6 Performance review cadence and governance

**FR-VPM-050.** The system shall support a configurable review cadence per vendor, defaulting to quarterly for critical vendors, and shall schedule and track the next review date.

**FR-VPM-051.** The system shall represent each performance review (Quarterly Business Review) as a record carrying the date, attendees, the scorecard period under review, the discussion summary or minutes, the agreed outcomes, and the actions arising.

**FR-VPM-052.** The system shall support a vendor acknowledgement of the review outcome, recording that the performance result was shared with and acknowledged by the vendor.

**FR-VPM-053.** The system shall alert the responsible owner in advance of an upcoming review and shall flag a review that is overdue.

### 3.7 Closed-loop improvement engine

**FR-VPM-060.** When a KPI or dimension falls below its target threshold, the system shall enable the creation of a corrective action that documents the performance gap with the supporting data.

**FR-VPM-061.** A corrective action shall carry a root-cause statement, an improvement plan, an accountable owner, a due date, a current status, and an escalation path.

**FR-VPM-062.** The system shall track corrective actions through to closure, and shall require a verification step that confirms the action's effectiveness and that performance has been sustained after the action, rather than permitting closure on completion of the activity alone.

**FR-VPM-063.** The system shall provide a defined escalation procedure for corrective actions that are not progressing, including escalation to a higher governance tier and, for persistent or severe underperformance, linkage to contingency and exit planning.

**FR-VPM-064.** The system shall implement corrective actions on the existing remediation and Action Plan infrastructure (`RemediationRecord` and the Action Plan), tagged to the originating scorecard, rather than introducing a parallel task list, so that performance actions appear alongside risk-driven actions in the governance view.

### 3.8 Trend, trajectory, and benchmarking

**FR-VPM-070.** The system shall retain every scorecard period for a vendor, so that performance can be viewed as a trend over time rather than only as a point-in-time snapshot.

**FR-VPM-071.** The system shall display the trajectory of the composite score and of each dimension across periods, indicating improvement, stability, or deterioration.

**FR-VPM-072.** The system shall support year-over-year improvement targets, such as structured reductions in defect rates, late deliveries, or risk incidents, and shall report attainment against those targets.

**FR-VPM-073.** The system shall support comparison of a vendor's performance against peers in the same category or tier, to inform negotiation, renewal, and dual-sourcing decisions.

### 3.9 Integration and rollup to the risk profile

**FR-VPM-080.** On completion or publication of a scorecard, the system shall write the performance result into the vendor's consolidated risk profile, populating the existing rollup fields: a summary of SLA performance, the incident count, dispute history, the composite performance score, the review cadence, and the date of the last review.

**FR-VPM-081.** The performance result shall inform but shall not override the vendor's authoritative inherent and residual risk bands, which remain derived from the engagement-level assessments. Performance is a contributing dimension of the consolidated view, not a substitute for the risk rating.

**FR-VPM-082.** The system shall make the current performance band available to the renewal, escalation, and criticality workflows, so that sustained underperformance can inform renewal and contingency decisions.

### 3.10 Reporting, dashboards, and alerts

**FR-VPM-090.** The system shall provide a per-vendor performance dashboard showing the current composite score and band, the dimension breakdown, the trend, open corrective actions, and the next review date.

**FR-VPM-091.** The system shall provide a portfolio view across all critical vendors, ranked or filterable by performance band, so that the weakest performers are immediately visible.

**FR-VPM-092.** The system shall generate alerts on defined triggers, including a KPI or composite score crossing a threshold, an SLA breach, an overdue review, and an overdue corrective action.

**FR-VPM-093.** The system shall support export of a vendor scorecard and review record for sharing with the vendor and for governance reporting.

### 3.11 Roles, permissions, and audit

**FR-VPM-100.** The system shall enforce role-based access control consistent with the existing permission model. Viewing performance data shall require a vendor-view permission; defining and scoring scorecards and raising actions shall require a vendor-edit or equivalent performance-management permission; and publication of a scorecard shall be gated to an appropriately senior role.

**FR-VPM-101.** The system shall record an immutable audit entry for every material action, including scorecard definition and amendment, scoring, override of an automatically sourced value, publication, review completion, vendor acknowledgement, and the creation, escalation, and closure of corrective actions.

---

## 4. Data model

The following entities are introduced. All are additive and follow the platform's existing conventions of human-readable identifiers and one-to-many child relationships keyed by identifier.

### 4.1 New entities

**VendorScorecard** — one row per critical vendor per measurement period.
Fields: scorecard identifier; vendor identifier; period label and start/end dates; status (draft, agreed, in-measurement, in-review, published, closed); composite score; performance band; review cadence; the contributing critical engagement identifiers; agreed-with-vendor flag, date, and acknowledging party; published flag, publisher, and timestamp; created and updated metadata.

**ScorecardDimension** — one row per dimension per scorecard.
Fields: dimension identifier; scorecard identifier; dimension name; weight; computed dimension score; active flag.

**ScorecardKPI** — one row per KPI per dimension.
Fields: KPI identifier; dimension identifier; metric name; definition; target; measurement window; calculation method; data source; weight within dimension; actual value; auto-sourced value; score; trend indicator; exclusion flag and reason.

**PerformanceReview** — one row per review event.
Fields: review identifier; vendor identifier; scorecard identifier; review date; cadence; attendees; summary or minutes; outcomes; vendor acknowledgement flag and date; next review date.

**Corrective actions** are represented using the existing `RemediationRecord` and Action Plan, extended with a reference to the originating scorecard and a verification-of-effectiveness field, rather than a new entity, in satisfaction of FR-VPM-064.

### 4.2 Fields populated on existing entities

On `VendorRiskProfile`, the VPM module populates the previously unpopulated performance-rollup fields: `sla_summary`, `incident_count`, `dispute_history`, `performance_score`, `review_cadence`, and `last_review`.

On `VendorRecord` and the Critical Vendors designation, VPM reads the authoritative `is_critical` flag as its scope trigger and does not modify it.

---

## 5. API surface

The following endpoints are specified, consistent with the platform's existing versioned API conventions. All are subject to the role-based access control in FR-VPM-100.

- Create or retrieve a vendor's performance profile and current scorecard.
- Define and amend a scorecard, its dimensions, KPIs, targets, and weights.
- Record the agreed-with-vendor state.
- Enter or override KPI actuals, and trigger a recompute of the composite score.
- Refresh auto-sourced KPIs from the engagement, financial, attribute, and monitoring sources.
- Create, list, and complete performance reviews, and record vendor acknowledgement.
- Raise, update, escalate, verify, and close corrective actions against a scorecard.
- Retrieve the per-vendor dashboard, the portfolio view, and the trend series.
- Publish a scorecard, triggering the rollup write into the risk profile.
- Export a scorecard or review record.

---

## 6. Business rules and scoring logic

**BR-VPM-01.** Dimension weights on an active scorecard must sum to one hundred percent; the system shall reject a publication where they do not.

**BR-VPM-02.** The composite score is the sum across active dimensions of the dimension score multiplied by its weight; the dimension score is the sum across its scored KPIs of the KPI score multiplied by its in-dimension weight, with weights re-normalised when a KPI is excluded for want of data.

**BR-VPM-03.** Band thresholds are configurable but default to a four-band scale; the band is derived deterministically from the composite score.

**BR-VPM-04.** A KPI breach (actual worse than target by a configurable tolerance) is eligible to generate a corrective action; a dimension falling into the lowest band shall prompt the assessor to raise one.

**BR-VPM-05.** A corrective action cannot be closed until its verification-of-effectiveness field confirms sustained performance; completion of the planned activity alone is insufficient.

**BR-VPM-06.** Publication writes the rollup to the risk profile but never alters the inherent or residual band.

---

## 7. Non-functional requirements

**NFR-VPM-01 (Determinism and offline operation).** The scoring engine shall be fully deterministic and shall operate without any external service. Where a large language model is available, it may be used to draft review summaries and to suggest candidate root causes for corrective actions, but it shall never be required for scoring, banding, or any core function, and its outputs shall be clearly attributable and editable.

**NFR-VPM-02 (Auditability).** Every material state change shall be recorded in the immutable audit trail with actor, timestamp, and before-and-after values where applicable.

**NFR-VPM-03 (Data continuity).** Onboarding and the first agreed scorecard shall establish the performance baseline; subsequent periods shall preserve continuity so that trends and benchmarks remain valid across the relationship's life.

**NFR-VPM-04 (Security and segregation).** Performance data shall be subject to the same role-based access control and field-level protection as the rest of the vendor record; scorecard publication shall be segregated from scorecard scoring where the governance model requires it.

**NFR-VPM-05 (Proportionality).** The system shall not impose the full regime on non-critical vendors and shall make the regime's depth configurable by tier should a lightweight tier be introduced later.

---

## 8. Workflow and state model

A scorecard progresses through a defined lifecycle. It is first **drafted**, when dimensions, KPIs, targets, and weights are defined. It moves to **agreed** once the definition has been shared with and acknowledged by the vendor. It enters **in-measurement** as actuals are captured across the period. It moves to **in-review** when the period closes and the Quarterly Business Review is convened. It is then **published**, at which point the composite result is written to the consolidated risk profile and any corrective actions are confirmed. Finally it is **closed** when the period is superseded by the next, with the closed scorecard retained for trend and benchmarking. Corrective actions raised during review follow their own lifecycle of open, in-progress, escalated where necessary, and closed only on verification of sustained effectiveness.

---

## 9. Acceptance criteria

The module shall be considered functionally complete when a critical vendor automatically acquires a performance profile; when a multi-dimensional, weighted scorecard can be defined, agreed with the vendor, scored deterministically, and banded; when operational, financial-stability, and compliance KPIs populate automatically from the existing engagement, financial, and attribute data; when a Quarterly Business Review can be recorded and acknowledged; when a performance gap can raise a corrective action on the existing Action Plan that cannot be closed without verification of sustained effectiveness; when the published result populates the performance-rollup fields on the consolidated risk profile without altering the inherent or residual band; when per-vendor and portfolio dashboards present current score, trend, open actions, and next review date; and when the entire flow operates deterministically without external dependencies, with a complete audit trail.

---

## 10. Assumptions, dependencies, and out of scope

### 10.1 Assumptions

It is assumed that the Critical Vendors module is in place and provides the authoritative critical designation that scopes this module, and that the Engagement Register, Financial Due Diligence, Financial Monitoring, and Vendor Attribute Database are available as data sources as described.

### 10.2 Dependencies

This module depends on the Critical Vendors designation for its scope trigger; on the Engagement Register and `EngagementSLA` for operational KPIs; on the financial and attribute engines for the financial-stability and compliance dimensions; on the `RemediationRecord` and Action Plan for corrective actions; and on the consolidated risk profile as the destination for its rollup. Several of these connections — notably the financial-health, reputation, and monitoring feeds into the consolidated profile — are themselves the subject of prior requirements; VPM should be sequenced after those links are established so that its Financial Stability dimension draws on persisted rather than transient data.

### 10.3 Out of scope

A lightweight performance regime for non-critical vendors is out of scope for this release. Direct system-to-system integration with external ERP or procurement suites for automated actuals ingestion is out of scope, though the data model accommodates a recorded source for each actual so that such integration can be added later. Vendor-facing self-service portals are out of scope; vendor input and acknowledgement are mediated through the internal user in this release.

---

## 11. Suggested phasing

A pragmatic build sequence would deliver, first, the scorecard data model, the deterministic scoring and banding engine, and manual KPI entry; second, the automatic sourcing of operational, financial-stability, and compliance KPIs from existing platform data, and the rollup write into the consolidated risk profile; third, the review cadence, Quarterly Business Review records, and vendor acknowledgement; fourth, the closed-loop corrective-action engine with verification of effectiveness, built on the existing Action Plan; and fifth, the trend, benchmarking, dashboard, and alerting layer. This sequence delivers a usable, deterministic core early and layers governance and analytics on a proven foundation.
