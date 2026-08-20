"""
Agent conversation engine.

Produces an agent's turn given the conversation state. Two paths:
  - LIVE: if a provider key is configured, route through the Claude adapter using
    the system prompt from agents.build_system_prompt (best quality).
  - LOCAL (default): a deterministic, methodology-faithful stand-in so the full
    eight-stage flow runs and is testable with zero external calls.

The local path is intentionally simple but correct: it asks the right next
question per stage, advances stages, hands off to the right specialist, and at
Stage 7 issues a verdict consistent with the scoring rules in bro_engine.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from app.features.assessment import agents as A
from app.features.assessment import bro_engine as eng


@dataclass
class AgentTurn:
    agent_id: str
    body: str
    stage_complete: Optional[str] = None
    handoff: Optional[str] = None
    research_purpose: Optional[str] = None
    dossier_update: Optional[dict] = None


# Stage-by-stage deterministic scripts for the local path. Each returns the
# question/statement an agent would produce, plus whether the stage completes.
_STAGE_QUESTIONS = {
    0: ("bro", "Drop everything you have on this engagement — proposals, notes, "
                "prior assessments. I will read it and only chase the gaps. If you "
                "have nothing, say so and we start at the intake questions."),
    1: ("bro", "Engagement intake. Who is the supplier, what service do they provide, "
                "and what is the deployment model (SaaS, on-prem, hybrid)?"),
    2: ("scope", "Scope check. What data will the supplier access or process, and is "
                  "any of it personal, special-category, or payment/health data?"),
    3: ("bro", "Scoring inherent exposure across the eight domains now, weighted "
                "InfoSec 30 / Privacy 20 / Resilience 15 / Compliance 10 / Physical 10 / "
                "Org 5 / Reputation 5 / ESG 5."),
    4: ("bro", "Selecting applicable control domains for due diligence based on the "
                "inherent tier — Tier 1 pulls all eight, lower tiers a relevant subset."),
    5: ("infosec", "Due diligence. Evidence over assertion: for the critical controls "
                    "(MFA on external exposure, TLS 1.2+ in transit, AES-128+ at rest, "
                    "tested BC/DR, annual pen test) — what can you substantiate?"),
    6: ("bro", "Computing residual exposure = inherent reduced by demonstrated control "
                "effectiveness. A marginal critical control floors residual at HIGH."),
    7: ("bro", "Decision and memo."),
}


def _verdict_line(dossier: dict) -> str:
    """Stage 7 verdict consistent with bro_engine bands."""
    residual = (dossier or {}).get("residual_band", "MODERATE")
    mapping = {
        "LOW": "APPROVE — annual review cadence.",
        "MODERATE": "APPROVE WITH CONDITIONS — 6-month review.",
        "ELEVATED": "ESCALATE to CISO before proceeding.",
        "HIGH": "DO NOT PROCEED — requires CISO + Legal + CRO sign-off.",
    }
    return mapping.get(residual, "APPROVE WITH CONDITIONS — 6-month review.")


def _live_available() -> bool:
    from app.agents import llm_config
    return llm_config.is_enabled()


def _render_history(history, limit: int = 24) -> str:
    """Render the recent conversation into a transcript the model can read as memory.
    Without this the live model sees only the latest message and loops on intake."""
    if not history:
        return ""
    rows = []
    for m in history[-limit:]:
        who = "User" if m.get("role") == "user" else \
            A.AGENTS.get(m.get("agent") or "bro", {}).get("name", "Bro")
        body = (m.get("body") or "").strip()
        if body:
            rows.append(f"{who}: {body}")
    return "\n".join(rows)


def run_turn(agent_id: str, stage: int, dossier: dict, learnings: list[str],
             user_message: Optional[str], methodology: str = "",
             briefs=None, deep: bool = False, history=None) -> AgentTurn:
    """Produce one agent turn. Local-deterministic unless a live key is set.
    When ``deep`` (Deep Research mode) the live path runs the self-review loop
    for a more thorough answer; otherwise it is a fast single pass. ``history`` is
    the prior conversation, passed to the live model as memory."""
    if _live_available():
        try:
            return _run_turn_live(agent_id, stage, dossier, learnings, user_message,
                                  methodology, briefs, deep=deep, history=history)
        except Exception:
            pass  # fall back to local on any live failure

    return _run_turn_local(agent_id, stage, dossier, learnings, user_message)


def _run_turn_local(agent_id: str, stage: int, dossier: dict,
                    learnings: list[str], user_message: Optional[str]) -> AgentTurn:
    owner, question = _STAGE_QUESTIONS.get(stage, ("bro", "Continue."))
    # The agent who owns the stage speaks; if a different agent was asked, hand off.
    if agent_id != owner and stage not in (3, 6, 7):
        return AgentTurn(agent_id=agent_id, body=f"Passing to {A.AGENTS[owner]['name']} for this stage.",
                         handoff=owner)

    # If the user has answered (any message), treat the stage as progressable.
    answered = bool(user_message and user_message.strip()
                    and user_message.strip().lower() not in {"nothing", "none", "n/a"})

    if stage == 7:
        verdict = _verdict_line(dossier)
        body = (f"Verdict. {verdict} This closes the eight-stage assessment. "
                "Findings fed the score; the decision rests on residual exposure, not arithmetic alone.")
        return AgentTurn(agent_id="bro", body=body, stage_complete="Decision issued.")

    if stage in (3, 4, 6):
        # computed/transition stages — state the action and complete
        return AgentTurn(agent_id=owner, body=question,
                         stage_complete=f"Stage {stage} computed.")

    # intake/question stages: ask, and complete once the user has answered
    if answered:
        return AgentTurn(agent_id=owner, body=f"Noted. {question}",
                         stage_complete=f"Stage {stage} captured.")
    return AgentTurn(agent_id=owner, body=question)


def _run_turn_live(agent_id: str, stage: int, dossier: dict,
                   learnings: list[str], user_message: Optional[str],
                   methodology: str = "", briefs=None, deep: bool = False,
                   history=None) -> AgentTurn:
    """Live path: call the configured provider (Claude or OpenAI) via llm_config.
    Imported lazily so the app runs without the SDKs installed. The prior
    conversation is folded into the user content so the model has memory."""
    from app.agents import llm_config
    system = A.build_system_prompt(agent_id, stage, dossier, learnings, methodology, briefs)
    name = A.AGENTS.get(agent_id, A.AGENTS["bro"])["name"]
    transcript = _render_history(history)
    parts = []
    if transcript:
        parts.append("CONVERSATION SO FAR (already answered — do NOT re-ask any of this):\n"
                     + transcript)
    parts.append("User: " + (user_message or f"[Begin Stage {stage}.]"))
    parts.append(
        f"Respond now as {name}, continuing the assessment from the latest user message. "
        "Use the dossier and the conversation above as your memory; never re-ask what is already "
        "known. Record any durable fact with a ```dossier {…}``` block. Advance with "
        "'STAGE_COMPLETE: <why>' once this stage's information is captured (or the user asks to "
        "proceed and the essentials are in hand) — do not loop.")
    user = "\n\n".join(parts)
    # Fast Track: single pass, short fail-fast timeout. Deep Research: self-review loop.
    text = llm_config.complete(system, user,
                               domain=agent_id, review=bool(deep),
                               timeout_s=(120 if deep else 45))
    if not text:
        raise RuntimeError("no LLM text")
    parsed = A.parse_directives(text)
    return AgentTurn(
        agent_id=agent_id, body=parsed.body or "(no content)",
        stage_complete=parsed.stage_complete,
        handoff=parsed.handoff["to"] if parsed.handoff else None,
        dossier_update=parsed.dossier_update or None,
    )


# --- BACKGROUND CONSISTENCY CHECK (Sara, silent) ------------------
def consistency_check(dossier: dict, user_message: str,
                      learnings: list[str]) -> list[dict]:
    """Deterministic contradiction / practicality scan. Returns insight dicts.
    Mirrors the JSX 'runConsistencyCheck' output shape."""
    insights: list[dict] = []
    msg = (user_message or "").lower()

    # practicality heuristics
    if "100%" in msg or "never fails" in msg or "fully secure" in msg:
        insights.append({"kind": "practicality", "severity": "medium",
                         "claim": user_message[:80],
                         "concern": "Absolute assurance claim — verify with evidence."})
    if "no data" in msg and dossier.get("data_types"):
        insights.append({"kind": "contradiction", "severity": "high",
                         "with": "data_types in dossier",
                         "issue": "User now says no data, but data types were recorded earlier."})
    # cross-border vs tier
    if "cross-border" in msg and dossier.get("tier") == "Tier 3":
        insights.append({"kind": "contradiction", "severity": "medium",
                         "with": "tier=Tier 3",
                         "issue": "Cross-border transfer is unusual for a Tier 3 (no-data) engagement."})
    return insights


def stream_turn(agent_id: str, stage: int, dossier: dict, learnings: list[str],
                user_message: Optional[str], methodology: str = "", briefs=None,
                history=None):
    """Yield the lead agent's reply as text deltas for near-real-time chat.
    Single-pass, no review loop, short fail-fast timeout. Yields nothing if AI is
    not live (the caller then emits its holding message). The prior conversation is
    folded into the user content so the model has memory and does not loop."""
    from app.agents import llm_config
    system = A.build_system_prompt(agent_id, stage, dossier, learnings, methodology, briefs)
    name = A.AGENTS.get(agent_id, A.AGENTS["bro"])["name"]
    transcript = _render_history(history)
    parts = []
    if transcript:
        parts.append("CONVERSATION SO FAR (already answered — do NOT re-ask any of this):\n"
                     + transcript)
    parts.append("User: " + (user_message or f"[Begin Stage {stage}.]"))
    parts.append(
        f"Respond now as {name}, continuing from the latest user message. Use the dossier and "
        "conversation above as memory; never re-ask what is known. Record durable facts with a "
        "```dossier {…}``` block, and advance with 'STAGE_COMPLETE: <why>' once captured — do not loop.")
    user = "\n\n".join(parts)
    for delta in llm_config.stream_complete(system, user, domain=agent_id, timeout_s=45):
        yield delta
