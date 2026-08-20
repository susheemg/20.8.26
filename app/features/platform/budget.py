"""Per-run token and cost ceilings (AI-05).

The guide requires five bounds on any agent loop: iteration cap, token budget,
wall-clock timeout, cost ceiling and tool-call quota. Brata already had the iteration
cap (the review loop is bounded), per-call timeouts, and a daily budget check. What it
lacked was a bound on a *single run*: one assessment could regenerate repeatedly and
consume an unexpected amount of budget without anything noticing until the daily cap
tripped, by which point other work was blocked too.

This adds a run-scoped budget that any operation can open, spend against, and close.
It is deliberately simple: a context manager plus an accounting call. No framework, no
new dependency.

    with run_budget("ASM-000123", max_tokens=200_000, max_cost_usd=2.00) as rb:
        ...
        rb.spend(input_tokens=900, output_tokens=300, cache_read=800, model="claude-...")
        if rb.exhausted: ...

Pricing is indicative and configurable. The point of a cost ceiling is not accounting
precision — finance reconciles from the provider invoice — it is stopping a runaway
before it becomes expensive. A ceiling built on approximate prices still stops it.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import Optional

# USD per 1M tokens. Indicative, and overridable per deployment via BRO_PRICE_JSON.
# Cache reads bill at roughly a tenth of base input; cache writes at a premium.
DEFAULT_PRICES = {
    "default":        {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "haiku":          {"in": 0.80, "out": 4.00,  "cache_read": 0.08, "cache_write": 1.00},
    "sonnet":         {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "opus":           {"in": 15.00, "out": 75.00, "cache_read": 1.50, "cache_write": 18.75},
}


def _prices() -> dict:
    raw = os.environ.get("BRO_PRICE_JSON")
    if raw:
        try:
            import json
            merged = dict(DEFAULT_PRICES)
            merged.update(json.loads(raw))
            return merged
        except Exception:
            pass
    return DEFAULT_PRICES


def price_for(model: str) -> dict:
    p = _prices()
    m = (model or "").lower()
    for key in ("opus", "sonnet", "haiku"):
        if key in m:
            return p.get(key, p["default"])
    return p["default"]


def estimate_cost_usd(*, model: str, input_tokens: int = 0, output_tokens: int = 0,
                      cache_read: int = 0, cache_write: int = 0) -> float:
    r = price_for(model)
    return ((input_tokens * r["in"]) + (output_tokens * r["out"])
            + (cache_read * r["cache_read"]) + (cache_write * r["cache_write"])) / 1_000_000


class RunBudget:
    """Token, cost and wall-clock ceiling for one run."""

    def __init__(self, run_id: str, *, max_tokens: int = 0, max_cost_usd: float = 0.0,
                 max_seconds: float = 0.0):
        self.run_id = run_id
        self.max_tokens = max_tokens or int(os.environ.get("BRO_RUN_MAX_TOKENS", "400000"))
        self.max_cost_usd = max_cost_usd or float(os.environ.get("BRO_RUN_MAX_COST_USD", "5.0"))
        self.max_seconds = max_seconds or float(os.environ.get("BRO_RUN_MAX_SECONDS", "1800"))
        self.tokens = 0
        self.cost_usd = 0.0
        self.calls = 0
        self.started = time.time()
        self.stopped_reason: Optional[str] = None
        self._lock = threading.Lock()

    # ---- accounting -------------------------------------------------------
    def spend(self, *, model: str = "", input_tokens: int = 0, output_tokens: int = 0,
              cache_read: int = 0, cache_write: int = 0) -> None:
        c = estimate_cost_usd(model=model, input_tokens=input_tokens,
                              output_tokens=output_tokens, cache_read=cache_read,
                              cache_write=cache_write)
        with self._lock:
            self.calls += 1
            self.tokens += (input_tokens + output_tokens + cache_read + cache_write)
            self.cost_usd += c
            self._check()

    def _check(self) -> None:
        if self.stopped_reason:
            return
        if self.max_tokens and self.tokens >= self.max_tokens:
            self.stopped_reason = (f"token budget exhausted "
                                   f"({self.tokens:,} of {self.max_tokens:,})")
        elif self.max_cost_usd and self.cost_usd >= self.max_cost_usd:
            self.stopped_reason = (f"cost ceiling reached "
                                   f"(${self.cost_usd:.2f} of ${self.max_cost_usd:.2f})")
        elif self.max_seconds and (time.time() - self.started) >= self.max_seconds:
            self.stopped_reason = (f"wall-clock ceiling reached "
                                   f"({int(time.time() - self.started)}s of "
                                   f"{int(self.max_seconds)}s)")

    # ---- interrogation ----------------------------------------------------
    @property
    def exhausted(self) -> bool:
        with self._lock:
            self._check()
            return self.stopped_reason is not None

    def check(self) -> tuple:
        """(ok, reason) — call before an expensive step, not only after."""
        return (not self.exhausted, self.stopped_reason)

    def snapshot(self) -> dict:
        with self._lock:
            return {"run_id": self.run_id, "calls": self.calls, "tokens": self.tokens,
                    "cost_usd": round(self.cost_usd, 4),
                    "elapsed_s": int(time.time() - self.started),
                    "max_tokens": self.max_tokens, "max_cost_usd": self.max_cost_usd,
                    "max_seconds": self.max_seconds,
                    "stopped_reason": self.stopped_reason,
                    "tokens_pct": (round(self.tokens / self.max_tokens * 100, 1)
                                   if self.max_tokens else None),
                    "cost_pct": (round(self.cost_usd / self.max_cost_usd * 100, 1)
                                 if self.max_cost_usd else None)}


# Active budgets, so a nested call can find the run it belongs to without threading
# the object through every signature.
_ACTIVE: dict = {}
_ACTIVE_LOCK = threading.Lock()


@contextlib.contextmanager
def run_budget(run_id: str, **kw):
    rb = RunBudget(run_id, **kw)
    with _ACTIVE_LOCK:
        _ACTIVE[run_id] = rb
    try:
        yield rb
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.pop(run_id, None)


def active(run_id: str) -> Optional[RunBudget]:
    with _ACTIVE_LOCK:
        return _ACTIVE.get(run_id)


def active_runs() -> list:
    with _ACTIVE_LOCK:
        return [rb.snapshot() for rb in _ACTIVE.values()]
