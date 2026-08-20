## [4.27.0] — 2026-08-19 · Conversation History and Activity — transparency of human and agent action

Two pages whose objective is visibility of what has happened and continuity of what has
not finished. **Release gate: PASS** — 74/74 functional (12 new), 141 endpoints clean,
both eval suites green.

### Added — Conversation History
- One page covering **both** conversational routes. BroAssess sessions and ProAssess runs
  appear in a single list rather than in two separate popups, because a user looking for
  "what did I do about this supplier" does not think in terms of which engine ran.
- **In progress** → Continue, resuming the conversation where it was left.
  **Concluded** → Open record, which opens the assessment it produced along with its
  engagement and supplier. ProAssess is single-shot, so it is concluded the moment a
  record exists; there is nothing to resume and the page does not pretend otherwise.
- Progress is shown as stage *n* of 8 with the stage name, not a bare percentage, so a
  user can tell what the conversation was in the middle of.
- **Visibility.** Assessor, controller and administrator see every conversation — they are
  the review functions and cannot review what they cannot see. A buyer sees their business
  unit's work plus anything assigned to them. Everyone else sees their own.

### Added — reassignment of unfinished conversations
- A controller, assessor or administrator can hand an in-progress conversation to another
  user. People leave, go on holiday, and hand over suppliers; an assessment stranded in a
  departed colleague's account is a real operational failure.
- **`created_by` is never overwritten.** Who started a piece of work is part of the record;
  `assigned_to` is who owns it now, and the list shows both when they differ.
- Refused with 409 on a concluded conversation — there is nothing to hand over — and 404
  on an unknown or deactivated target user. Every reassignment is audited.

### Added — Activity page, two tabs
- **User** — actions performed by people. Every user sees their own; a controller or
  administrator sees everyone's.
- **Agent** — actions performed by the system: automated record chains, scheduled sweeps,
  screening outcomes and AI activity, **scoped to the records the viewer may see**, so the
  agent log never becomes a side channel around row-level scoping.
- Both are views over the existing hash-chained audit trail, not a second copy. Each entry
  carries its chain hash, and the page points at the verification endpoint.

### Added — human/agent classification
- `app/features/platform/activity.py` classifies every audited action as human or agent.
- The audit trail attributes an AI action to the human who invoked it, and always will —
  SOP IAM-4 exists because the model is never the accountable party. That is right for
  accountability and unhelpful for transparency: a reviewer could not tell whether a
  person decided something or an automated chain fired underneath. **This adds the
  distinction without changing the attribution.** The agent tab says what *acted*; the
  actor column still says who is *answerable*.
- Classification is by action name, held in one place so it can be reviewed as a whole and
  corrected without touching the audit writer. **Unknown actions default to human**, because
  over-attributing to a person invites scrutiny, whereas mis-filing a human decision into a
  system log hides it.
- Actions carry readable labels ("Registered an assessment", not `assessment.registered`)
  so the page is usable by a reviewer who does not read code.

## [4.26.1] — 2026-08-19 · Assessor sign-off workflow · run budgets · prompt versioning

Closes the three findings left partial at v4.26.0. **Release gate: PASS** — 62/62
functional, 137-endpoint sweep clean, both eval suites green.

### Closed — AI-02 (step 2): assessors can now sign evaluation cases
- The roadmap named assessor sign-off as the single most valuable next action, and it had
  not happened for a mundane reason: **there was no way to do it.** An assessor cannot
  review a Python literal in a source file, and asking them to edit one would be neither
  reasonable nor auditable.
- Cases moved to a versioned store (`tools/eval_cases.json`) carrying the methodology
  version, and `tools/sign_cases.py` gives a reviewable queue: `--list`, `--show`,
  `--sign`, `--status`. A signature records who, role, verdict, comment and timestamp.
- **A signature is a claim about the expected outcome, not about the code.** The assessor
  asserts: given these inputs, this is the answer the methodology requires — exactly the
  judgement an engineer is not qualified to make, and exactly what turns a conformance
  test into a golden case.
- A verdict of `disagree` is treated as a finding, not a nuisance: the case is **excluded
  from the gate and reported separately** rather than quietly deleted, because a
  disagreement means either the case is wrong or the methodology is ambiguous.
- The eval suite reads signatures, reports signed coverage per dimension, and marks signed
  cases in its output.
- **The store ships unsigned.** Demonstration signatures used in testing were removed
  before packaging — shipping a fabricated assessor approval would be precisely the kind
  of unearned assurance this work exists to prevent.

### Closed — AI-05: per-run token, cost and wall-clock ceilings
- Added `app/features/platform/budget.py`. The daily budget and per-call timeouts existed;
  what was missing was a bound on a *single run*, so one assessment could regenerate
  repeatedly until the daily cap tripped and blocked everyone else's work.
- `run_budget(run_id, max_tokens=…, max_cost_usd=…, max_seconds=…)` as a context manager,
  with an indicative price table overridable per deployment via `BRO_PRICE_JSON`.
- Pricing is deliberately approximate: the point of a cost ceiling is not accounting
  precision — finance reconciles from the provider invoice — it is stopping a runaway
  before it becomes expensive, and an approximate ceiling still stops it.
- New `GET /api/v1/platform/run-budgets` surfaces in-flight runs and flags any above 80%
  of a limit. A run 90% through its token budget is the signal that something is
  regenerating rather than converging.

### Closed — AI-04: prompt changes are versioned and require a reason
- Overrides now carry a version, an owner, a timestamp, a before/after digest and a
  **mandatory change note**. `POST /api/v1/ai/prompts/{key}` returns 400 without one.
- "Why did this prompt change?" is the first question asked when an assessment is
  challenged, and it cannot be answered retrospectively.
- New `GET /api/v1/ai/prompts/{key}/version` returns the version, owner and last ten
  changelog entries. The response to a prompt edit reminds the administrator to run the
  release gate, because a prompt edit alters assessment behaviour like a code change.

### Position after this release
| Finding | Status |
|---|---|
| AI-01, AI-02, AI-03, AI-04, AI-05, AI-06, APP-01, APP-02, APP-03, DB-03 | **Closed** (10 of 15) |
| DB-01, DB-02, DB-04, DB-05 | Scheduled — all require the PostgreSQL migration window; DB-05's migration is written and shipped |
| AI-07 | Product decision — retrieval should not be built without a reason and its own evaluation set |

