"""Tests for the relevance-first reasoning contract in the management/analysis
AI path: the model is told to weigh internal vs external data and use only what is
relevant, attached external signals are relevance-gated, internal-only questions get
no external block, and structured (review=False) callers are untouched."""
import sys, os
sys.path.insert(0, "/home/claude/tprm")
import app.agents.llm_config as L


def _arm():
    """Force the review branch on and capture the prompts via a fake raw-complete."""
    os.environ["BRO_LLM_REVIEW"] = "1"
    L.is_enabled = lambda: True
    L._sdk_installed = lambda p: True
    L.configured_provider = lambda: "anthropic"
    calls = []
    scores = iter([9])

    def fake_raw(system_prompt, user_content, domain="general", web_search=False, max_tokens=None):
        calls.append((domain, system_prompt, user_content))
        if domain == "review":
            try:
                sc = next(scores)
            except StopIteration:
                sc = 9
            return '{"score": %d, "externally_influenced": false, "critique": "ok"}' % sc
        return "DRAFT ANSWER"

    L._raw_complete = fake_raw
    return calls, (lambda s: [c[1] for c in calls if c[0] == "management"][0].__contains__(s))


def test_relevance_contract_injected():
    calls, has = _arm()
    L.complete("SYS", "Which engagements are overdue?", domain="management", review=True)
    assert has("RELEVANCE FIRST") and has("FILTER BY RELEVANCE")


def test_external_signals_attached_and_gated():
    calls, has = _arm()
    L.complete("SYS", "Assess geopolitical exposure of my estate", domain="management", review=True,
               external_context="OSS / SBOM exposure (external): 68% coverage, 6 KEV.",
               pestle_context="political instability (72)")
    assert has("use STRICTLY per relevance")
    assert has("OSS / SBOM exposure") and has("PESTLE signal")


def test_internal_only_has_no_external_block():
    calls, has = _arm()
    L.complete("SYS", "List my highest-value engagements", domain="management", review=True)
    assert has("RELEVANCE FIRST")
    assert not has("ATTACHED DATA SIGNALS")


def test_structured_caller_unchanged():
    calls, _ = _arm()
    out = L.complete("SYSX", "extract json", domain="general", review=False)
    assert out == "DRAFT ANSWER"
    assert calls[0][1] == "SYSX"  # no contract appended for structured callers


def test_low_score_triggers_regeneration():
    os.environ["BRO_LLM_REVIEW"] = "1"
    L.is_enabled = lambda: True
    L._sdk_installed = lambda p: True
    L.configured_provider = lambda: "anthropic"
    gen = {"n": 0}
    scores = iter([4, 9])

    def fake_raw(system_prompt, user_content, domain="general", web_search=False, max_tokens=None):
        if domain == "review":
            try:
                sc = next(scores)
            except StopIteration:
                sc = 9
            return '{"score": %d, "externally_influenced": false, "critique": "be more specific"}' % sc
        gen["n"] += 1
        return f"ANSWER v{gen['n']}"

    L._raw_complete = fake_raw
    out = L.complete("SYS", "internal question", domain="management", review=True, min_score=8, max_rounds=2)
    assert gen["n"] >= 2          # a low score forced a regeneration
    assert out in ("ANSWER v1", "ANSWER v2")


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception:
            print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
