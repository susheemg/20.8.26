# 360° Vendor Dashboard — System Requirements Specification

**Module:** Vendor 360 Dashboard ("Vendor360")
**Platform:** BRO Risk Oracle (Enterprise TPRM)
**Design standard:** Executive / management-consulting grade — single-pane-of-glass, insight-first
**Document type:** System Requirements Specification
**Status:** Specification for build — not yet implemented
**Version:** 1.0

---

## 1. Purpose and design philosophy

### 1.1 Purpose

This document specifies the requirements for a 360-degree vendor dashboard that compiles and correlates every data point the platform holds about a vendor, enriched with external signals, and presents it as a single, executive-grade view. The dashboard is the synthesis layer that sits above the vendor master, the engagement register, the contract database, the Financial Due Diligence and monitoring engines, the reputation and attribute data, the criticality designation, and the performance module. Its purpose is not to display data but to produce judgement: to let a senior stakeholder understand a vendor's complete posture, and where it is exposed, within seconds, and to drill from any signal to its evidence.

### 1.2 Design philosophy

The specification is built on the principles that separate dashboards executives use from those they ignore. Five govern the design.

The first is correlation over collection. The dashboard's value lies in relating signals to one another — a financial-distress signal read against contract concentration, a reputation event read against a critical designation — not in assembling them side by side. A single pane of glass that merely aggregates feeds without correlating them transfers the burden of synthesis back to the human; the design must perform that synthesis.

The second is the five-second comprehension test. A viewer should grasp the vendor's overall posture within five seconds of opening the view. This dictates a disciplined visual hierarchy: a single headline verdict, a small set of dimension scores, and a clear exception list, with all depth reserved for governed drill-down rather than crowded onto the surface.

The third is insight density without overload. Information overload is the most common dashboard failure. Every element must earn its place by influencing a decision; a metric that cannot change a decision does not belong on the surface. The design favours a small number of high-information visual elements over many low-information ones.

The fourth is persona-driven, layered disclosure. The same underlying data serves different audiences at different altitudes: a board or executive needs the verdict and the exceptions; a vendor manager needs the operational and relationship detail; a risk analyst needs the evidence and the trail. The dashboard presents a strategic surface with governed drill-down to tactical and analytical layers, rather than one undifferentiated view.

The fifth is one version of the truth. The dashboard reads from the platform's authoritative records and derived rollups so that the number a board sees is the same number the analyst can trace to source. It does not compute private figures that diverge from the consolidated risk profile.

### 1.3 The aesthetic standard

The presentation must reach management-consulting quality: a restrained, confident visual language with strong typographic hierarchy, generous white space, a disciplined palette in which colour carries meaning rather than decoration, and charts chosen for interpretive clarity rather than visual novelty. The existing brand system — the forest-green, navy, and gold palette with the Fraunces and Spline Sans typefaces — is the foundation. The result should read as a considered, professional artefact suitable for a risk committee, not as an operational console.

---

## 2. Scope

### 2.1 In scope

The dashboard covers a single vendor in depth — the 360 view — and provides a portfolio entry point from which any vendor can be reached. It compiles all internal data held for the vendor and its engagements, correlates that data into a set of derived insights, enriches it with external signals where available, and presents the result across a layered, drill-down interface. It is a read-and-synthesise surface; it does not itself create or alter the underlying records, which remain owned by their respective modules.

### 2.2 Out of scope

Authoring and editing of vendor, engagement, contract, or assessment data remain with their originating modules and are out of scope here, save for navigation links that take the user to those modules. A fully configurable, user-built dashboard designer is out of scope for this release; the layout is curated and persona-driven rather than freely arranged. Direct external-platform integrations beyond the platform's existing research and monitoring capabilities are out of scope, though the data model accommodates additional external feeds.

---

## 3. Information architecture

The dashboard is organised as a single vendor canvas with a fixed, meaningful reading order from verdict to evidence. The architecture is layered into four altitudes.

The **headline layer** presents the vendor's identity, its critical designation, a single composite posture verdict, and the small set of top-level dimension scores. This is the five-second layer.

The **correlation layer** presents the derived insights that relate signals to one another: the concentration picture, the exposure-versus-control balance, the trajectory of risk over time, and the exceptions that demand attention. This is where the dashboard earns its keep.

The **dimension layer** presents each domain in its own panel — risk, financial, reputation, monitoring, contract, performance, resilience, ESG, and compliance — each summarised with a score, a trend, and the one or two facts that matter, each expandable.

The **evidence layer** is reached by drill-down from any element and exposes the underlying records, documents, assessments, and the audit trail, taking the user into the owning module where appropriate.

---

## 4. Functional requirements

Functional requirements are enumerated with the prefix `FR-V360` for traceability.

### 4.1 Data compilation

**FR-V360-001.** The dashboard shall compile, for a selected vendor, all internal data held across the platform, including the vendor master record, all linked engagements, all linked contracts, all assessments and findings, the Financial Due Diligence result, the reputation result, the financial-monitoring signals, the full vendor attribute set, the criticality designation, and the performance scorecard.

