# BUILD JOURNAL — Requirements 1–6 (single continuous build)

Order (dependency-driven): R1 intelligence links → R2 contract entity → R3 critical vendors
→ R4 performance mgmt → R5 ProAssess → R6 Vendor360 dashboard.

## Confirmed design defaults (from requirement dialogues)
- R1: persist FDD/Reputation/Monitoring against registered VEN- only (skip "Other");
  engine outputs populate dedicated fields; inherent/residual stay authoritative;
  reconcile FinMonitorRecord<->VendorMonitorSignal; populate financial_health_band,
  reputation_summary, monitoring_signal on VendorRiskProfile.
- R2: single ContractRecord (CON-), MSA->vendor primary link, Contract/PO->engagement
  primary link + optional parent MSA; contract engine + EngagementExt write into it;
  migrate v1 Contract table.
- R3: deterministic criticality engine + optional LLM rationale; 4 params (customer impact,
  downtime tolerance, alt availability, substitution complexity) as scored engagement inputs;
  auto-designate engagement->vendor->contract; authoritative source for is_critical w/ override.
- R4: scoped to critical vendors; deterministic weighted scorecard; agreed-with-vendor;
  auto-source operational/financial/compliance KPIs; QBR; closed-loop CAPA on RemediationRecord;
  rollup into VendorRiskProfile perf fields; never overrides inherent/residual.
- R5: ProAssess; proportionate to inherent rating; no questions, no assumptions, gaps->risk-averse;
  two-layer (deterministic engines authoritative, LLM extract+synthesise); register = non-destructive
  merge, permission-gated, audited; empanel for monitoring on completion; one-time assess + continuous monitor.
- R6: Vendor360 dashboard; deterministic correlation; one version of truth; 5-sec headline; drill-down;
  reconciles with risk profile; degrades offline; committee-grade aesthetic.

## STATUS
- [x] R1  intelligence links
- [x] R2  contract entity
- [x] R3  critical vendors
- [x] R4  performance management
- [x] R5  ProAssess
- [x] R6  Vendor360 dashboard

## PROGRESS LOG
(baseline captured below)

### R1 DONE (intelligence links)
- master_service.py: persist_fdd / persist_reputation / persist_monitor_result; _vendor_exists; _latest_signal;
  refresh_risk_profile now reads ext.financial_health_band, latest monitoring signal, carried reputation_summary;
  falls back to assessment bands when engagements carry none (fix for pre-existing gap).
- bro_app.py: FinancialIn gains vendor_id/other_name; FDD + reputation endpoints persist for registered vendor
  (skip "Other"); fin-monitor sweep reconciles signal into VendorMonitorSignal + refresh_risk_profile.
- tests/test_r1_intel_links.py (5 tests). Engagement/assessment inherent stays authoritative; FDD/rep/monitor fill dedicated fields only.
- Marker: [x] R1

### R2 DONE (contract entity)
- master_ext.py: ContractRecord (CON-) with vendor_id+engagement_id+parent_msa+primary_link;
  type-driven: MASTER_TYPES{MSA,Framework,Master}->vendor primary, CALLOFF->engagement primary; is_critical flag for R3.
- master_service.py: create_contract (resolves vendor from engagement for call-offs; MSA nulls engagement),
  list_contracts, update_contract, contract_from_engine, sync_engagement_contract, migrate_v1_contracts (idempotent via doc_link marker),
  mark_contracts_critical (R3 hook).
- bro_app.py endpoints: POST/GET/PUT /api/v2/contracts, POST /contracts/migrate-v1, POST /engagement-register/{eid}/sync-contract (155 routes).
- tests/test_r2_contracts.py (8 tests).
- Marker: [x] R2

### R3 DONE (critical vendors)
- master_ext.py: EngagementCriticalityInput (4 params 1-5), CriticalityDesignation (engagement|vendor, auto vs override).
- master_service.py: CRIT_PARAMS/WEIGHTS/THRESHOLD(3.5); set_criticality_inputs; score_engagement_criticality
  (gaps->worst-case 5 risk-averse; HIGH inherent or mission_critical floors to threshold); designate_engagement
  (marks contracts critical); designate_vendor_from_engagements (sets authoritative is_critical, respects manual override);
  override_vendor_criticality; run_critical_analysis (chain); list_critical.
