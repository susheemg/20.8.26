"""
Conversational multi-agent assessment — server-side core.

Ports the agent registry, eight-stage methodology, directive parsing and
orchestration routing from the uploaded BRO agent UI into tested backend logic.
The chat surface (app/web.py) and API (app/bro_app.py) sit on top of this.

Design: deterministic and offline by default. When a provider key is present,
agent turns can route through the live Claude adapter; without one, a
deterministic stand-in produces structured, methodology-faithful turns so the
whole flow is demonstrable and testable with no external calls.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line.
    Never raises — observability must not change control flow."""
    try:
        from app.features.admin.security import log_json as _lj
    except Exception:
        return
    try:
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass



# --- AGENT REGISTRY (faithful to the JSX) -------------------------
AGENTS: dict[str, dict] = {
    "bro":        {"name": "Bro",    "title": "Risk Oracle — Lead",              "color": "#0F1419"},
    "scope":      {"name": "Sara",   "title": "Scope & Completeness Lead",       "color": "#335577"},
    "infosec":    {"name": "Isaac",  "title": "Information Security Reviewer",    "color": "#1A4D3C"},
    "resilience": {"name": "Rhea",   "title": "Operational Resilience / BCM",    "color": "#7A4F2E"},
    "privacy":    {"name": "Priya",  "title": "Privacy & Data Protection",       "color": "#5C3A6B"},
    "reputation": {"name": "Mira",   "title": "Reputation & Conduct Risk",       "color": "#8A2E3B"},
    "compliance": {"name": "Connor", "title": "Compliance & Regulatory",         "color": "#2E4A5C"},
    "physical":   {"name": "Finn",   "title": "Physical & Environmental",        "color": "#4A4A4A"},
    "esg":        {"name": "Elara",  "title": "ESG & Ethical Sourcing",          "color": "#3D6B3D"},
    "researcher": {"name": "Rex",    "title": "Public Data Researcher",          "color": "#967037"},
}

AGENT_BRIEFS: dict[str, str] = {
    "bro": "Senior TPRM consultant and lead orchestrator. Direct, confident, dryly witty, never compromises on rigour. Decides which specialist owns each turn and issues the final verdict at Stage 7.",
    "scope": "Scope & Completeness Lead. Ensures the full footprint of the engagement is captured; flags anything missing; never lets a contradiction slide.",
    "infosec": "Information Security Reviewer. Assesses data exposure, access profile, technology integration. Demands evidence over assertion.",
    "resilience": "Operational Resilience & BCM. Asks: if this vendor goes dark tomorrow, what happens to us? RTO, RPO, sub-contractor concentration, exit strategy.",
    "privacy": "Privacy & Data Protection. Personal data, special categories, cross-border transfers, lawful basis, subject rights, retention.",
    "reputation": "Reputation & Conduct. If this engagement misfires, what does the front page look like? Brand usage, conduct, adverse media, ESG signals.",
    "compliance": "Compliance & Regulatory. GDPR, DORA, FCA outsourcing, sanctions, AML, anti-bribery. Maps the regulatory perimeter the engagement creates for us.",
    "physical": "Physical & Environmental. Site access, hardware delivery, premises controls, environmental risks at data centres.",
    "esg": "ESG & Ethical Sourcing. Modern slavery, environmental commitments, sanctions adjacency, supply-chain ethics.",
    "researcher": "Public Data Researcher. Fetches verifiable public facts about the supplier — size, listing status, enforcement, breach history, substitutability — and presents them concisely.",
}


# --- EIGHT STAGES -------------------------------------------------
@dataclass(frozen=True)
class Stage:
    id: int
    name: str
    short: str


STAGES: list[Stage] = [
    Stage(0, "Context Dump", "Context"),
    Stage(1, "Engagement Details", "Intake"),
    Stage(2, "Inherent Risk Questionnaire", "IRQ"),
    Stage(3, "Inherent Risk Rating", "IRR"),
    Stage(4, "Control Domain Selection", "Scoping"),
    Stage(5, "Due Diligence (DDQ)", "DDQ"),
    Stage(6, "Residual Risk", "Residual"),
    Stage(7, "Decision & Memo", "Decision"),
]

METHODOLOGY = (
    "BRO METHODOLOGY — eight stages, no skipping. Exposure first. Controls second. "
    "Verdict last. Exposure (inherent) is what the engagement creates by its nature; "
    "controls (residual) are what the vendor brings to reduce it. Certifications, SOC 2, "
    "DPA reduce RESIDUAL, never INHERENT. Inherent domains and weights: InfoSec 30%, "
    "Privacy 20%, Resilience 15%, Compliance 10%, Physical 10%, Org 5%, Reputation 5%, "
    "ESG 5%. Bands: >=85% LOW, 70-84 MODERATE, 50-69 ELEVATED, <50 HIGH. Floor rule: "
    "Tier 1 + mission-critical + sensitive data + cross-border + multi-regulatory -> HIGH "
    "regardless of arithmetic. No mid-stream escalations; verdict at Stage 7 only. "
    "Reconcile contradictions before scoring."
)


# --- DIRECTIVE PARSING (research / STAGE_COMPLETE / HANDOFF) ------
@dataclass
class ParsedDirectives:
    body: str
    research: list[dict] = field(default_factory=list)
    stage_complete: Optional[str] = None
    handoff: Optional[dict] = None
    dossier_update: dict = field(default_factory=dict)