**FR-V360-002.** The dashboard shall resolve the vendor's corporate hierarchy and present data not only for the legal entity but, where relevant, aggregated to the parent or group, so that exposure concentrated across related entities is visible.

**FR-V360-003.** The dashboard shall enrich the internal picture with external signals where the platform's research and monitoring capabilities are available, clearly distinguishing internal data from externally sourced data and marking the freshness and source of each external signal.

**FR-V360-004.** Where a data domain is empty or a signal is stale, the dashboard shall represent the absence explicitly rather than silently omitting it, so that gaps in the vendor picture are themselves visible as a form of insight.

### 4.2 Correlation and derived insight

**FR-V360-010.** The dashboard shall compute and present a single composite posture verdict for the vendor, derived from the consolidated risk profile and clearly labelled as a synthesis. This verdict shall be consistent with the authoritative inherent and residual bands and shall not contradict them.

**FR-V360-011.** The dashboard shall correlate signals across domains to surface insights that no single domain reveals, including at minimum: a financial-distress signal read against contract value and concentration; a reputation or monitoring event read against the critical designation; and a control weakness read against the inherent exposure it fails to mitigate.

**FR-V360-012.** The dashboard shall present a concentration view showing the platform's dependence on the vendor and its group — the number and value of engagements, the criticality of the functions supported, and the fourth-party and shared-upstream dependencies — so that concentration risk is quantified rather than implied.

**FR-V360-013.** The dashboard shall present an exposure-versus-control balance, juxtaposing the inherent risk with the residual risk and the maturity of the controls and assurance evidence, so that the gap between what is at stake and what is mitigated is explicit.

**FR-V360-014.** The dashboard shall present the trajectory of the vendor's key scores over time — risk, financial health, reputation, and performance — so that direction of travel is as visible as current state.

**FR-V360-015.** The dashboard shall generate a ranked exceptions list that surfaces the items demanding attention — overdue screenings and reviews, open critical findings, aging remediation, SLA breaches, expiring certifications, and adverse monitoring signals — so that the user is directed to where focus is needed rather than left to search.

**FR-V360-016.** Where the language-model capability is available, the dashboard may present a concise, generated narrative synthesis of the vendor's posture; this narrative shall be clearly attributable, shall be derived only from the compiled data, and shall never be required for the dashboard to function.

### 4.3 Presentation and interaction

**FR-V360-020.** The dashboard shall present the headline verdict and dimension scores such that overall posture is comprehensible within five seconds, with colour used to convey status meaningfully and consistently.

**FR-V360-021.** The dashboard shall support governed drill-down from any summarised element to its supporting detail and, ultimately, to the owning module and the evidence behind the signal.

**FR-V360-022.** The dashboard shall support persona-appropriate views or progressive disclosure, presenting a strategic surface by default with tactical and analytical depth available on demand, rather than one undifferentiated view.

**FR-V360-023.** The dashboard shall be responsive and legible across screen sizes, including presentation on a large display in a committee setting and review on a tablet, given that the mobile context here is a phone-width chat client.

**FR-V360-024.** The dashboard shall support export of the vendor 360 view as a polished, self-contained report suitable for circulation to a risk committee or for a vendor business review.

**FR-V360-025.** Every chart and figure shall serve interpretive clarity; the design shall avoid chart types that decorate without informing, and shall prefer a small number of high-information visuals to many low-information ones.

### 4.4 Portfolio entry and navigation

**FR-V360-030.** The dashboard shall provide a portfolio entry view listing vendors, filterable and rankable by posture band, criticality, and exception count, so that the vendors needing attention are immediately apparent and the weakest performers surface without searching the full list.

**FR-V360-031.** The dashboard shall allow direct navigation to any vendor's 360 view from the portfolio entry and from contextual links elsewhere in the platform.

### 4.5 Governance, access, and integrity

**FR-V360-040.** The dashboard shall enforce role-based access consistent with the platform's permission model, and shall respect field-level protection such that sensitive data, including banking detail, is shown only to roles entitled to see it.

**FR-V360-041.** The dashboard shall read from the platform's authoritative records and derived rollups so that the figures it shows reconcile with the consolidated risk profile and the owning modules — one version of the truth.

**FR-V360-042.** The dashboard shall record the freshness of the data it presents, displaying when each domain was last updated or assessed, so that the user can judge the currency of the picture.

**FR-V360-043.** Access to a vendor 360 view shall be recorded in the audit trail, given the sensitivity of the consolidated picture.

---

## 5. Dashboard content model

The vendor 360 canvas comprises the following panels, in reading order from verdict to evidence.

The **identity and designation header** carries the vendor's legal identity, group and ultimate parent, tier, lifecycle state, and the critical designation with its rationale.

The **posture headline** carries the single composite verdict and band, the inherent and residual risk bands, and a compact set of dimension scores spanning risk, financial health, reputation, performance, and compliance.

The **exceptions panel** carries the ranked list of items demanding attention, each linking to its source.

