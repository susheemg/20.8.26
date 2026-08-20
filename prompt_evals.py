#!/usr/bin/env python3
"""
Prompt evaluation harness (AI governance).

Golden-set regression over the prompt registry + the deterministic assessment
engines, so prompt edits and model/provider changes can't silently degrade
behaviour. Run: python3 prompt_evals.py
"""
import sys

sys.path.insert(0, ".")
FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    from app.features.assessment import prompts as P
    from app.features.assessment import agents as A

    # 1. Registry integrity
    d = P.defaults()
    check("registry: 30+ prompts registered", len(d) >= 30, str(len(d)))
    for key, meta in d.items():
        check(f"registry: {key} has non-empty default", bool((meta.get("default") or "").strip()))
        check(f"registry: {key} grouped", meta.get("group") in P.GROUP_ORDER, str(meta.get("group")))
    check("rubric demands strict JSON", "JSON" in d["assessment_rubric"]["default"])
    check("viny persona is exit-specialist", "exit" in d["exit_plan_persona"]["default"].lower())
    for aid in A.AGENTS:
        check(f"persona default matches brief: {aid}",
              d[f"agent_persona_{aid}"]["default"] == A.AGENT_BRIEFS.get(aid, ""))

    # 2. Deterministic goldens — the offline engines the AI paths must agree with
    from app.features.lifecycle.exit_planning import deterministic_draft
    g = deterministic_draft({"vendor_name": "GoldenCo", "is_critical": True, "services": ["Payments"],
                             "dependencies": [], "existing_alternatives": [], "residual_band": "HIGH",
                             "contract_exit_clause": False, "tier": "Tier 1", "hq_country": "GB",
                             "vendor_id": "VEN-G", "engagement_count": 1})
    check("golden exit: critical -> multi_source", g["strategy_type"] == "multi_source")
    check("golden exit: stressed window present", "stressed" in g["target_window"])
    check("golden exit: missing clause flagged", "exit/assistance clause" in g["rationale"])
    check("golden exit: 6 steps", len(g["steps"]) == 6)

    from app.features.assessment import agent_engine as AE
    check("golden verdict: HIGH -> DO NOT PROCEED",
          "DO NOT PROCEED" in AE._verdict_line({"residual_band": "HIGH"}))
    check("golden verdict: ELEVATED -> ESCALATE",
          "ESCALATE" in AE._verdict_line({"residual_band": "ELEVATED"}))

    # 3. Output-validation goldens
    from app.features.assessment.ai_json import parse_json_strict, wrap_untrusted
    check("ai_json: clean parse", parse_json_strict('{"a":1}') == {"a": 1})
    check("ai_json: fenced parse", parse_json_strict('```json\n{"a":1}\n```') == {"a": 1})
    check("ai_json: prose rejected", parse_json_strict("I think the risk is high.") is None)
    check("ai_json: missing keys rejected",
          parse_json_strict('{"a":1}', required_keys=("b",)) is None)
    check("ai_json: untrusted wrap tags", wrap_untrusted("x").startswith("<untrusted_document>"))

    print(f"\n{'ALL GREEN' if not FAILS else str(len(FAILS)) + ' FAILURES'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
