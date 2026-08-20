# TPRM Platform — AI-First Vendor Risk (Phases 0–2)

Comprehensive, multi-domain, AI-first TPRM platform. AI delivers assessments;
humans validate by exception and authorise all consequential actions.

## What's built (33 tests passing)

### Phase 0 — the policy spine
- `models/policy.py` — canonical controls, overlays, custom controls, effective controls
- `core/resolution.py` — deterministic baseline+overlay merge
- `core/snapshot.py` — content-hashed frozen policy at assessment start
- `core/audit.py` — append-only, hash-chained, tamper-evident trail

### Phase 1 — actors, evidence, ratings
- `models/evidence.py` + `core/evidence_resolution.py` — trust ladder
  (audit > attestation > chat; assessor above all), recency gating, conflict-as-finding
- `models/rating.py` + `core/rollup.py` — Tier 1–4 computed, Tier 0 human-only;
  domain→engagement (worst-of), engagement→vendor (worst-of + concentration overlay)

### Phase 2 — AI delivery + escalation (the heart)
- `agents/provider.py` — multi-provider (Claude + ChatGPT), per-domain pinning
- `agents/escalation.py` — confidence × impact gate + mandatory-escalation modifiers
  (Tier 0, roll-up band change, evidence conflict, policy-lags-baseline);
  shadow mode escalates everything until a domain is calibrated
- `agents/agent.py` — structured verdict contract with full provenance
- `agents/actions.py` — second gate: actions ALWAYS need human agreement;
  informational notifications auto-fire, consequential ones are gated

## The two safety properties this design guarantees
1. **Nothing auto-delivers unless earned.** Shadow mode → calibrate per
   (domain × provider) → gated auto-delivery. The escalation engine is the only
   thing between a confident wrong answer and the customer; every modifier that
   should force human review is tested to do so.
2. **AI-first assessment, human-gated consequence.** Findings may auto-deliver;
   real-world actions never do without explicit human agreement.

## Run all tests
```bash
for p in 0 1 2; do python3 tests/test_phase$p.py; done
```

## Decisions locked (driving the build)
- All risk domains, comprehensive COVERAGE; automation earned per-domain
- Chat used by both vendor and assessor in shared engagements → role/trust + visibility
- Ratings: engagement × domain → vendor; worst-of + concentration
- Actions: propose, execute on human agreement (two-gate model)
- Evidence: audit > attestation > chat, recency-gated, conflicts recorded
- Scale: Tier 0–4, Tier 0 human-only; single Postgres + object storage

## Not yet built (next layers)
- LLM adapters (real Claude/OpenAI calls behind the Protocol) + JSON→verdict parsing
- Calibration harness: shadow-mode logging, calibration curves, threshold setting
- Random sampling of auto-delivered outputs (catches silent misses post-cutover)
- Adaptive chat orchestration, document ingestion/extraction, RAG (pgvector)
- FastAPI surface + persistence wiring (SQLAlchemy over schema.sql)

### Phase 3 — calibration harness (makes AI-first real, not hoped)
- `calibration/observation.py` — pairs every AI verdict with the human decision
  in shadow mode; flags silent misses (auto-delivered, wrong, needed a human)
- `calibration/analysis.py` — reliability curve + ECE (is confidence honest?),
  escalation recall/precision, and a graduation gate that REFUSES to leave
  shadow mode unless data volume, calibration, recall and silent-miss bars all clear
- `calibration/sampling.py` — deterministic post-cutover sampling of
  AUTO-DELIVERED outputs + drift check that auto-demotes a domain back to
  shadow mode if silent misses creep above tolerance

## The full trust lifecycle now in code
shadow (escalate everything) → log observations → analyse calibration →
graduate ONLY if earned → auto-deliver within gates → randomly sample live
outputs → demote on drift. Trust is continuously earned, never assumed.

Total: 42 tests passing across 4 phases.

### Phase 4 — LLM adapters + verdict parsing (reliability layer)
- `agents/prompt.py` — renders effective control + resolved evidence into a
  JSON-only prompt; applies tenant terminology so the model speaks the enterprise's language
- `agents/verdict_parser.py` — turns messy model text (fences, preamble, string
  tiers, out-of-range values, malformed JSON) into a VALIDATED verdict; raises
  on anything it cannot trust. Provenance is system-supplied, never trusted to the model
- `agents/adapters.py` — production-ready Claude (Messages API) and OpenAI
  (Chat Completions) adapters behind the LLMProvider Protocol; drop in a key and run
- `agents/agent.py::safe_assess_and_gate` — FAIL-SAFE: an unparseable verdict
  becomes a mandatory human escalation, never a crash and never an auto-deliver

Note: live API calls aren't exercised by tests (no keys/egress in this env).
The 18 Phase-4 tests cover prompt building + the parser, which is where
reliability is actually determined. The adapters are thin and SDK-shaped.

Total: 60 tests passing across 5 phases.

### Phase 5 — document ingestion -> typed evidence
- `ingestion/extract.py` — pluggable extractors (TextExtractor runnable now;
  PdfExtractor/OCR are seams that RAISE rather than silently return empty text,
  which would understate risk) + classifier mapping DocType -> SourceType so a
  document's type drives evidence precedence
- `ingestion/pipeline.py` — extract -> classify -> derive validity window ->
  emit typed Evidence -> dedup. Low-confidence/unknown classification routes the
  whole document to a human before its evidence is trusted. Author role is set
  from source type, never guessed (trust is never silently upgraded)

End-to-end test proves an ingested SOC 2 correctly outranks an ingested chat
claim through the real precedence resolver, with the contradiction recorded.

Note: live PDF/OCR parsing of real binaries needs production libraries + real
files; the pipeline INTELLIGENCE (classification, evidence typing, precedence,
dedup, human-routing) is fully tested. Drop a PDF library into PdfExtractor.

Total: 68 tests passing across 6 phases.

### Phase 6 — BRO application surface (FastAPI over the engine)
- `core/scoring.py` — six-domain exposure banding (HIGH≥70 / ELEVATED 50-69 /
  MODERATE 30-49 / LOW<30) + critical-control override (any critical MARGINAL/FAILED
  forces residual HIGH) + straight-through routing (AUTO-APPROVE/FAST-TRACK/FULL)
- `core/lifecycle.py` — 10-stage state machine (Sourcing→…→Terminate) with
  enforced legal transitions, stage notifications, monitoring→reassessment loop
- `api.py` — FastAPI REST under /api/v1: vendors, engagements, triage, inherent
  scoring + routing, decision with VRM/justified-override (human-only, needs
  reason + 2nd approver), audit verification, health. In-memory store so it RUNS
  with no DB/key; SQLAlchemy-over-schema.sql is the production drop-in.

## Run the reference app
```bash
pip install -r requirements.txt
python run.py     # http://127.0.0.1:8000/docs
```

## How this maps to the BRO compendium
- Six-domain exposure + bands + confidence → scoring.py + rating/escalation engine
- Residual + VRM sign-off + justified override + immutable audit → api.py + audit.py
- Isaac (SOC 2/ISO parsing → DDQ controls) → Phase 5 ingestion + classification
- Evidence expiry / next-validation → Phase 1 validity windows + recency gating
- Critical-control MARGINAL → residual HIGH → scoring.py critical override
- 10 lifecycle stages + notifications → lifecycle.py
- Deterministic offline fallback → default analyser; live LLM path when key present

Total: 79 tests passing across 7 phases. App boots with 12 routes.
