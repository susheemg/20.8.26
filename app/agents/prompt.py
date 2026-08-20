"""
Phase 4b: prompt construction.

Renders the effective control + resolved evidence into a strict prompt that asks
the model for JSON-only output. Tenant terminology (from the overlay) is applied
so the model speaks the enterprise's language. The prompt makes the contract
explicit and demands JSON with no prose, which maximises parse success — but the
parser still assumes the model will misbehave.
"""
from __future__ import annotations

from typing import Optional

from ..models.evidence import ResolvedEvidence
from ..models.policy import EffectiveControl

_SYSTEM = (
    "You are a third-party risk assessor. Assess the supplier against the single "
    "control provided, using only the evidence given. Apply the evidence precedence "
    "already resolved for you. Respond with a SINGLE JSON object and nothing else "
    "(no markdown, no preamble). Schema: "
    '{"tier": <int 1-4, 1=most critical>, "confidence": <float 0-1>, '
    '"severity": <int 1-5>, "rationale": "<one paragraph>"}.'
)


def _apply_terminology(text: str, terminology: dict[str, str]) -> str:
    for src, dst in terminology.items():
        text = text.replace(src, dst)
    return text


def build_prompt(
    control: EffectiveControl,
    resolved: Optional[ResolvedEvidence],
) -> tuple[str, str]:
    """Return (system_prompt, user_content)."""
    term = control.terminology or {}

    lines = [
        f"CONTROL {control.control_id} [{control.domain}]",
        f"Requirement: {_apply_terminology(control.statement, term)}",
        f"Threshold: {control.threshold}",
        f"Applicability (min data classification): {int(control.applicability)}",
        f"Risk weight: {int(control.risk_weight)} (1-5)",
        "",
        "EVIDENCE (precedence already resolved):",
    ]
    if resolved is None:
        lines.append("  (no evidence supplied — assess as unverified)")
    else:
        w = resolved.winner
        lines.append(
            f"  Governing source [{w.source_type.name}] captured {w.captured_on}: "
            f"{w.claim}"
        )
        if resolved.staleness_flag:
            lines.append("  NOTE: governing source is past its freshness window.")
        if resolved.conflicts:
            lines.append(
                f"  NOTE: {len(resolved.conflicts)} lower-precedence source(s) "
                "contradict the governing source."
            )
    user_content = _apply_terminology("\n".join(lines), term)
    return _SYSTEM, user_content
