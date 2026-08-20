#!/usr/bin/env bash
# Release gate (AI-01/AI-02). No release without these passing.
# Per-dimension thresholds live in tools/eval_assessment.py and are never blended.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
FAIL=0
run () { echo; echo "── $1"; shift; "$@"; local rc=$?
         [ $rc -eq 0 ] && echo "   PASS" || { echo "   FAIL (exit $rc)"; FAIL=1; }; }

run "Prompt registry & deterministic goldens"  python3 prompt_evals.py
run "Assessment quality evaluation"            python3 tools/eval_assessment.py
run "Functional regression & endpoint sweep"   python3 tools/simtest.py

echo; echo "═══════════════════════════════════════"
[ $FAIL -eq 0 ] && echo "RELEASE GATE: PASS" || echo "RELEASE GATE: BLOCKED"
exit $FAIL
