"""OpenTelemetry tracing with GenAI semantic conventions (AI-06).

The architecture assessment found no distributed tracing anywhere: a production
failure could not be reproduced, and a challenged assessment could not be replayed
step by step. That is an evidential gap for a platform whose central claim is
defensibility.

Design decisions worth stating:

* **Vendor-neutral.** Instrumented with OpenTelemetry using the GenAI semantic
  conventions rather than a vendor SDK, so the observability backend can change
  without touching application code.
* **Optional dependency.** If `opentelemetry` is not installed the module degrades to
  no-op spans that still carry attributes into the correlation log. Tracing must never
  be the reason the platform fails to boot in an air-gapped deployment.
* **Redaction at capture.** Prompt and response *content* never enters a span. The AI
  ledger's metadata-only discipline is extended here rather than abandoned, because a
  trace store that holds supplier confidential text is a second data-protection
  exposure wherever it is exported.
"""
from __future__ import annotations

import contextlib
import contextvars
import time
import uuid
from typing import Any, Optional

# ── correlation id: one identifier from HTTP edge to provider call and back ────
_correlation: contextvars.ContextVar = contextvars.ContextVar("brata_correlation_id",
                                                              default=None)

# Attributes that must never be recorded, whatever a caller passes.
_FORBIDDEN = {"prompt", "system_prompt", "user_content", "response", "completion",
              "text", "content", "document", "password", "api_key", "token"}


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def set_correlation_id(cid: Optional[str]) -> str:
    cid = cid or new_correlation_id()
    _correlation.set(cid)
    return cid


def correlation_id() -> Optional[str]:
    return _correlation.get()


# ── tracer resolution ─────────────────────────────────────────────────────────
_TRACER = None
_ENABLED = False


def _tracer():
    global _TRACER, _ENABLED
    if _TRACER is not None:
        return _TRACER
    try:
        from opentelemetry import trace  # type: ignore
        _TRACER = trace.get_tracer("brata.tprm")
        _ENABLED = True
    except Exception:
        _TRACER = False        # sentinel: tried and unavailable
        _ENABLED = False
    return _TRACER


def enabled() -> bool:
    _tracer()
    return _ENABLED


class _NoopSpan:
    """Carries attributes so the shape of instrumentation is identical either way."""

    __slots__ = ("name", "attrs", "_t0")

    def __init__(self, name: str):
        self.name = name
        self.attrs: dict = {}
        self._t0 = time.time()

    def set_attribute(self, k: str, v: Any) -> None:
        self.attrs[k] = v

    def record_exception(self, exc: BaseException) -> None:
        self.attrs["error.type"] = type(exc).__name__

    def set_status(self, *_a, **_k) -> None:
        pass

    @property
    def duration_ms(self) -> int:
        return int((time.time() - self._t0) * 1000)


def _clean(attrs: dict) -> dict:
    out = {}
    for k, v in (attrs or {}).items():
        leaf = k.rsplit(".", 1)[-1].lower()
        if leaf in _FORBIDDEN:
            continue                      # content never enters a span
        if v is None:
            continue
        out[k] = v if isinstance(v, (str, int, float, bool)) else str(v)[:200]
    return out


@contextlib.contextmanager
def span(name: str, **attributes):
    """Start a span. Works identically with or without OpenTelemetry installed."""
    attrs = _clean(attributes)
    cid = correlation_id()
    if cid:
        attrs["brata.correlation_id"] = cid
    t = _tracer()
    if t:
        with t.start_as_current_span(name) as s:      # type: ignore[union-attr]
            for k, v in attrs.items():
                s.set_attribute(k, v)
            try:
                yield s
            except Exception as e:
                s.record_exception(e)
                raise
    else:
        s = _NoopSpan(name)
        s.attrs.update(attrs)
        try:
            yield s
        except Exception as e:
            s.record_exception(e)
            raise


# ── GenAI convention helpers ──────────────────────────────────────────────────
def llm_span(*, provider: str, model: str, domain: str, web_search: bool = False,
             prompt_version: str = "", max_tokens: int = 0):
    """A span for one model call, using GenAI semantic convention attribute names."""
    return span("gen_ai.chat",
                **{"gen_ai.system": provider,
                   "gen_ai.request.model": model,
                   "gen_ai.request.max_tokens": max_tokens,
                   "brata.domain": domain,
                   "brata.web_search": web_search,
                   "brata.prompt_version": prompt_version})


def record_llm_usage(s, *, input_tokens=0, output_tokens=0, cache_read=0,
                     cache_write=0, finish_reason="") -> None:
    for k, v in (("gen_ai.usage.input_tokens", input_tokens),
                 ("gen_ai.usage.output_tokens", output_tokens),
                 ("brata.cache.read_tokens", cache_read),
                 ("brata.cache.write_tokens", cache_write),
                 ("gen_ai.response.finish_reason", finish_reason)):
        if v:
            try:
                s.set_attribute(k, v)
            except Exception:
                pass


def tool_span(*, tool: str, run_id: str = "", idempotency_key: str = ""):
    return span("brata.tool", **{"brata.tool.name": tool, "brata.run_id": run_id,
                                 "brata.idempotency_key": idempotency_key})


def run_span(*, run_id: str, agent: str, tenant: str = "", actor: str = "",
             goal_kind: str = ""):
    """Goal *kind*, never the goal text — the goal can contain supplier confidential
    detail and belongs in the audit trail, not in a trace store."""
    return span("brata.agent.run", **{"brata.run_id": run_id, "brata.agent": agent,
                                      "brata.tenant": tenant, "brata.actor": actor,
                                      "brata.goal_kind": goal_kind})
