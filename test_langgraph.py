"""LangGraph orchestration of the 8-stage ProAssess methodology."""
import sys

sys.path.insert(0, "/home/claude/tprm")

from app.agents import langgraph_flow as LG  # noqa: E402
from app.features.assessment import agents as A  # noqa: E402


def test_mermaid_topology_includes_all_stages():
    m = LG.to_mermaid()
    for st in A.STAGES:
        assert f"S{st.id}" in m
    assert "flowchart" in m or "graph" in m.lower()


def test_graph_executes_end_to_end():
    if not LG.LANGGRAPH_AVAILABLE:
        return  # honest skip: langgraph not installed
    final = LG.run_assessment("Test SaaS engagement, low criticality.",
                              dossier={"residual_band": "ELEVATED"})
    stages_seen = {t["stage"] for t in final["transcript"]}
    assert stages_seen.issuperset({st.id for st in A.STAGES})
    assert final["verdict"] and "ESCALATE" in final["verdict"]["decision"]


def test_verdict_tracks_residual_band():
    if not LG.LANGGRAPH_AVAILABLE:
        return
    f = LG.run_assessment("x", dossier={"residual_band": "HIGH"})
    assert "DO NOT PROCEED" in f["verdict"]["decision"]


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
