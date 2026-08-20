"""
Phase 3c: post-cutover random sampling — the safeguard teams drop and regret.

Once a domain graduates, the escalation engine routes only flagged cases to
humans. The danger: a confident wrong answer the AI did NOT flag is auto-
delivered and never seen again. Calibration can drift (model update, policy
change, shifting vendor population) and you'd never know.

So even after cutover, a random fraction of AUTO-DELIVERED outputs is pulled
for human review — NOT the escalated ones, the ones the system thought were
safe. These samples feed back as fresh Observations. If the sampled silent-miss
rate creeps above the graduation bar, the domain is automatically pulled BACK
into shadow mode (auto-demotion). Trust is continuously re-earned, never assumed.

Sampling is deterministic given a seed so audits are reproducible.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .analysis import CalibrationReport, GraduationCriteria


def should_sample(finding_id: str, sample_rate: float, seed: str = "tprm") -> bool:
    """Deterministic per-finding sampling: hash(finding_id+seed) -> [0,1).
    Reproducible — the same finding is always sampled or not for a given seed,
    so an auditor can verify the sample set was not cherry-picked."""
    if not 0.0 <= sample_rate <= 1.0:
        raise ValueError("sample_rate must be in [0,1]")
    if sample_rate == 0.0:
        return False
    h = hashlib.sha256(f"{seed}:{finding_id}".encode()).hexdigest()
    bucket = int(h[:8], 16) / 0xFFFFFFFF
    return bucket < sample_rate


@dataclass(frozen=True)
class DriftCheck:
    domain: str
    provider: str
    sampled_n: int
    sampled_silent_miss_rate: float
    within_tolerance: bool
    recommend_demote: bool


def check_drift(
    sampled: CalibrationReport,
    criteria: GraduationCriteria = GraduationCriteria(),
    min_samples_to_act: int = 50,
) -> DriftCheck:
    """Decide whether sampled auto-delivered outputs show the domain has
    drifted out of its graduation criteria. Won't demote on thin data."""
    enough = sampled.n >= min_samples_to_act
    breached = sampled.silent_miss_rate > criteria.max_silent_miss_rate
    within = not breached
    return DriftCheck(
        domain=sampled.domain,
        provider=sampled.provider,
        sampled_n=sampled.n,
        sampled_silent_miss_rate=sampled.silent_miss_rate,
        within_tolerance=within,
        recommend_demote=bool(enough and breached),
    )
