"""LangGraph orchestration of the BRO ProAssess multi-agent assessment.
Eight-stage methodology as a StateGraph; each stage node runs the existing
deterministic/agentic engine, so it executes with or without a live LLM."""
from __future__ import annotations

from typing import Optional, TypedDict

from app.features.assessment import agents as A
from app.features.assessment import agent_engine as AE


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line.
    Never raises — observability must not change control flow."""
    try:
        from app.features.admin.security import log_json as _lj
    except Exception:
        try:
            from app.features.admin.security import log_json as _lj
        except Exception:
            return
    try:
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass


try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover
    StateGraph = None  # type: ignore
    END = "__end__"  # type: ignore
    LANGGRAPH_AVAILABLE = False

_MAX_HANDOFFS = 2


class AssessState(TypedDict, total=False):
    free_text: str
    stage: int
    dossier: dict
    learnings: list
    transcript: list
    verdict: Optional[dict]


def _node_name(st: "A.Stage") -> str:
    owner = A.route_next_agent(st.id)
    return f"S{st.id}_{st.short}_{A.AGENTS[owner]['name']}"


def _resolve_methodology(session=None) -> str:
    """The methodology that should guide ProAssess.

    When a DB session is available, ProAssess is guided by the firm's
    methodology documents in the Methodology folder (the active
    ``methodology_doc`` rows) — the SAME source BRO Chat uses. With no
    methodology loaded it returns the best-practice directive; with no session
    at all it falls back to the built-in default constant.
    """
    if session is not None:
        try:
            from app.features.assessment import methodology as _M
            directive = _M.methodology_directive(session)
            if directive:
                return directive
        except Exception as _e:
            _obs_swallow('langgraph_flow.py', _e)
    return A.METHODOLOGY


def _make_stage_node(stage_id: int, methodology: str = A.METHODOLOGY):
    def _node(state: AssessState) -> dict:
        dossier = state.get("dossier") or {}
        learnings = state.get("learnings") or []
        msg = state.get("free_text") or "Proceed."
        owner = A.route_next_agent(stage_id)
        transcript = list(state.get("transcript") or [])
        turn = AE.run_turn(owner, stage_id, dossier, learnings, msg, methodology)
        transcript.append({"stage": stage_id, "agent": turn.agent_id, "body": turn.body})
        hops = 0
        while getattr(turn, "handoff", None) and hops < _MAX_HANDOFFS:
            turn = AE.run_turn(turn.handoff, stage_id, dossier, learnings, msg, methodology)
            transcript.append({"stage": stage_id, "agent": turn.agent_id, "body": turn.body})
            hops += 1
        out: dict = {"stage": stage_id + 1, "transcript": transcript}
        if stage_id == A.STAGES[-1].id:
            out["verdict"] = {"decision": AE._verdict_line(dossier),
                              "residual_band": (dossier or {}).get("residual_band", "MODERATE"),
                              "by": turn.agent_id, "summary": turn.body}
        return out
    return _node


def build_graph(session=None):
    if not LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed (pip install langgraph); "
                           "to_mermaid() works without it.")
    g = StateGraph(AssessState)
    methodology = _resolve_methodology(session)  # firm methodology folder → guides every stage
    names = [_node_name(st) for st in A.STAGES]
    for st, name in zip(A.STAGES, names):
        g.add_node(name, _make_stage_node(st.id, methodology))
    g.set_entry_point(names[0])
    for i in range(len(names) - 1):
        g.add_edge(names[i], names[i + 1])
    g.add_edge(names[-1], END)
    return g.compile()


def run_assessment(free_text: str = "", *, dossier: Optional[dict] = None,
                   learnings: Optional[list] = None, session=None) -> dict:
    app = build_graph(session=session)
    return app.invoke({"free_text": free_text or "Proceed.", "stage": 0,
                       "dossier": dossier or {}, "learnings": learnings or [],
                       "transcript": [], "verdict": None})


def to_mermaid(session=None) -> str:
    if LANGGRAPH_AVAILABLE:
        try:
            return build_graph(session=session).get_graph().draw_mermaid()
        except Exception as _e:
            _obs_swallow('langgraph_flow.py', _e)
    lines = ["flowchart TD", "    __start__([start]) --> S0"]
    for st in A.STAGES:
        owner = A.AGENTS[A.route_next_agent(st.id)]["name"]
        lines.append(f'    S{st.id}["Stage {st.id} · {st.name}<br/>owner: {owner}"]')
    for i in range(len(A.STAGES) - 1):
        lines.append(f"    S{A.STAGES[i].id} --> S{A.STAGES[i+1].id}")
    lines.append(f"    S{A.STAGES[-1].id} --> __end__([verdict])")
    return "\n".join(lines)
