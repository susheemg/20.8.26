# BRO Port Plan — uploaded Flask app → our FastAPI engine

## Goal
Port ALL features of the uploaded `bro-risk-oracle-unified` Flask application
into our tested FastAPI codebase, WITHOUT losing the disciplined core that makes
ours worth porting into: the tested policy/evidence/rating engine, the calibration
harness (shadow→graduate→sample→demote), per-domain provider pinning, and the
fail-safe verdict parser.

## What the uploaded app actually contains (measured, not guessed)
- **94 routes** in a 125KB `app.py` (web UI + REST + admin)
- **39 database tables** in `database.py` (SQLite, seeded)
- **50+ Jinja templates** (full server-rendered UI, 3 dashboards, vendor portal)
- **7 supporting modules**: engine (scoring/hash/terms), ai (12 analyser fns +
  Claude call + local fallback), autopilot, conversation, assessment_chat,
  notify (email + 11 lifecycle hooks + webhooks), mcp_server (14 tools)

## Reconciliation principle
Three buckets for every uploaded feature:
1. **Already have it (keep ours)** — policy resolution, evidence precedence,
   ratings/Tier-0, escalation, calibration, ingestion, scoring bands, lifecycle
   state machine, hash-chained audit, two-gate actions. Their equivalents are
   thinner; we map their routes onto our engine.
2. **Port it (they have, we don't)** — see feature groups below.
3. **Improve in the port** — where they use a local heuristic and we have a
   tested component (e.g. their evidence_analyze → our Phase 5 ingestion +
   classification; their ai._extract_json → our hardened verdict_parser).

## Feature groups → port sequence (each ≈ one session)

### GROUP A — Persistence + auth foundation  [DO FIRST]
- SQLAlchemy models over our schema.sql + their 39 tables reconciled
- Replace in-memory Store with a real repository
- Users, roles, 37 permissions, RBAC dependency for FastAPI
- Sessions/login (their /login, /logout, vendor portal)
WHY FIRST: every other route needs persistence + an actor identity to audit.

### GROUP B — Core lifecycle routes onto our engine
- vendors, engagements, IRQ, DDQ, record/submit/review/override/terminate
- findings + advancement, acceptances, certifications
- Maps onto our scoring.py + lifecycle.py + two-gate model (already tested)

### GROUP C — Intelligence engines (Vera/Mira/Matt/Isaac)
- Financial DD, Reputation/ESG, Contracts terms+gap, Evidence check
- Isaac → reuse our Phase 5 ingestion; others → ported analysers with the
  deterministic-local default + LLM path via our provider abstraction
- All LLM output through our verdict_parser (improve-in-port)

### GROUP D — Monitoring lifecycle
- monitoring sweeps, reassessments (periodic/triggered/delta), evidence expiry,
  security ratings, screening, incidents, BIA, performance, obligations, trending

### GROUP E — Notifications + email + webhooks
- 11 lifecycle notification hooks, email outbox (simulation default), webhooks
- in-app notifications + unread count

### GROUP F — Conversational + autopilot + assessment chat
- conversation sessions/messages, autopilot (propose IRQ/DDQ/decision),
  adaptive assessment chat — routed through our agent + escalation + provider layers
- This is where our Q1 role/visibility model and escalation engine add real value

### GROUP G — Admin + integrations + MCP + procurement APIs
- admin users/roles/integrations/email/ai-keys, webhooks
- MCP server (14 tools) re-exposed over our app
- procurement PO API, SAP/ProcessUnity integration seams, regulatory export

### GROUP H — UI layer
- Port templates OR expose as API + note a frontend is a separate build
- DECISION NEEDED from user: server-rendered Jinja (match theirs) vs API-only

## Test discipline (non-negotiable)
Every group ships with tests in the same style; the running total must never
regress. Their 30KB test_e2e.py is a reference oracle — we port its assertions
as we port features, so behaviour parity is provable, not assumed.

## Status
- [x] Group A — Persistence + auth + RBAC  ✓ DONE (9 tests)
- [x] Group B — Core lifecycle routes  ✓
- [x] Group C — Intelligence engines (deterministic-local)  ✓
- [x] Group D — Monitoring lifecycle (core)  ✓
- [x] Group E — Notifications + webhooks (core)  ✓
- [x] Group F — Conversational + autopilot  ✓
- [x] Group G — MCP tools + procurement (core)  ✓
- [ ] Group H — UI