The **concentration and dependency panel** carries the engagement count and value, the critical functions supported, and the fourth-party and shared-upstream dependencies, expressing how much the organisation relies on this vendor and its supply chain.

The **risk panel** carries the inherent-versus-residual balance, the open findings by severity, the assessment recency, and the exposure-versus-control narrative.

The **financial panel** carries the Financial Due Diligence health band and Altman zone, the monitoring signal and its trajectory, the credit position, and any distress indicators.

The **reputation and ESG panel** carries the reputation score and pillar breakdown, adverse events, and the sustainability position.

The **contract and commercial panel** carries the contract inventory, value and renewal horizon, key dates and notice windows, and any contract gaps.

The **performance panel** carries the composite performance score, the dimension breakdown, SLA attainment and breaches, and the next review.

The **resilience and continuity panel** carries the business-continuity and exit posture, recovery expectations, substitutability, and the concentration indicator.

The **trajectory panel** carries the time series of the key scores, so that the direction of travel across risk, financial, reputation, and performance is visible at a glance.

The **provenance footer** carries the freshness of each domain and the distinction between internal and external sources.

---

## 6. Data sources and correlation logic

The dashboard draws from the platform's authoritative stores. Internally, these are the vendor master and its extension, the engagement register and its children, the contract database, the assessment and finding records, the Financial Due Diligence and reputation results, the financial-monitoring signals, the vendor attribute domains, the criticality designation, the performance scorecard, and the consolidated risk profile rollup. Externally, where the research and monitoring capabilities are configured, these are the public-data and continuous-monitoring feeds, each carrying its own source and freshness.

The correlation logic is deterministic and reproducible. The composite verdict and the derived insights are computed from the compiled records by defined rules, so that the same data always yields the same dashboard. The language model, where available, contributes narrative synthesis only; it does not compute the scores or the verdict. Offline, the dashboard operates fully on internal and structured data, presenting the external panels as unavailable rather than failing.

---

## 7. Non-functional requirements

**NFR-V360-01 (Determinism).** All scores, bands, and derived insights shall be computed deterministically from the compiled data and shall be reproducible independent of any external service.

**NFR-V360-02 (Performance and scan time).** The dashboard shall render the headline and correlation layers quickly enough to preserve the five-second comprehension standard, deferring heavier evidence-layer detail to drill-down.

**NFR-V360-03 (Graceful degradation).** Absent external connectivity, the dashboard shall present a complete internal picture and shall mark external panels as unavailable rather than blocking.

**NFR-V360-04 (Consistency).** Figures shall reconcile with the owning modules and the consolidated risk profile; the dashboard shall not introduce a divergent version of any number.

**NFR-V360-05 (Accessibility and legibility).** Colour shall not be the sole carrier of meaning; the design shall maintain sufficient contrast and clear typographic hierarchy for committee-room and tablet viewing.

**NFR-V360-06 (Aesthetic standard).** The presentation shall meet a management-consulting standard of visual quality, using the established brand palette and typography, disciplined white space, and charts selected for interpretive value.

---

## 8. Dependencies and sequencing

The dashboard's value is proportional to the completeness of the data it correlates, which makes it dependent on the requirements already in the queue. It draws its financial-health, reputation, and monitoring signals from the persisted intelligence links of the first requirement; absent those, the corresponding panels would read transient or empty values. It draws the contract inventory from the contract entity of the second requirement. It draws the critical designation and the concentration picture from the Critical Vendors module of the third. It draws the performance panel from the performance module of the fourth. It is therefore best sequenced after those requirements, so that every panel resolves to real, persisted data rather than to placeholders.

This does not prevent an earlier build of the dashboard against the data that exists today; it means only that the dashboard should be expected to grow richer as each upstream requirement lands, and that building it last allows it to be delivered complete.

---

## 9. Acceptance criteria

The dashboard shall be considered functionally complete when, for any vendor, it compiles the complete internal picture and correlates it into a single posture verdict consistent with the consolidated risk profile; when it surfaces concentration, exposure-versus-control, trajectory, and a ranked exceptions list as derived insights rather than raw feeds; when external signals enrich the view where available and their absence is marked where not; when the headline conveys overall posture within five seconds and any element drills down through governed disclosure to its evidence and owning module; when the portfolio entry surfaces the vendors needing attention without searching; when role-based access and field-level protection are enforced and figures reconcile with their sources; when the view exports as a committee-grade report; and when the entire surface renders deterministically, degrades gracefully offline, and meets the stated aesthetic standard.

---

## 10. Suggested phasing

A pragmatic build sequence would deliver, first, the data-compilation layer and the deterministic composite verdict drawing on the consolidated risk profile; second, the correlation insights of concentration, exposure-versus-control, trajectory, and exceptions; third, the full panel set with governed drill-down to the owning modules; fourth, external enrichment and provenance; and fifth, the export-to-committee-report and portfolio-ranking capabilities. This sequence delivers a defensible, insight-bearing core early and layers external enrichment and presentation polish on a proven foundation.