def parse_directives(text: str) -> ParsedDirectives:
    out = ParsedDirectives(body=text or "")

    for m in re.finditer(r"```research\s*([\s\S]*?)```", out.body):
        try:
            obj = json.loads(m.group(1).strip())
            if obj.get("query"):
                out.research.append(obj)
        except Exception as _e:
            _obs_swallow('agents.py', _e)
    out.body = re.sub(r"```research\s*[\s\S]*?```", "", out.body).strip()

    # ```dossier { ... }``` blocks record durable captured facts into the dossier
    for m in re.finditer(r"```dossier\s*([\s\S]*?)```", out.body):
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj, dict):
                out.dossier_update.update(obj)
        except Exception as _e:
            _obs_swallow('agents.py', _e)
    out.body = re.sub(r"```dossier\s*[\s\S]*?```", "", out.body).strip()

    sc = re.search(r"^STAGE_COMPLETE:\s*(.+)$", out.body, re.MULTILINE)
    if sc:
        out.stage_complete = sc.group(1).strip()
        out.body = re.sub(r"^STAGE_COMPLETE:.*$", "", out.body, flags=re.MULTILINE).strip()

    ho = re.search(r"^HANDOFF:\s*([a-z]+)\s*[—-]\s*(.+)$", out.body, re.MULTILINE)
    if ho and ho.group(1) in AGENTS:
        out.handoff = {"to": ho.group(1), "why": ho.group(2).strip()}
        out.body = re.sub(r"^HANDOFF:.*$", "", out.body, flags=re.MULTILINE).strip()

    return out


# --- ORCHESTRATOR ROUTING -----------------------------------------
def route_next_agent(stage: int) -> str:
    """Lightweight router; an agent's own HANDOFF takes priority elsewhere."""
    return {
        0: "bro", 1: "bro", 2: "scope", 3: "bro",
        4: "bro", 5: "infosec", 6: "bro", 7: "bro",
    }.get(stage, "bro")


# --- SYSTEM PROMPT BUILDER (for the live-LLM path) ----------------
def build_system_prompt(agent_id: str, stage: int, dossier: dict,
                        learnings: list[str], methodology: str = "",
                        briefs=None) -> str:
    src = briefs or AGENT_BRIEFS
    brief = src.get(agent_id) or AGENT_BRIEFS.get(agent_id, AGENT_BRIEFS["bro"])
    st = STAGES[stage] if 0 <= stage < len(STAGES) else STAGES[0]
    colleagues = "; ".join(
        f"{a['name']} ({a['title']})" for k, a in AGENTS.items() if k != agent_id
    )
    learn_block = ""
    if learnings:
        learn_block = "OPERATOR-CALIBRATED LEARNINGS (apply these; they override defaults):\n" + \
            "\n".join(f"L{i+1}. {t}" for i, t in enumerate(learnings))
    dossier_block = json.dumps(dossier, indent=2) if dossier else "(empty — engagement just opened)"
    meth_block = (methodology + "\n\n") if methodology else ""
    return (
        f"You are {AGENTS[agent_id]['name']} — {brief}\n\n"
        f"Your colleagues: {colleagues}.\n\n{meth_block}{METHODOLOGY}\n\n"
        f"CURRENT STAGE: {st.id} — {st.name}\n\n"
        f"DOSSIER SO FAR:\n{dossier_block}\n\n{learn_block}\n\n"
        "RULES: Read the DOSSIER and the conversation transcript first — they are your memory. "
        "NEVER re-ask anything already answered there; acknowledge what is known and ask only for a "
        "genuine gap. One question at a time; lead with the answer; be concise. When you learn a "
        "durable fact (vendor, service, data types, deployment, tier, jurisdictions, contract value), "
        "record it by appending a fenced ```dossier {\"key\": \"value\"}``` block so the team never "
        "re-asks it. When the current stage's information has been captured — or the user asks to "
        "proceed and the essentials are in hand — advance: end with 'STAGE_COMPLETE: <why>'. Do not "
        "loop. Use 'HANDOFF: <agent_id> — <why>' to pass to a colleague. No mid-stream escalation; "
        "the verdict is Stage 7 only. ALWAYS finish your message with a single clear next step on its "
        "own final line, written exactly as '**Ask:** <the one thing you need from the user>' (or "
        "'**Action:** …' when it is something for them to do) — never end a message without telling the "
        "user precisely what to do next. Speak ONLY as "
        f"{AGENTS[agent_id]['name']} in the first person — never write another agent's lines, "
        "quote them, or narrate them speaking, taking over, or handing back. To bring in a "
        "colleague, emit the HANDOFF directive and stop; the system gives them the floor on the "
        "next turn. Sign nothing."
    )


def synthesize_learning(rating: int, agent: Optional[str], issue: str,
                        note: str, stage: int) -> str:
    a = AGENTS[agent]["name"] if agent and agent in AGENTS else "the team"
    stage_name = STAGES[stage].name if 0 <= stage < len(STAGES) else "the engagement"
    base = issue or ("stage felt off" if rating <= 2 else "minor refinement")
    suffix = f' Operator note: "{note}".' if note else ""
    if rating <= 2:
        return f'When at stage "{stage_name}", {a} should be more careful: {base}.{suffix}'
    return f'At stage "{stage_name}", {a} performed well — keep current approach for: {base}.{suffix}'