The one thing still outstanding that no code can close: **an assessor has to sit down and
sign the cases.** The tooling, the queue and the audit record now exist; the judgement
does not, and cannot be manufactured.

## [4.26.0] — 2026-08-19 · Architecture remediation against the Practitioner's Guide

Implements the recommendations from the best-practice assessment (DOC-ASM-001). Ten of
fifteen findings are closed in code; five require a PostgreSQL migration window or a
decision outside engineering and are scoped, written down and scheduled rather than
silently deferred. Regression: 62/62 functional, 136-endpoint sweep clean, both eval
gates passing.

### Closed — AI-01: the AI governance harness now runs
- `prompt_evals.py` had raised `ImportError` since the router split moved the modules it
  imports, so the control the SOP names as gating every prompt change had not executed
  for months. Import paths repaired; **86 checks now pass**.

### Closed — AI-02: assessment quality is now measured
- Added `tools/eval_assessment.py`: 18 cases across **four separately gated dimensions** —
  band (methodology conformance), gaps (control-gap detection), grounding (no parse of
  unsupported output) and adversarial (prompt-injection containment). Per-dimension
  thresholds, never a blended score, because an aggregate hides the dimension that causes
  production failures.
- **The gate was verified to fail**, not just to pass: deliberately breaking the JSON
  parser dropped grounding to 50% and returned exit code 1. A gate that cannot fail is
  not a gate.
- Added `tools/release_gate.sh` chaining all three suites for CI.
- **Stated honestly in the module docstring and in the output:** the cases are
  engineer-authored from the methodology, not signed by a second-line assessor. The suite
  currently measures *conformance to the documented methodology*, which is real and
  useful, but is not the same as assessment quality as a CRO would judge it. Cases carry
  `labelled_by` so the two can never be confused, and the summary reports the split.

### Closed — AI-03: prompt-cache effectiveness is now measurable
- Cache counters were read from the provider and sent to `print()`. `LLMResponse` now
  carries usage, the gateway persists it, and `ai_call_log` gained input, output,
  cache-read and cache-write token columns (self-healing on existing databases).
- New `GET /api/v1/ai/cache-metrics`: hit rate and write:read ratio per domain. Below 1.0
  write:read means caching is paying for itself; a high ratio with a low hit rate means
  the breakpoint is sitting on volatile content.

### Closed — AI-06: distributed tracing and correlation
- Added `app/features/platform/telemetry.py`: OpenTelemetry with GenAI semantic
  conventions, **vendor-neutral** so the backend can change without touching application
  code, and **optional** — it degrades to no-op spans when the library is absent, because
  tracing must never stop an air-gapped deployment booting.
- `X-Correlation-Id` accepted, generated when absent, propagated and echoed.
- **Content never enters a span.** A forbidden-attribute list drops prompt, response and
  document text at capture, extending the ledger's metadata-only discipline rather than
  abandoning it.

### Closed — APP-01: job state survives the process
- The research job registry was a module-level dict, so a run died with its process and a
  status poll could land on a worker that had never heard of the job. State now persists
  to `research_jobs` with the owning worker recorded, and 24-hour retention.
- This is **not** full durable execution — nothing re-drives an interrupted run — and the
  distinction is recorded in the code rather than glossed.

### Closed — APP-02: idempotency on identifier-minting endpoints
- `POST /api/v2/vendors` honours `Idempotency-Key`, scoped by (key, actor, route) so one
  tenant's key cannot collide with another's. A retry returns the first result; **reusing
  a key with a different body returns 409** rather than silently discarding the second
  request; omitting the header leaves behaviour unchanged.

### Closed — APP-03: circuit breakers
- Added breakers with half-open probing, wired into the model gateway per provider. A
  probe reservation now **expires after one cooldown**, fixing a flaw found in testing
  where a probe that never reported back would wedge the breaker shut permanently.
- New `GET /api/v1/platform/reliability` exposes breaker state to operators.

### Closed — DB-03: personal-data map and erasure procedure
- Added `app/features/admin/privacy.py` mapping ten tables to one of erase, pseudonymise
  or retain, each with its basis — and stating plainly the tension between the immutable
  hash-chained audit trail and the erasure right, with the resolution: pseudonymise by
  forward correction, never rewrite history.
- Three endpoints: the map for DPO review, a report-only erasure plan, and execution that
  **defaults to a dry run and refuses to execute at all until `LEGAL_REVIEW` is set**.
  The classification is an engineering proposal for Legal and the DPO to confirm; the code
  will not act on it unsigned.

### Scoped, not deferred silently
| Finding | Why not now |
|---|---|
| DB-05 foreign keys | Migration written and shipped; PostgreSQL-only, needs a migration window |
| DB-01 object storage | Requires a storage endpoint decision and a backfill window |
| DB-02 temporal/JSONB types | Belongs in the same PostgreSQL migration as DB-05 |
| DB-04 partitioning | PostgreSQL-only; must precede volume accrual |
| AI-07 retrieval layer | A product decision. The guide is explicit that retrieval should not be added without a reason and its own evaluation set |
| AI-04 prompt version gate | Depends on AI-02 having assessor-signed cases first |
| AI-05 per-run token/cost ceilings | Partially closed (daily budget, breakers); per-run ceilings follow the run-record work |

## [4.25.9] — 2026-08-18 · Design system review: colour coherence, dark theme, motion, contrast

A design review of the interface. The type system (self-hosted Bricolage Grotesque /
Manrope / Martian Mono) and the light/dark token architecture were already in place and
well-judged; this release fixes defects found in them and finishes the parts that were
declared but not working. Regression: 62/62, 132-endpoint sweep clean.

### Fixed — 36 declarations referenced CSS variables that were never defined
- An audit of the stylesheet found `var(--dur)` used 19 times, `var(--dur-lg)` 5,
  `var(--accent-2)` 11 and `var(--sh)` once, none of them defined. An undefined custom
  property invalidates the whole declaration, so **most transitions and several borders
  were silently doing nothing** — the interface looked animated in the source and was not
  in the browser. Aliased to the real tokens rather than rewritten at 36 call sites.
- Removed three malformed declarations carrying a space inside the hex value
  (`--mute:#8695 8C`, `--warn-soft:#332714 45`, `--accent:#14574180`). Each was dead but
  overridden on the following line, so the symptom was invisible.

