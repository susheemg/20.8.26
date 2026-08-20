"""
Phase 4a: turning untrusted model text into a validated AgentVerdict.

This is the reliability-critical layer. The network call is trivial; parsing
what a model actually emits is where real-world accuracy is won or lost. Models
return JSON wrapped in markdown fences, with preamble ("Here's my assessment:"),
trailing commentary, missing fields, out-of-range numbers, string tiers, and
occasionally truncated/invalid JSON. A naive json.loads() ships a brittle product.

Strategy:
  1. Extract the JSON object from noisy text (strip fences, find the object).
  2. Parse leniently, then VALIDATE strictly against the verdict contract.
  3. On any failure, raise VerdictParseError with a precise reason — the caller
     treats an unparseable verdict as an automatic ESCALATE (never auto-deliver
     something we couldn't even read). Failing safe is the whole point.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from ..models.rating import Tier
from .provider import Provider
from .agent import AgentVerdict


class VerdictParseError(ValueError):
    """Raised when model output cannot be turned into a valid verdict."""


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json_object(text: str) -> str:
    """Pull the first JSON object out of noisy model text."""
    if not text or not text.strip():
        raise VerdictParseError("empty model output")

    # Prefer a fenced block if present.
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text

    # Find the outermost {...} by brace matching (tolerates preamble/trailing text).
    start = candidate.find("{")
    if start == -1:
        raise VerdictParseError("no JSON object found in output")
    depth = 0
    for i in range(start, len(candidate)):
        c = candidate[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return candidate[start:i + 1]
    raise VerdictParseError("unbalanced braces in JSON object")


def _coerce_tier(value: Any) -> Tier:
    """Accept 1..4, '1'..'4', or 'TIER_2' / 'tier 2' forms."""
    if isinstance(value, bool):
        raise VerdictParseError("tier must not be a boolean")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        iv = int(value)
    elif isinstance(value, str):
        digits = re.search(r"[1-4]", value)
        if not digits:
            raise VerdictParseError(f"tier string has no valid digit: {value!r}")
        iv = int(digits.group())
    else:
        raise VerdictParseError(f"tier has unsupported type: {type(value).__name__}")
    if iv not in (1, 2, 3, 4):
        raise VerdictParseError(f"tier out of range 1..4: {iv}")
    return Tier(iv)


def _coerce_unit(value: Any, name: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise VerdictParseError(f"{name} not a number: {value!r}")
    if not 0.0 <= f <= 1.0:
        raise VerdictParseError(f"{name} out of range 0..1: {f}")
    return f


def _coerce_severity(value: Any) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise VerdictParseError(f"severity not an integer: {value!r}")
    if not 1 <= iv <= 5:
        raise VerdictParseError(f"severity out of range 1..5: {iv}")
    return iv


def parse_verdict(
    raw_text: str,
    *,
    control_id: str,
    domain: str,
    provider: Provider,
    winning_evidence_id: Optional[str],
    considered_evidence_ids: tuple[str, ...],
    conflict_present: bool,
    effective_control_origin: str,
    baseline_version: Optional[int],
) -> AgentVerdict:
    """
    Parse + validate model output into an AgentVerdict. Provenance fields are
    supplied by the orchestrator (NOT trusted to the model) — the model only
    provides judgement (tier, confidence, severity, rationale); the system
    owns the chain of custody. This prevents a model from fabricating which
    evidence it relied on.
    """
    obj_text = _extract_json_object(raw_text)
    try:
        data = json.loads(obj_text)
    except json.JSONDecodeError as e:
        raise VerdictParseError(f"invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise VerdictParseError("top-level JSON is not an object")

    for required in ("tier", "confidence", "severity"):
        if required not in data:
            raise VerdictParseError(f"missing required field: {required}")

    return AgentVerdict(
        control_id=control_id,
        domain=domain,
        tier=_coerce_tier(data["tier"]),
        confidence=_coerce_unit(data["confidence"], "confidence"),
        severity=_coerce_severity(data["severity"]),
        rationale=str(data.get("rationale", "")).strip(),
        provider=provider,
        winning_evidence_id=winning_evidence_id,
        considered_evidence_ids=considered_evidence_ids,
        conflict_present=conflict_present,
        effective_control_origin=effective_control_origin,
        baseline_version=baseline_version,
    )
