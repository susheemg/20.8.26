# CR BUILD JOURNAL — improvements CR-1..CR-13 + animations

Build order (dependency-driven):
Phase 1 quick/low-risk: CR-13 hide monitoring, CR-11 perf beyond critical, CR-9 critical top band
Phase 2 form quality: CR-6 labels, CR-7 classification dropdowns, CR-8 typed inputs
Phase 3 assessment workflow: CR-2 detail review, CR-3 access control
Phase 4 document spine + consumers: doc store/extract, CR-5 certs, CR-12 contracts, CR-4 ProAssess autonomous
Phase 5: animations (cross-cutting CSS)

## STATUS
- [x] CR-1 BRO Chat capture (done earlier)
- [x] CR-2 assessment detail review view
- [x] CR-3 access control on assessments
- [x] CR-4 ProAssess autonomous
- [x] CR-5 certificates document-backed
- [x] CR-6 sentence-case labels
- [x] CR-7 classification dropdowns
- [x] CR-8 typed inputs
- [x] CR-9 critical top band
- [x] CR-10 risk attributes on 360
- [x] CR-11 performance beyond critical + enrolment page
- [x] CR-12 contract inherit + doc gap review
- [x] CR-13 hide monitoring + sweeps
- [ ] animations

## LOG

### Phase 1 DONE (browser-verified, 291 tests pass)
- CR-13: removed Monitoring + Financial Monitoring nav items (engines retained).
- CR-11: PerfEnrolment model; enrol/unenrol/list_perf_enrolment service; removed critical gate in create_scorecard
  (auto-enrols); enrolment endpoints (GET/POST/DELETE /performance/enrolment); UI Manage-list multi-select panel;
  picker now from enrolment. R4 tests updated 15/15.
- CR-9: override_engagement_criticality service + POST /engagements/{eid}/criticality-override;
  _engagement_is_critical helper; engagement_full base now carries is_critical; Critical top band on Vendor Master
  (vmSetCritical) and Engagement Register (erSetCritical), wired to authoritative override; crit-band CSS.

### Phase 2 DONE (browser-verified, 296 tests pass)
- CR-6: lbl() formatter (sentence-case, preserves acronyms via _ACRONYMS map); applied to engagement register,
  domain master, v360 dimension headers. "business justification" -> "Business justification"; TCV/ACV/FX preserved.
- CR-7: VOCAB controlled vocabularies; vmField renders dropdowns for supplier_category/segmentation/tier/spend_band/
  substitutability; tier de-flagged read-only. SIC/UNSPSC/NACE left free-text (large taxonomies — need curated lists, flagged).
- CR-8: COUNTRIES list + fieldType()/typedInput() (country dropdown, date input, email, phone +digits only);
  applied to vmField, engagement register, domain master; server-side _validate_typed_fields on vendor-master PUT.
  tests/test_cr_phase2.py 5/5.

### Phase 3 DONE (browser-verified, 303 tests pass)
- CR-10: Risk Attributes summary panel on Vendor 360, above engagements section; read-only with "Open editor →"
  link to full attributes screen; fetches /vendor-attributes alongside /vendor360; v360-attr grid CSS.
- CR-3: _can_view_assessment(u,a) — admin+vrm see all, buyer sees own (owner/SPOC), vendor none; applied to
  /assessments list and /assessments/{aid}/structured and the new review endpoint. tests/test_cr_access.py.
- CR-2: GET /api/v2/assessments/{aid}/review (scope, inherent+risks, controls_assessed, documents, residual+
  recommendation, gaps, can_approve gated to admin/vrm + unlocked); assessment rows clickable ->
  openAssessmentReview; reviewApprove from within; rev-* CSS. 7/7 tests incl can_approve gating.

### Phase 4 partial (document spine + CR-5 + CR-12) — tests pass
- Document spine: app/features/documents.py — StoredDocument (base64 in Text, portable), store/get_document,
  _decode_text (text/pdf/docx), extract_certificate, extract_contract_terms, extract_proassess_signals.
  DOC- prefix added; table registered. 15MB + type guard.
- Endpoints: POST /documents/upload, GET /documents/{id} (streams bytes), POST /certificates/ingest.
- CR-5: Certificates view -> "Upload documents" multi-file -> /certificates/ingest -> AI reads each ->
  ArtefactRecord with object_uri doc link; view link column; artefacts list exposes doc_link. 6/6 tests.
- CR-12: POST /contracts/gap-from-document — inherits inherent band + exposure from engagement when registered,
  prompts band only for Other; stores doc, extracts terms, runs gap engine. UI: engagement picker (inherit/hide
  manual), doc upload on Gap review + Existing-vs-to-add tabs. engagement-register PUT now persists base bands. 5/5 tests.
- STILL TODO: CR-4 ProAssess (new vendor, single box, doc upload, autonomous creation); animations.

### Phase 4 COMPLETE — CR-4 done (browser-verified, 321 tests pass)
- CR-4: run_proassess_autonomous in master_service — single free_text + documents, new/existing vendor.
  _find_duplicate_vendor (normalised-name guard, no phantom records). Extracts IRQ via extract_proassess_signals
  from text+docs; runs existing run_proassess (logic unchanged); creates vendor/engagement/assessment/artefact
  records transactionally + audited, owner=user (CR-3 applies). POST /api/v2/proassess/autonomous (ProAssessAutoIn).
  UI: new/existing toggle, single text box, multi-file upload, "Records created automatically" panel,
  extracted-IRQ + gaps + risks, "Open assessment record →". 7/7 tests. (re import added to master_service.)

### Phase 5 DONE — animations (browser-verified, 321 tests pass, 0 JS errors across 25 screens)
- Added: staggered table-row entry (rowIn), card/panel pop-in (popIn), button press feedback + hover shadow,
  modal/flash entry (popIn/slideInRight), critical-band attention pulse (pulseCrit/bandPop), nav hover slide,
  band/pill pop, spinner utility. All use existing --dur/--ease tokens. Respects prefers-reduced-motion.

## ALL 13 CRs + ANIMATIONS COMPLETE. 321 tests pass. 186 routes. 25 screens render, 0 JS errors.

### Supply-chain additions (browser-verified, 325 tests pass, 0 JS errors across 25 screens)
- Engagement fields: delivery_location + receiving_location (country dropdowns via fieldType); columns added to
  EngagementExt; surfaced in engagement register Scope tab; persist + reload verified.
- Management > Supply Chain tab: concentration_graph service (nodes=vendors/fourth-parties/locations,
  edges=dependencies, degree-based concentration risk colouring) + GET /api/v2/management/concentration.
- Concentration network: client-side force-directed SVG (multi-colour by node type, red=high concentration),
  hubs callout table. World map: equirectangular SVG with stylised continent polygons + delivery-location
  bubbles sized/coloured by engagement count, country centroid table. tests/test_cr_supply.py 4/4.
- NOTE: caught an embedded-JS syntax error (else after else-if) that python ast.parse missed — now validate
  web.py JS with `node --check` on the extracted <script>.