### Fixed — role identity was repainting the entire chrome
- `applyRoleTheme()` set the topbar background inline, per role, to five unrelated hues
  (rust, navy, brown, purple, grey). The product read as five different applications, the
  brand colour never appeared for four of six roles, and because the paint was an inline
  style it survived theme switching.
- Role is now a `--role` hue token expressed as a 2px hairline under the topbar and applied
  via `data-role` on the document, so it re-tints with the theme. The chrome keeps one
  identity. Hues were re-picked as one family differentiated by temperature, each legible
  on both themes.

### Fixed — dark theme
- **Surfaces had no elevation ladder**: `--paper` (#151A18) and `--soft` (#0F1412) sat four
  points apart, so cards lost their edge and tables read as a wash. Surfaces now step up in
  lightness with elevation.
- **Accent read as a different brand**: #4FD39D at full chroma against the light theme's deep
  evergreen. Pulled toward the brand hue and desaturated to #3FBE8C.
- **Primary buttons were unreadable**: `.btn` hardcoded `color:#fff`, which on the light dark-mode
  accent measures ~1.9:1. Now uses `--accent-ink`, which pairs correctly in both themes.
- Critical red desaturated (#FF6B5E → #F0776B); fully saturated red on near-black vibrates.

### Fixed — WCAG AA contrast
- Measured every text node against its resolved background in both themes. Three real
  failures fixed: `--mute` 4.34:1 on tinted table rows, `--faint` 4.34:1 on identifiers, and
  `--ember` 4.07:1 at 12px. **Content area now passes AA in both themes with zero failures.**

### Fixed — charts ignored the theme
- The supply-chain concentration graph and the fourth-party graph hardcoded light-theme
  colours: node labels rendered near-black on a near-black surface and edge strokes stayed
  bright, so on dark the labels vanished and the web of edges dominated the page. Strokes,
  labels and node halos now resolve through tokens and follow the theme.

### Added — a motion system
- One easing family, three durations, and a rule that motion explains a change of state or
  position rather than decorating: views rise 8px on arrival (not 24 — large travel reads as
  latency once seen fifty times), table rows lift with an inset accent rule so the click
  target is unambiguous in dense tables, primary buttons depress on press, focus rings grow,
  and theme changes crossfade the surfaces instead of hard-cutting.
- A HIGH band pulses once on arrival and then stops; perpetual animation on a risk indicator
  becomes wallpaper within a day.
- Everything is suppressed under `prefers-reduced-motion`.

### Changed — layout density
- Segmented controls were `flex:1`, stretching a binary choice across the full content width.
  Now intrinsically sized.
- Page headers: the subtitle measure follows the type size (62ch) rather than a fixed 680px,
  which had produced a three-line subtitle in a narrow column beside empty space.

### Known, not addressed
- 19 selectors (`.btn`, `.card`, `.band`, `.top` and others) are defined two to four times at
  top level: a legacy stylesheet is appended after the design system and wins on cascade
  order. The duplicates were made consistent where they conflicted visibly, but merging the
  two stylesheets is a larger change than this release should carry.
- The home hero ("Brata · Third-Party Risk" split across two unrelated hues, with a large
  amber demo affordance above the working surface) is a content and hierarchy question, not a
  token question, and wants a decision on what the landing page is for.

## [4.25.8] — 2026-08-10 · Access-control fix (BU scoping) · supplier home · chat history

Regression: 62/62 functional checks pass (12 new), 132-endpoint sweep clean.
Migration: `access_scope_1`. Operator note: `docs/DB_HARDENING.md` unchanged; see below.

### SECURITY — cross-supplier data exposure on Supplier 360 and 8 related endpoints
- **Reported as** "Supplier 360 shows all suppliers to everyone". **Reproduced as worse**: a
  supplier portal user bound to one vendor could read *another* supplier's full 360, evidence
  pack, master record, linkage and performance data, and could list the entire 322-supplier
  portfolio. That is cross-tenant leakage to an external party, not only an over-permissive
  internal view.
- Root cause: function-level RBAC was applied (`require("vendor.view")` — held by all six
  roles, so it gated nothing) but **object-level authorisation was not**. The scoping helper
  `scoped_vendor_ids()` already existed and was used by 4 endpoints; 9 others never called it.
  OWASP API Security #1 (Broken Object Level Authorization).
- Fixed by applying `assert_object_visible()` to: vendor360, evidence pack, vendor-master,
  vendor linkage, vendor-attributes (read + refresh-rollups), sanctions screen-vendor,
  fourth-party impact scenario, and vendor performance — and by filtering the vendor360
  portfolio through `scoped_vendor_ids()`.
- **Returns 404, not 403**, on a scope miss: a 403 confirms the record exists and would let a
  scoped user enumerate the supplier base by ID.
- Scope denials are now logged (`brata.access`) so probing is detectable rather than silent.

### Changed — buyer scoping is now business-unit level (was engagement-owner level)
- `scoped_vendor_ids()` for the buyer role now returns every vendor engaged by the user's
  business unit(s), not only engagements they personally own.
- Added `users.business_unit` (comma-separated where a buyer covers several). **When unset the
  BUs are derived from the engagements the user owns**, so existing deployments scope correctly
  with no backfill, and a buyer who owns nothing sees nothing — failing safe.
- `scope_engagement_query()` moved to the same BU basis so the two cannot drift apart.
- Verified on the demo estate: buyer 149 of 322 suppliers (3 BUs), supplier 1, assessor/admin all.

### Added — supplier home page
- The `vendor` role now lands on a purpose-built portal page instead of the internal task grid.
- "What needs your attention" orders work by urgency — overdue actions, then critical/high
  findings, then open findings, performance issues, issues log — each with a live count and a
  single call to action. Clean state when nothing is outstanding.
- Greets the organisation ("Hello, Amazon Web Services, Inc.") rather than the login, because an
  external user identifies with their company, not their username.

### Added — Previous Chats (BroAssess)
- `ConversationSession` gained provenance: `created_by`, `business_unit`, `vendor_id`,
  `subject_label`, `status`, `updated_at` (indexed). Without these a user could not find their
  own unfinished conversations and the list could not be access-scoped.
- A touch-helper keeps last-activity current and lifts the supplier/subject out of the dossier
  as the conversation establishes it, so the list shows a real name rather than "Session 12".
- New `GET /api/v1/agent/sessions`: unfinished and completed conversations, most recently active
  first, with a progress indicator (stage n/8 plus stage name), message count, who started it,
  and the assessment id where the chat produced one. **Continue** resumes in place.
- Access-scoped: admin / assessor / controller see all; a buyer sees its business unit's chats
  plus its own; anyone else sees only their own.

### Added — Previous Chats (ProAssess)
- New `GET /api/v2/proassess/history`: previous runs with supplier, engagement, inherent and
  residual bands, outcome and assessment id — vendor-scoped by the same rule.
- ProAssess is single-shot, so the popup says plainly there is nothing to resume; each row opens
  the full assessment review via **Read outcome**.

### Added — regression coverage
- 12 new checks in `tools/simtest.py` covering supplier isolation (own record readable, others
  404, portfolio of 1), buyer BU scope (in-BU 200, out-of-BU 404, bounded portfolio),
  unrestricted-role visibility, and both chat-history endpoints with their scoping.
- The harness is now self-contained: it derives its endpoint list from source at run time rather
  than depending on a temp file left by an earlier manual step.

## [4.25.7] — 2026-08-06 · Database hardening (DB-01 … DB-08)

Implements the actionable findings from the database design review (DOC-DBR-001).
Operator guide: `docs/DB_HARDENING.md`. Regression: 49/49 functional checks pass,
130-endpoint sweep clean.

### Fixed — DB-01: two schema-provisioning paths produced different databases
- `create_all` (the default) and Alembic diverged silently: a database built by
  create_all carried no `alembic_version` stamp, so migrations could never be applied
  to it, and any change shipped only as a migration never reached it. The six indexes
  from `g6_fk_indexes` were absent from every create_all database, including the demo.
- Fresh databases are now stamped at the expected revision on creation, so both paths
  converge. Existing databases are checked at boot: an unstamped or unrecognised
  revision logs a warning naming the exact remediation command. The check never
  rewrites a stamp it did not create — guessing another operator's migration state is
  worse than reporting the mismatch. Boot is never blocked by the check.

### Fixed — DB-02: core join columns were unindexed
- 54 of 96 business-key columns had neither an index nor a unique constraint,
  including `finding_records.vendor_id`, `assessment_records.engagement_id` and
  `engagement_records.vendor_id`.
- Indexes are now declared on the models (`index=True`), so **both** provisioning
  paths create them — a fresh database now builds 67 indexes, up from 43 — and
  migration `db_hardening_1` adds 29 to existing databases, with composite indexes
  where the access path is filtered (e.g. `(vendor_id, status)` on findings).

### Fixed — DB-03: the audit trail could not scale to the question it answers
- `audit_log` had no subject columns and no indexes, and four endpoints loaded the
  entire table with no limit — including the evidence pack, which loaded the whole
  chain to render one vendor.
- Added indexed `vendor_id` / `engagement_id` columns, populated automatically from
  the payload and backfilled from existing rows. `GET /api/v1/audit` is now paginated
  and filterable (vendor, engagement, actor, action); `/audit/verify` verifies a
  window by default and reports its scope, with `full=1` for whole-chain assurance;
  `/audit/export.csv` streams, is bounded, and can be scoped to one subject; the
  evidence pack queries by subject with a bounded fallback for pre-backfill rows.
- **The hash chain is unchanged.** The subject columns are not part of the hash input,
  so chains written by earlier releases still verify (confirmed before and after).

### Fixed — DB-05: four incompatible status vocabularies, already drifting in data
- `routers/domain.py`, `routers/assessment.py` and `assessment/bro_engine.py` each
  declared a different finding-status list (one lower-case), `registry_service` wrote
  a fifth value, and the database held "In remediation", which no list contained.
  Because status matching is a string comparison, every status-filtered count was
  silently wrong rather than erroring.
- Added `app/features/domain/vocab.py` as the single definition for finding status,
  severity, band, assessment status and issue status, with alias mapping so legacy and
  case variants converge. All three modules now import it. Writes normalise before
  persisting. Migration normalises existing rows (82 findings corrected in the demo
  database). Unknown values pass through unchanged rather than being dropped — an
  unrecognised value is a data-quality signal and must stay visible.

### Fixed — DB-06: identifier generation was not concurrency-safe
- `next_id()` performed a read-modify-write on the shared counter with no lock. On
  SQLite the global write lock hid this; on PostgreSQL two concurrent workers could
  mint the same identifier, and CSV import and autonomous assessment are exactly the
  concurrent paths where it would surface. The counter row is now locked for update on
  backends that support it; the unique constraints remain the final backstop.

### Added — DB-08: risk-band divergence detection
- Inherent and residual bands are deliberately stored on the engagement, the
  assessment snapshot and the vendor profile, but nothing verified the live copies
  agreed. The monitoring sweep gains a `band_reconciliation` task comparing each
  engagement against its latest assessment, reporting divergence and auditing it
  rather than guessing which side is correct.

### Added — DB-04: PostgreSQL constraints (opt-in, separate revision)
- `db_hardening_2_pg` adds foreign keys (`ON DELETE RESTRICT`, encoding the existing
  no-hard-delete convention as a guarantee) and CHECK constraints on the canonical
  vocabularies. Shipped as its own revision because it is the one change that can
  reject writes that previously succeeded; constraints are added `NOT VALID` then
  validated, so the table is not locked for the scan. No-op on SQLite. An orphan
  pre-flight query is documented — the current data has zero orphans across all
  checked paths, which is why this is cheap to adopt now.

### Deliberately not included
- DB-07 (temporal columns stored as text), DB-09 (`engagement_ext` at 126 columns),
  DB-10 (JSON → JSONB), DB-11 (nullability), DB-12 (retention/partitioning) and
  DB-13 (dropping the 13 empty legacy v1 tables). Each needs judgement calls or
  touches many read paths; bundling them into a hardening release would have made the
  change unreviewable. Reasoning recorded in `docs/DB_HARDENING.md`.

### API change (breaking for direct consumers)
- `GET /api/v1/audit` previously returned a bare list of every entry; it now returns
  `{entries, count, has_more, next_before_seq}`. The UI is unaffected.

## [4.25.6] — 2026-08-06 · Full-system simulation test pass: 3 fixes + regression harness

### Tested
- Full-application simulation with a simulated Claude SDK injected at the anthropic-client
  level, so the real LLM pipeline ran end-to-end (provider detection, prompt-cache, streaming
  web-search transport, retries, JSON parsing, async research jobs, AI ledger).
- Tier 1: 49 deliberate functional checks across Platform/RBAC, User Mgmt (JML + supplier
  guardrails), Registry, ProAssess, BroAssess, BroCall, Intelligence, Lifecycle, Governance —
  **49/49 PASS** after fixes. Tier 2: automated sweep of all 130 parameterless GET endpoints —
  **0 server errors**. Evidence: Brata_System_Test_Report.xlsx.

### Fixed
- **BUG-1 (High) — Global Regulations 500.** regdata.json was resolved relative to
  app/routers/ (path regression from the router split); the catalog lives in app/features/.
  Now resolved from the app package root with fallback; a genuinely missing file returns 503.
- **BUG-2 (Medium) — ProAssess 400 on AI shape drift.** Converting AI risks → findings read
  r['note'] (and reputation keys) with bare indexing; off-schema model output raised KeyError
  and failed the whole run. Risk entries are now normalised and read tolerantly
  (note → detail → issue → summary → default); reputation via .get.
- **BUG-3 (Low) — AI ledger rows dropped ('database is locked', SQLite).** The telemetry
  insert fires while the request's own session holds the write transaction, so busy_timeout
  can never win (same-thread self-block). Lock failures now retry on a background thread with
  backoff (1.5s/4s/8s) after the request commits. Residual: a transaction open >13.5s can
  still drop a row on SQLite (logged; Postgres unaffected).

### Investigated & retracted
- Supplier primary-before-backup guard suspected missing — disproven; verified working
  (400 before primary, 409 on second backup) once tested on a vendor with no supplier users.

### Added
- tools/simtest.py — the reusable simulation/regression harness (fake Claude SDK + 49-check
  functional suite + endpoint sweep) used for this pass.

## [4.25.5] — 2026-08-06 · Fix: FDD/Reputation UI stuck on "searching the web…"

### Fixed — Detailed FDD & Reputation never returned a result (spinner never resolved)
- With web search now streaming to completion (v4.25.3), the research call runs the full
  duration (1–3 min for a Detailed run). But the `/research/fdd` and `/research/reputation`
  endpoints ran it **synchronously**, so the browser sat on "Claude is searching the web and
  organising the result…" for the whole time — and behind any proxy/worker request limit it
  could be cut off, leaving the spinner stuck with no result.
- Made research **asynchronous**, matching what the UI already promised ("continues on the
  server and is filed in AI Reports even if you navigate away"):
  - the POST now starts a background job and returns immediately with `{pending, job_id}`;
  - the work runs off the request thread (own DB session) and auto-files the report as before;
  - a new `GET /api/v2/research/status/{job_id}` returns `running` → `done` (full result) or
    `error`; jobs are actor-scoped and GC'd after an hour.
  - the frontend polls every 3s, keeps the spinner alive with an elapsed counter, renders the
    result on completion, surfaces a clear message on error, and after 8 min (or an unknown
    job) falls back to "check Past Reports" — where the report is filed regardless.
- Verified: POST returns immediately (job `running`), polling resolves to `done` with the
  filed report; unknown job ids handled; reputation backgrounds the same way.

### Note
- The job registry is in-memory (single-process, as the app is normally run). Under multiple
  workers a poll may land on another worker and report `unknown`; the client then points the
  user to Past Reports, where the result is filed either way.

## [4.25.4] — 2026-08-06 · Fix: FDD "Could not parse research output"

### Fixed — FDD & Reputation research returned "Could not parse research output; see raw text"
- With web search now completing (v4.25.3), the model's reply interleaves narration and
  search-result text with the answer JSON, may wrap it in one of several markdown fences,
  and appends citations/sources. The old parser (strip one fence, then first-`{`…last-`}`)
  broke on that noise — grabbing the wrong fence, spanning stray braces in narration, or
  choking on trailing prose.
- Added a robust, string-aware JSON extractor (`_extract_json_obj`): it scans fenced blocks
  first, then the whole text, finds every brace-balanced `{...}` object (ignoring braces
  inside quoted strings), and returns the LAST one that parses — i.e. the final answer, not a
  search snippet. Routed both the FDD/reputation and the financials parse paths through it.
- Reduced truncation risk on deep runs: web-search output ceiling 4096 → 8192 tokens, so a
  long research JSON with many sources isn't cut off mid-object (which would be unparseable).
- Verified against realistic shapes: narration + citations + trailing prose, single/multi
  fences, stray braces in narration, clean JSON — all parse; genuinely truncated or prose-only
  output still returns the honest "see raw text" note rather than a wrong parse.

## [4.25.3] — 2026-08-06 · Fix: Detailed FDD & Reputation web-search timeout

### Fixed — "AI research did not complete: APITimeoutError: Request timed out or interrupted"
- Root cause: `ClaudeAdapter.complete()` issued web-search calls with the **non-streaming**
  Messages API (`messages.create`). A Detailed (deep) FDD + Reputation run performs several
  server-side web-search round-trips plus a self-review loop, so the request runs long — and
  a long non-streaming request is dropped by the API ("Request timed out or interrupted",
  per Anthropic's long-requests guidance). Raising the timeout could not fix an *interrupted*
  non-streaming request.
- Fix: web-search calls now **stream** (`messages.stream()` + `get_final_message()`), keeping
  the connection alive for the full research; the accumulated message carries the same content
  and usage, so prompt-caching, the web-search tool, max-tokens and cache-usage logging are all
  preserved. Non-web calls are unchanged (still `messages.create`).
- Gave deep research more headroom now that it streams: `BRO_RESEARCH_TIMEOUT_DEEP` default
  180s → 300s (still env-tunable; shallow stays 90s; web-search floor stays 90s).
- Verified: web-search requests route through the streaming path (the old non-streaming path
  raised the timeout); non-web requests remain on the create path.
- If a very large deep run still needs more time, raise `BRO_RESEARCH_TIMEOUT_DEEP`; ensure the
  provider/model has web-search entitlement in Settings → AI.

## [4.25.2] — 2026-08-05 · Fixes: ProAssess crash + BRO Chat agent highlight

### Fixed — ProAssess: "autonomous assessment failed: name 'deep' is not defined"
- `_proassess_ai()` referenced `deep` but never declared it as a parameter, and
  `run_proassess_autonomous()` called it without passing `deep`. Because `_proassess_ai`
  is always invoked, every ProAssess run crashed with a `NameError` the moment the AI
  engine was connected (the line evaluates `review=bool(deep), timeout_s=(180 if deep else 90)`).
- Added `deep: bool = False` to `_proassess_ai` and pass `deep=deep` from the caller.
  Verified: deep→180s/review, shallow→90s, no NameError.

### Fixed — BRO Chat: active-agent highlight didn't move dynamically
- The streaming turn picked the speaker from the stage's default owner and **ignored
  `sess.active_agent`**, and it **didn't honor `HANDOFF`**. Since most stages default to
  Bro, the highlight (and every message header) stayed on Bro while the model role-played
  Sara/Isaac in the text — so handoffs never moved the floor.
- Now: the router picks the speaker as **@mention > current floor-holder (`active_agent`)
  > stage owner**; an explicit **HANDOFF sets the next active agent** (winning over the
  stage default); each message is attributed to its real sender; and the `done` SSE event
  carries `next_agent` so the highlight advances immediately. The system prompt now forbids
  an agent from writing another agent's lines or narrating a handoff — it must emit HANDOFF
  and stop, so the engine gives the next agent the floor.
- The same routing fix is applied to the non-streaming `/agent/send` path for consistency.
- Verified: Bro → (HANDOFF: scope) → the next turn is spoken by, attributed to, and
  highlighted as Sara; stage advances correctly.

## [4.25.1] — 2026-08-04 · Fix: live web-search research timing out (used 30s instead of the intended limit)

### Fixed — "AI research did not complete: APITimeoutError"
- **Root cause:** in `llm_config.complete()`, the review/deep path (Deep Research) called the
  model **without forwarding `timeout_s`**, so the two web-search research calls silently fell
  back to the 30-second `BRO_LLM_TIMEOUT` default instead of the 75s/150s the research path
  intended. A live web-search research call cannot finish in 30s, so Deep Research (FDD +
  reputation / entity resolution, and any review+web_search caller) timed out almost every time.
- **Fixes:**
  - `complete()` now **forwards `timeout_s`** to both web-search calls in the review loop
    (initial answer + regeneration).
  - `_raw_complete` applies a **web-search timeout floor** — any `web_search=True` call gets at
    least `BRO_WEBSEARCH_MIN_TIMEOUT` (default 90s) even if a caller omits `timeout_s`.
  - FDD/reputation research timeouts are now **env-tunable** with more headroom:
    `BRO_RESEARCH_TIMEOUT` (default 90s) and `BRO_RESEARCH_TIMEOUT_DEEP` (default 180s).
  - Verified: the deep+web_search path now runs at the full timeout (180s), web-search calls are
    floored to 90s, and non-web-search calls are unchanged (30s).

### If it still times out (configuration, not code)
- In **Settings → AI**, confirm the provider shows LIVE AI READY, the **model supports the
  web-search tool**, and the key has **web-search entitlement** — a model/account without web
  search fails regardless of timeout.
- Under provider load, raise the knobs (e.g. `BRO_RESEARCH_TIMEOUT_DEEP=240`, `BRO_LLM_RETRIES=2`).

## [4.25.0] — 2026-08-03 · New feature: BroCall — live voice assessment (OpenAI Realtime)

### Added — BroCall (under Assess)
- A **live voice** TPRM assessment: the caller talks to Bro in the browser over WebRTC using
  **OpenAI's Realtime API** (`gpt-realtime`) as the voice shell, while the **BroAssess methodology
  stays the authority**. The model is instructed to record everything through tools; it must not
  improvise the verdict.
- **Backend** (`app/routers/brocall.py`): session lifecycle, **consent capture** (AI disclosure +
  recording, required before the call — EU AI Act Art. 50), server-side **ephemeral Realtime token**
  minting (the real OpenAI key never reaches the browser; returns `enabled:false` gracefully when no
  key is set), a **function-calling tool bridge** (`update_dossier`, `set_stage`, `record_finding`,
  `request_document`, `compute_verdict`), **transcript persistence**, and a **Calendly webhook** that
  provisions a session on `invitee.created`. `compute_verdict` is **deterministic and risk-averse** —
  residual is derived from the recorded inherent band and findings, and a critical/severe finding
  floors it at HIGH regardless of arithmetic.
- **Frontend** (`app/static/app.js`, `V.brocall`): a consent gate → a live call console with a
  WebRTC client to OpenAI Realtime (mic in, Bro's voice out), a live diarised **transcript**, an
  eight-stage **stepper**, and **dossier / findings / verdict** panels updated as the model calls
  tools. A labelled **tool-bridge simulation** runs the real tools without audio so the pipeline is
  demonstrable without a key.
- Sessions reuse `ConversationSession`, so a BroCall can be captured to an assessment like a BRO Chat;
  every turn, tool call and the verdict are audited.
- **Nav** (`app/web.py`): "BroCall" added to the Assess group.

### Notes
- The live call needs `OPENAI_API_KEY` (and optionally `BROCALL_MODEL`/`BROCALL_VOICE`) on the server
  plus a browser microphone; it does not join Zoom/Teams by itself (that needs a meeting-bot gateway
  such as Recall.ai — see the Live Voice Assessment architecture document). Everything else — session,
  consent, tools, deterministic verdict, transcript, audit, Calendly webhook — runs and is tested
  without any external dependency.

## [4.24.0] — 2026-08-03 · BroAssess: active-agent clarity, seamless flow, in-conversation upload

### Added — in-conversation document upload (stored in DB for audit)
- **📎 Attach button** in the BRO Chat composer. Files are read client-side and posted to a new
  endpoint that persists each one in the document store, tagged to the session
  (`purpose = broassess:<sid>`) and to the engagement when present.
- **Endpoints** (`routers/assessment.py`): `POST /agent/sessions/{sid}/documents` (upload, writes a
  system message into the transcript and audits), `GET /agent/sessions/{sid}/documents` (list), and
  `GET /agent/documents/{doc_id}/download` (retrieve). `get_session` now returns the linked documents.
- **Audit linkage:** on **Capture to assessment**, the session's uploaded documents are re-tagged with
  the resulting engagement (and vendor) id, so every uploaded file is retrievable against the
  assessment record for audit.
- A **Documents (audit)** panel in the left rail lists the files with one-click download.

### Fixed — active-agent clarity (the UX did not show who was working)
- The streaming reply header **hardcoded "BRO"** regardless of which specialist was active. It now
  renders the real active agent (name + role + colour) and updates live from the stream's `meta`
  event as handoffs occur.
- New **active-agent banner** above the chat ("On point: **Isaac** — Information Security Reviewer ·
  Stage n") that updates every turn and mid-stream; the roster row for the active agent is bolder and
  highlighted. Persona name/role in each message are now bold and clearly weighted.

### Changed — conversation flow
- Every agent message now **ends with an explicit next step** — the system prompt requires a final
  `**Ask:** …` (or `**Action:** …`) line, so the user always knows exactly what to do next.

### Notes
- Upload gating matches the existing BroAssess endpoints (`engagement.view`); files are size/type
  validated by the document store (untrusted input) and never executed. Verified end-to-end: upload →
  persisted → listed in session → downloaded byte-for-byte, and the prompt now carries the Ask rule.

## [4.23.1] — 2026-08-01 · Fix: BroAssess conversational memory & dossier persistence

### Fixed — BRO Chat (BroAssess) intake loop
- **Root cause:** the live assessment path gave the model no memory. The session dossier
  was set to `{}` at open and **never written back**, and only the single latest user
  message was sent to the model (no conversation history). With an empty dossier and no
  transcript, Bro could not retain answers, re-asked intake questions indefinitely, and
  never emitted `STAGE_COMPLETE` — so stages never advanced.
- **Conversation memory** (`agent_engine.py`): `run_turn` / `_run_turn_live` /
  `stream_turn` now accept the prior conversation and fold a rendered transcript
  ("CONVERSATION SO FAR …") into the model's user content, with an explicit instruction not
  to re-ask what is already answered and to advance once a stage's information is captured.
- **Dossier persistence** (`routers/assessment.py`, both `/agent/send` and `/agent/stream`):
  the dossier is now merged and written back every turn — structured captures from a new
  fenced ```dossier {…}``` directive plus an accumulating `intake_notes` trail of the user's
  answers — so the "DOSSIER SO FAR" block grows across turns.
- **Prompt** (`agents.py`): the system-prompt rules now instruct the agent to read the
  dossier/transcript as memory, never re-ask, record durable facts via a ```dossier``` block,
  and advance rather than loop; `parse_directives` parses the new block.

### Notes
- Fix targets the live-AI path (the deterministic-local path already advanced on an answer and
  is not reached from the router when AI is off — that returns the holding message). Verified
  end-to-end with a stubbed provider: the transcript reaches the model, the dossier persists
  (vendor/service/data + intake notes), and stages advance 0 → 1 → 2 instead of looping.

## [4.23.0] — 2026-08-01 · New module: TPRM Genie (autonomous discovery → SOW → risk profiling)

### Added — TPRM Genie (under Assess)
- **Backend router** (`app/routers/genie.py`, wired in `bro_app.py` via the RouterDeps
  pattern): a three-phase, human-gated pipeline that reads the connected data sources.
  - **Phase 1 — Discover:** scans `vendor_records` + `engagement_records` → deduplicated
    vendor & engagement inventory with counts and unmanaged-engagement (no-assessment) flags.
  - **Phase 2 — Contract / SOW:** reads `contract_records` (linked by `contract_id` or
    `engagement_id`) and builds a cited **SOW summary for every engagement** — scope,
    business unit, delivery model, value, term, governing law, inferred data-sensitivity and
    gap flags (e.g. no contract on file).
  - **Phase 3 — Risk profile:** compiles a comprehensive profile per vendor from
    `vendor_risk_profile`, `vendor_cyber`, `vendor_screening` and the watchlist — inherent/
    residual band (engagement-derived fallback), cyber rating, breach flag, screening result,
    open findings, monitoring signal — flagging watchlist/sanctions/severe-finding vendors
    for **mandatory human review**.
  - Endpoints: `GET /genie/sources/template`, `POST /genie/run`, `GET /genie/run/{id}`,
    `POST /genie/run/{id}/confirm`, `POST /genie/run/{id}/cancel`. Each phase advances only
    on explicit user confirmation; runs persist in the config store (survive across workers);
    suppliers are blocked (403); every phase is audited.
- **Frontend** (`app/static/app.js`, `V.genie`): a dedicated **TPRM Genie** page (nav under
  Assess) with a clickable pipeline chart. Starting a run first prompts for the **addresses of
  the source databases** (read-only), then opens a **progress window** with a live scan log, a
  three-step stepper, per-phase result previews and **confirm-to-continue** gates (including
  acknowledgement of unmanaged engagements and review-flagged vendors).
- **Nav** (`app/web.py`): "TPRM Genie" entry added to the Assess group.

### Notes
- This build scans the connected Brata registry as the configured data source; enterprise
  deployments bind the captured source addresses to read-only connectors — the phase logic is
  identical. Genie produces a baseline (inventory, SOW summaries, risk profiles); the
  accountable assessment and decision remain with ProAssess and a human reviewer.

## [4.22.5] — 2026-07-11 · New module: Supplier Watchlist + Supplier Notes

### Added — Watchlist module (under Monitor & Manage)
- **Data model** (`registry_models.py`): `WatchlistCriterion`, `SupplierWatchlistEntry`
  (renamed to avoid collision with the existing sanctions-feed `WatchlistEntry`),
  `WatchlistCandidate`, `SupplierNote`; auto-created via `create_all`; ID prefixes
  WLC/WLE/WLK/SNT.
- **Service** (`watchlist_service.py`): criteria CRUD, entries CRUD, database **sweep**
  (evaluates country / keyword / flag rules across the estate → candidates; manual
  criteria are never auto-evaluated), candidate approve/reject, `is_watchlisted`,
  summary, and supplier notes.
- **Criteria seeded from the AOC configuration** (GI 3000.005 App. B single-issue
  triggers & factors, GI 3000.017 trade-compliance) — 9 seeds incl. restricted-country
  exposure (Cuba/Iran/Syria/North Korea/Crimea/Russia), adverse media, under
  investigation, government-owned, shell structures, critical-under-stress.
- **Router** (`routers/watchlist.py`): `/api/v1/watchlist/{criteria,entries,vendor/{id},
  sweep,candidates,candidates/{id}/decide,summary}` and `/api/v1/vendors/{id}/notes`.
- **Frontend**: new **Watchlist** page — KPIs, three tabs (Watchlist / Criteria /
  Sweep candidates), Controller-gated Sweep + add/edit/delete + approve/reject.
- **Supplier 360**: `ON WATCHLIST` flag, watchlist detail panel, and a **Notes** section
  (internal-only). **Supplier Register**: `👁 WATCH` badge. **Management → Risk**: active
  watchlist count.

### Added — governance
- **Engagement sign-off gate**: creating an engagement for a watchlisted supplier returns
  `watchlist_signoff_required`; the autopilot proposal makes human sign-off **mandatory
  irrespective of risk band**.
- **ProAssess** output now captures and explains watchlist status (advisory-only; cannot
  auto-approve a watchlisted supplier).

### RBAC & visibility
- New permissions: `watchlist.view/edit/sweep/approve`, `note.view/note.add`.
- Watchlist and notes are visible to **all internal roles** (buyer, vrm, controller, exec)
  and **hidden from the supplier role** (403 at function level); **mutation is
  Controller-only**. `seed()` now additively reconciles new permissions onto existing
  system roles on boot, so deployments pick up the module without a DB reset.

### Verified
- Seeding, RBAC (buyer view/‌controller edit/‌vendor blocked), sweep (55 candidates on the
  demo estate), approve→entry, notes internal-only, engagement gate, register + 360 flags,
  risk-view count — all tested against a running instance. Demo DB seeded with 9 criteria
  and 3 curated watchlist entries.

## [4.22.4] — 2026-07-11 · Fix 500 on GET/PUT /api/v2/findings/{fid}

### Fixed
- **Finding detail/update crashed with `NameError: FINDING_STATUSES is not defined`.**
  Router extraction left three bare references to `FINDING_STATUSES` in the v2 finding
  handlers (`domain`/`assessment` split) with no in-scope definition, so viewing or
  updating a single finding returned HTTP 500 for every role.
- Added the canonical v2 finding lifecycle as a builder-scoped constant in
  `assessment.py` — `["Draft","Published","Under Remediation","Remediated","Verified","Closed"]`
  — matching `FindingRecord.status` (default "Draft"), the domain.py registry routes and
  the UI. Captured by the handler closures (same pattern domain.py already uses).
- The v1 legacy finding endpoints (int id, legacy `Finding` model) are unchanged — they
  correctly use `eng.FINDING_STATUSES` for that separate model.
- Verified: `GET /api/v2/findings/{fid}` → 200 with the canonical status list; BOLA guard
  from 4.22.3 still enforced (buyer owned → 200, not-owned → 404).

### Note (pre-existing data quality, not a code defect)
- Some seeded findings carry legacy status values ("Open"/"In remediation") outside the
  canonical set; they display correctly but aren't offered as dropdown transitions. A data
  migration to normalise seed statuses is recommended separately.

## [4.22.3] — 2026-07-11 · Fix BOLA (object-level authorization) for vendor & buyer roles

### Security — Fixed
- **Broken Object-Level Authorization (OWASP API #1).** Object-level routes enforced
  the *function* permission (require(perm)) but not object *ownership*, so a scoped
  `vendor` or `buyer` could reach another supplier's object by ID (confirmed: a buyer
  could read `/api/v2/vendors/{vid}/people` — beneficial-owner PII — for vendors outside
  their scope).
- Added a central ownership gate in `app/features/admin/rbac.py`:
  `assert_object_visible(session, user, kind, ident)` — resolves the object's vendor_id
  (engagement / assessment / finding / incident / remediation / person all carry one) and
  raises **404** (not 403, to prevent enumeration) when a scoped role is out of scope.
  Unrestricted roles (admin / vrm / controller / exec) short-circuit with zero extra
  queries.
- Applied the guard to **48 vendor-scoped object routes** across `domain.py`,
  `assessment.py` and `lifecycle.py`.
- Verified: buyer owned → 200, buyer not-owned → 404, admin/vrm unrestricted → 200,
  supplier role blocked at function level (403). No regression (admin 322 vendors,
  buyer scoped to 3).

### Notes
- Scope of this change is the vendor & buyer roles (the roles `scoped_vendor_ids`
  restricts). Legacy int-keyed `/api/v1/vendors|engagements/{id}` routes operate on empty
  legacy tables and fail closed for scoped roles.
- Pre-existing (out of scope, not introduced here): `/api/v2/findings/{fid}` returns 500
  in this build — flagged separately for follow-up.

## [4.22.2] — 2026-07-11 · SSO sign-in on the login screen

### Added
- Login screen now offers single sign-on beneath the credential form: an "OR"
  divider and three provider buttons — Continue with Google, Continue with Apple,
  Continue with SSO (enterprise IdP: Okta / Entra / Ping / Auth0).
- Provider-aware OIDC in `app/features/admin/identity.py`: each provider is
  configured and enabled independently. Enterprise keeps the original
  un-prefixed `BRO_OIDC_*` vars; Google/Apple use `BRO_OIDC_GOOGLE_*` /
  `BRO_OIDC_APPLE_*`. Apple's client secret is minted as an ES256 JWT from the
  Apple key trio when not pre-supplied.
- `GET /auth/oidc/login?provider=` and a `POST /auth/oidc/apple/callback`
  (Apple `response_mode=form_post`). The provider is carried in the signed,
  short-lived `state` token and recovered on callback (CSRF-safe).
- `GET /api/v1/auth/sso-status` now reports per-provider enablement; the UI
  greys out and explains any provider not configured in the environment.

### Unchanged
- Role selector + username/password (incl. admin/admin dev login) untouched —
  the demo flow is fully preserved. SSO buttons are additive.

## [4.22.1] — 2026-07-05 · Supplier "Vendor Page" = Supplier 360

### Changed
- Supplier self-service menu: the "Vendor Page" is now Supplier 360 (vendor360) instead
  of the Supplier Register. Final six-page allowlist: Supplier 360, Engagements,
  Performance Issues, Findings, Issues Log, Remediation Plans.