- bro_app.py endpoints: PUT /engagements/{eid}/criticality-inputs, GET /engagements/{eid}/criticality,
  POST /critical-vendors/analyse, GET /critical-vendors, POST /critical-vendors/{vid}/override (160 routes).
- tests/test_r3_critical.py (9 tests).
- Marker: [x] R3

### R4 DONE (vendor performance management — critical vendors)
- master_ext.py: VendorScorecard (SCD-), ScorecardDimension, ScorecardKPI, PerformanceReview (PRV-).
- master_data.py: added scorecard->SCD, review->PRV prefixes.
- master_service.py: PERF_DIMENSIONS (6, sum 100), DEFAULT_KPIS library, PERF_BANDS; create_scorecard (gated to
  is_critical vendors, seeds dims+KPIs, links contributing critical engagements); set_kpi_score; auto_source_kpis
  (NON-DESTRUCTIVE: skips KPIs already scored; sources SLA/findings/FDD band/certs); compute_scorecard (weighted,
  re-normalises on exclusion); agree_scorecard; publish_scorecard (refreshes risk profile THEN layers perf fields,
  never alters inherent/residual); reviews CRUD + acknowledge; raise_performance_capa + verify_performance_capa
  (closed-loop on RemediationRecord, status->Verified w/ evidence).
- latest_risk_profile now COALESCES newest non-null per field across snapshots (resilient to multi-row writes).
- registry_service.create_assessment now accepts+persists residual_band and propagates inherent/residual to engagement.
- bro_app.py: V2AssessmentIn gains residual_band; 11 perf endpoints (171 routes).
- tests/test_r4_performance.py (12 tests).
- Marker: [x] R4

### R5 DONE (ProAssess)
- master_service.py: PROASSESS_SCOPE (domain coverage per inherent band LOW/MOD/ELEV/HIGH),
  MONITOR_CADENCE (annual..monthly); run_proassess (deterministic inherent via compute_inherent;
  proportionate domain processing; no-assumption -> gaps resolved worst-case; financial/reputation engines
  when data supplied else gap; residual via compute_residual or =inherent when no controls; conservative
  recommendation); register_proassess (non-destructive merge: assessment, FDD band, reputation signal,
  findings-from-risks, refresh_risk_profile; empanels FinMonitorRecord if absent; advisory + audited).
- bro_app.py: ProAssessRunIn/RegisterIn; POST /proassess/run (engagement.view), /proassess/register (vendor.critical, gated) (174 routes).
- two-layer: deterministic engines authoritative; LLM-extracted inputs passed via `extracted`/`irq`/`ddq`.
- tests/test_r5_proassess.py (11 tests).
- Marker: [x] R5

### R6 DONE (Vendor 360 dashboard)
- master_service.py: _posture_verdict (consolidated verdict, never contradicts residual; adverse signals only raise concern);
  vendor360 (compiles all domains, correlates: concentration/value, exposure-vs-control gap, ranked exceptions;
  reconciles with risk profile); vendor360_portfolio (rankable: critical first, then posture level, then findings).
- bro_app.py: GET /vendor360/portfolio, GET /vendor360/{vid} (176 routes). Also fixed pre-existing gap:
  V2EngagementIn now accepts annual_value+currency (were dropped at schema boundary).
- web.py: Vendor 360 nav item; executive single-pane view (forest-green hero, posture dot, 6-dim strip,
  correlation panels: ranked exceptions / concentration / exposure-vs-control / performance+financial / engagements;
  provenance footer) + portfolio entry ranked view. BCG-grade aesthetic, brand palette, Fraunces/Spline Sans.
- tests/test_r6_vendor360.py (12 tests). Browser-verified portfolio + detail, no JS errors.
- Marker: [x] R6
