# Gap Remediation Progress (issues 1–6) — started 2026-06-22

| # | Gap | Pre-state (v4.5.1) | Action | Status |
|---|-----|--------------------|--------|--------|
| 1 | LLM call timeouts | DONE | Verified: 30s timeout, 2 retries, failover, transient classifier, retry loop fires | ✅ DONE |
| 2 | SQLite WAL | DONE | Verified: journal_mode=WAL, busy_timeout=5000, synchronous=NORMAL | ✅ DONE |
| 3 | Python-side LIKE search | OPEN | SQL-side ilike+limit+archived filter | ✅ DONE |
| 4 | Silent except:pass | PARTIAL | Routed remaining 2 app sites (ai_ledger, platform_docs) through _obs_swallow; 0 silent app sites remain | ✅ DONE |
| 5 | Over-fetching serializers | OPEN | defer(data_b64) + defer(structured_json); cache-bust already present | ✅ DONE |
| 6 | Missing FK indexes | DONE (g6 migration) | Verified 41 indexes at runtime | ✅ DONE |

STATUS: Issues 1-6 ALL REMEDIATED+VERIFIED. UX independent-scroll DONE. Next: docs (B6) + auditor doc (B7).

## COMPLETED 2026-06-22
- Issues 1–6: ALL remediated & verified (timeout/retry/failover, WAL, SQL search, observability, defer slimming, FK indexes)
- tests/test_reliability_fixes.py: 6 tests locking the fixes
- UX: independent scrolling (sidebar + main), viewport-locked #app, thin scrollbars
- TDA §8.2 rewritten as gap register w/ evidence + DONE/ROADMAP; in-system + PDF
- Auditor doc DOC-AUD-TOD-001: 10 control domains, 22 controls, evidence index, design conclusion
- Version 4.5.2; regression green; scrubbed clean
