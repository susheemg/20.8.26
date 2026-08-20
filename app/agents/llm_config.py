"""
Central LLM configuration — the ONE place to wire AI providers.

Reads API keys from environment variables, lazily builds the relevant SDK
client, and exposes a single `complete()` the rest of the app calls. If no key
is set, `is_enabled()` is False and every feature falls back to its tested
deterministic-local path — so the app always runs, with or without AI.

ENVIRONMENT VARIABLES (set these to enable AI):
    BRO_LLM_PROVIDER   "claude" (default) or "openai" — which provider to use
    ANTHROPIC_API_KEY  your Claude API key            (for provider=claude)
    OPENAI_API_KEY     your OpenAI / ChatGPT API key  (for provider=openai)
    BRO_LLM_MODEL      optional model override
                       (default claude-sonnet-4-6 / gpt-4o)

Examples:
    export ANTHROPIC_API_KEY=sk-ant-...           # Claude
    export BRO_LLM_PROVIDER=openai
    export OPENAI_API_KEY=sk-...                   # ChatGPT

Nothing here is committed; keys live only in the environment / your secrets store.
"""
from __future__ import annotations

import os
import re as _re
from functools import lru_cache
from typing import Optional

from .provider import LLMRequest, Provider
from .adapters import ClaudeAdapter, OpenAIAdapter


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



def configured_provider() -> Optional[str]:
    """Return the provider to use based on env, or None if no key is set."""
    pref = (os.environ.get("BRO_LLM_PROVIDER") or "").lower().strip()
    if pref in _PROVIDER_KEY_ENV and _key_present(pref):
        return pref
    # no explicit (or unusable) preference: prefer whichever key is present, in order
    for p in all_provider_ids():
        if _key_present(p):
            return p
    return None


def is_enabled() -> bool:
    """True if any provider key is configured. Features check this to decide
    whether to use AI or their deterministic-local fallback."""
    return configured_provider() is not None


def _sdk_installed(provider: Optional[str]) -> bool:
    """Is the provider's client library actually importable in this process?"""
    if not provider:
        return False
    try:
        if provider == "claude":
            import anthropic  # noqa: F401
            return True
        import openai  # noqa: F401  (openai-compatible: openai/grok/manus/nvidia/customs)
        return True
    except Exception:
        return False


def status() -> dict:
    """Human-readable status for an admin/settings screen — never leaks the key."""
    prov = configured_provider()
    sdk = _sdk_installed(prov) if prov else False
    return {
        "enabled": prov is not None,
        "provider": prov,
        "claude_key_present": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("BRO_LLM_KEY")),
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "model": _model_for(prov) if prov else None,
        "prompt_cache": os.environ.get("BRO_LLM_CACHE", "1").lower() not in ("0", "false", "no", "off"),
        "sdk_installed": sdk,
        # live_ready is the truth that matters: a key is set AND the SDK is present
        "live_ready": bool(prov) and sdk,
        "last_error": _LAST_ERROR,
    }


_DEFAULT_MODEL = {"claude": "claude-sonnet-4-6", "openai": "gpt-4o",
                  "grok": "grok-4.3", "manus": "manus-1.5",
                  "nvidia": "meta/llama-3.1-70b-instruct"}
# OpenAI-compatible base URLs for the non-OpenAI providers
_OAI_COMPAT_BASE = {
    "grok": ("XAI_API_BASE", "https://api.x.ai/v1"),
    "manus": ("MANUS_API_BASE", "https://api.manus.im/v1"),
    "nvidia": ("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"),
}
_PROVIDER_KEY_ENV = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                     "grok": "XAI_API_KEY", "manus": "MANUS_API_KEY",
                     "nvidia": "NVIDIA_API_KEY"}
_PROVIDER_LABEL = {"claude": "Claude (Anthropic)", "openai": "ChatGPT (OpenAI)",
                   "grok": "Grok (xAI)", "manus": "Manus",
                   "nvidia": "NVIDIA (NIM / API Catalog)"}
_BUILTIN_ORDER = ["claude", "openai", "grok", "manus", "nvidia"]
_CUSTOM_IDS: set = set()


def _envfloat(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _envint(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _llm_timeout() -> float:
    """Per-call wall-clock timeout (seconds) applied to every provider SDK client.
    A hung provider connection can no longer stall the worker indefinitely."""
    return _envfloat("BRO_LLM_TIMEOUT", 30.0)


def _llm_max_retries() -> int:
    """Retries per provider on transient errors (timeout / 429 / 5xx) before
    failing over to the next provider. 0 disables retry."""
    return max(0, _envint("BRO_LLM_RETRIES", 1))


def _llm_failover() -> bool:
    """Whether to fail over to the next key-present provider after a provider
    exhausts its retries. Default on; disable with BRO_LLM_FAILOVER=0."""
    return os.environ.get("BRO_LLM_FAILOVER", "1").lower() not in ("0", "false", "no", "off")


def _is_transient(exc: Exception) -> bool:
    """Heuristic: should this error be retried / failed-over rather than surfaced?
    Matches timeouts, rate limits, and 5xx without importing provider SDKs."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if any(k in name for k in ("timeout", "connection", "ratelimit", "apiconnection",
                               "internalserver", "serviceunavailable", "overloaded")):
        return True
    if any(k in msg for k in ("timed out", "timeout", "rate limit", "429",
                              "500", "502", "503", "504", "overloaded",
                              "temporarily unavailable", "connection reset")):
        return True
    return False


def _slug(x: str) -> str:
    s = _re.sub(r"[^a-z0-9_]+", "_", (x or "").lower().strip()).strip("_")[:40]
    return s or "provider"


def register_provider(pid: str, label: str, base_url: str, model: str,
                      key_env=None, base_env=None, custom: bool = True) -> str:
    """Register an OpenAI-compatible provider (built-in or admin-added custom)."""
    pid = _slug(pid)
    key_env = key_env or f"CUSTOM_{pid.upper()}_API_KEY"
    base_env = base_env or f"CUSTOM_{pid.upper()}_API_BASE"
    _PROVIDER_KEY_ENV[pid] = key_env
    _DEFAULT_MODEL[pid] = model or "gpt-4o"
    _OAI_COMPAT_BASE[pid] = (base_env, base_url)
    _PROVIDER_LABEL[pid] = label or pid
    if custom:
        _CUSTOM_IDS.add(pid)
    try:
        _adapter.cache_clear()
    except Exception as _e:
        _obs_swallow('llm_config.py', _e)
    return pid


def unregister_provider(pid: str) -> None:
    pid = _slug(pid)
    for d in (_PROVIDER_KEY_ENV, _DEFAULT_MODEL, _OAI_COMPAT_BASE, _PROVIDER_LABEL):
        d.pop(pid, None)
    _CUSTOM_IDS.discard(pid)
    try:
        _adapter.cache_clear()
    except Exception as _e:
        _obs_swallow('llm_config.py', _e)


def all_provider_ids() -> list:
    order = [p for p in _BUILTIN_ORDER if p in _PROVIDER_KEY_ENV]
    return order + sorted(_CUSTOM_IDS)


def provider_label(pid: str) -> str:
    return _PROVIDER_LABEL.get(pid, pid)


def _key_present(pid: str) -> bool:
    ke = _PROVIDER_KEY_ENV.get(pid)
    return bool(ke and os.environ.get(ke)) or (pid == "claude" and bool(os.environ.get("BRO_LLM_KEY")))


def provider_info() -> list:
    """Everything the admin UI needs to render every provider generically."""
    active = configured_provider()
    out = []
    for pid in all_provider_ids():
        base = _OAI_COMPAT_BASE.get(pid, (None, None))[1]
        out.append({"id": pid, "label": _PROVIDER_LABEL.get(pid, pid),
                    "key_present": _key_present(pid),
                    "model": _DEFAULT_MODEL.get(pid), "base_url": base,
                    "builtin": pid not in _CUSTOM_IDS, "custom": pid in _CUSTOM_IDS,
                    "active": pid == active})
    return out


def _model_for(provider: str) -> str:
    override = os.environ.get("BRO_LLM_MODEL")
    if override:
        return override
    return _DEFAULT_MODEL.get(provider, "gpt-4o")


@lru_cache(maxsize=8)
def _adapter(provider: str):
    """Build (and cache) the adapter + SDK client for a provider. Imported lazily
    so the app runs without the SDKs installed when AI is disabled.

    grok (xAI) and manus are OpenAI-compatible: same SDK, different base_url + key.
    Manus's *native* API is asynchronous/agentic; point MANUS_API_BASE at an
    OpenAI-compatible chat endpoint to use it as a synchronous inference provider."""
    return _build_adapter(provider, _llm_timeout())


def _adapter_with_timeout(provider: str, timeout_s: Optional[float]):
    """Interactive fast-path: an uncached adapter with a shorter wall-clock timeout,
    so chat and research calls fail fast to a deterministic reply instead of hanging."""
    if not timeout_s:
        return _adapter(provider)
    return _build_adapter(provider, float(timeout_s))


def _build_adapter(provider: str, _timeout: float):
    model = _model_for(provider)
    if provider == "claude":
        import anthropic  # pip install anthropic
        key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("BRO_LLM_KEY")
        client = anthropic.Anthropic(api_key=key, timeout=_timeout, max_retries=0)
        return ClaudeAdapter(client, model=model)
    if provider == "openai":
        import openai  # pip install openai
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"),
                               timeout=_timeout, max_retries=0)
        return OpenAIAdapter(client, model=model)
    if provider in _OAI_COMPAT_BASE:  # grok, manus — OpenAI-compatible
        import openai
        env_base, default_base = _OAI_COMPAT_BASE[provider]
        client = openai.OpenAI(api_key=os.environ.get(_PROVIDER_KEY_ENV[provider]),
                               base_url=os.environ.get(env_base, default_base),
                               timeout=_timeout, max_retries=0)
        return OpenAIAdapter(client, model=model)
    raise ValueError(f"unknown provider: {provider}")


def test_provider(provider: str, prompt: str = "Reply with exactly: OK") -> dict:
    """Probe a single provider's key/endpoint with a tiny live call, independent of
    which provider is currently selected. Never raises — returns a status dict."""
    provider = (provider or "").lower().strip()
    if provider not in _PROVIDER_KEY_ENV:
        return {"ok": False, "provider": provider, "error": "unknown provider"}
    key_env = _PROVIDER_KEY_ENV[provider]
    if not (os.environ.get(key_env) or (provider == "claude" and os.environ.get("BRO_LLM_KEY"))):
        return {"ok": False, "provider": provider, "error": f"no key set ({key_env})"}
    if not _sdk_installed(provider):
        sdk = "anthropic" if provider == "claude" else "openai"
        return {"ok": False, "provider": provider, "error": f"{sdk} SDK not installed"}
    try:
        adapter = _adapter(provider)
        resp = adapter.complete(LLMRequest(
            system_prompt="You are a connectivity probe.", user_content=prompt,
            domain="general", web_search=False, max_tokens=16))
        text = (resp.text or "").strip()
        return {"ok": bool(text), "provider": provider, "model": _model_for(provider),
                "reply": text[:120], "error": None if text else "empty response"}
    except Exception as e:
        return {"ok": False, "provider": provider, "model": _model_for(provider),
                "error": f"{type(e).__name__}: {str(e)[:240]}"}


_LAST_ERROR: Optional[str] = None

# ---- telemetry hooks (AI ledger + budget caps; set by the app at startup) ----
_TELEMETRY = {"record": None, "budget": None}


def set_telemetry(record=None, budget=None) -> None:
    _TELEMETRY["record"] = record
    _TELEMETRY["budget"] = budget


def last_error() -> Optional[str]:
    """The most recent live-call failure reason (for diagnostics/Settings)."""
    return _LAST_ERROR


def _raw_complete(system_prompt: str, user_content: str,
                  domain: str = "general", web_search: bool = False,
                  max_tokens: Optional[int] = None,
                  timeout_s: Optional[float] = None) -> Optional[str]:
    """Low-level single model call with per-call timeout, bounded retry with
    jitter on transient errors, and ordered failover across key-present providers.

    Reliability controls (all env-tunable):
      BRO_LLM_TIMEOUT   per-call wall-clock seconds   (default 30)
      BRO_LLM_RETRIES   retries per provider          (default 2)
      BRO_LLM_FAILOVER  try next provider after retry  (default on)
    """
    global _LAST_ERROR
    # Web-search calls are long-running (multiple server-side search round-trips).
    # Never let one run under a short timeout, even if a caller omits timeout_s
    # (e.g. the review path). This alone prevents the 30s-default timeout on research.
    if web_search:
        timeout_s = max(float(timeout_s or 0), _envfloat("BRO_WEBSEARCH_MIN_TIMEOUT", 90.0))
    primary = configured_provider()
    if primary is None:
        _LAST_ERROR = "no AI provider key configured"
        return None
    if _TELEMETRY.get("budget"):
        try:
            _ok, _reason = _TELEMETRY["budget"]()
            if not _ok:
                _LAST_ERROR = f"AI budget exceeded: {_reason}"
                return None
        except Exception as _e:
            _obs_swallow('llm_config.py', _e)

    import time as _time
    import random as _random

    # Provider try-order: configured first, then the rest (key-present) for failover.
    order = [primary]
    if _llm_failover():
        for p in all_provider_ids():
            if p != primary and _key_present(p):
                order.append(p)

    max_retries = _llm_max_retries()
    last_err = None

    for provider in order:
        if not _sdk_installed(provider):
            last_err = f"{provider} SDK not installed in this environment"
            continue
        for attempt in range(max_retries + 1):
            _t0 = _time.time()

            def _rec(success, text_len=0, error=None, usage=None):
                if _TELEMETRY.get("record"):
                    try:
                        u = usage or {}
                        _TELEMETRY["record"]({
                            "provider": provider, "model": _model_for(provider),
                            "domain": domain, "web_search": bool(web_search),
                            "duration_ms": int((_time.time() - _t0) * 1000),
                            "prompt_chars": len(system_prompt or "") + len(user_content or ""),
                            "response_chars": text_len, "success": bool(success),
                            # AI-03: cache effectiveness is only actionable if it is stored.
                            "input_tokens": u.get("in", 0), "output_tokens": u.get("out", 0),
                            "cache_read_tokens": u.get("cr", 0),
                            "cache_write_tokens": u.get("cw", 0),
                            "error": error})
                    except Exception as _e:
                        _obs_swallow('llm_config.py', _e)

            try:
                # APP-03: fail fast when a provider is already failing, rather than
                # retrying into a wall. The sweep calls this once per supplier, so an
                # unprotected outage stalls the whole portfolio run.
                try:
                    from app.features.platform.reliability import breaker as _brk
                    _b = _brk(f"llm:{provider}", threshold=5, cooldown=60.0)
                    if not _b.allow():
                        _LAST_ERROR = f"{provider} circuit open — provider failing"
                        _rec(False, 0, "circuit_open")
                        break
                except ImportError:
                    _b = None
                adapter = _adapter_with_timeout(provider, timeout_s)
                # AI-06: one span per model call, GenAI conventions, metadata only.
                try:
                    from app.features.platform import telemetry as _TEL
                    _span_cm = _TEL.llm_span(provider=str(provider),
                                             model=_model_for(provider), domain=domain,
                                             web_search=bool(web_search),
                                             max_tokens=max_tokens or 0)
                except Exception:
                    import contextlib as _cl
                    _span_cm, _TEL = _cl.nullcontext(None), None
                with _span_cm as _sp:
                    resp = adapter.complete(LLMRequest(
                        system_prompt=system_prompt, user_content=user_content,
                        domain=domain, web_search=web_search, max_tokens=max_tokens))
                    if _TEL is not None and _sp is not None:
                        _TEL.record_llm_usage(
                            _sp,
                            input_tokens=getattr(resp, "input_tokens", 0) or 0,
                            output_tokens=getattr(resp, "output_tokens", 0) or 0,
                            cache_read=getattr(resp, "cache_read_tokens", 0) or 0,
                            cache_write=getattr(resp, "cache_write_tokens", 0) or 0)
                text = resp.text
                if not (text or "").strip():
                    _LAST_ERROR = "provider returned an empty response"
                    _rec(False, 0, "empty response")
                    last_err = _LAST_ERROR
                    break  # empty is not transient; move to next provider
                _LAST_ERROR = None
                if _b is not None:
                    _b.record(True)          # success closes the circuit
                _rec(True, len(text), usage={
                    "in": getattr(resp, "input_tokens", 0) or 0,
                    "out": getattr(resp, "output_tokens", 0) or 0,
                    "cr": getattr(resp, "cache_read_tokens", 0) or 0,
                    "cw": getattr(resp, "cache_write_tokens", 0) or 0})
                return text
            except Exception as e:
                _LAST_ERROR = f"{type(e).__name__}: {str(e)[:300]}"
                if _b is not None:
                    _b.record(False)         # consecutive failures open the circuit
                _rec(False, 0, _LAST_ERROR)
                last_err = _LAST_ERROR
                if _is_transient(e) and attempt < max_retries:
                    # exponential backoff with full jitter, capped at 8s
                    backoff = min(8.0, (2 ** attempt) * 0.5)
                    _time.sleep(_random.uniform(0, backoff))
                    continue
                break  # non-transient, or retries exhausted -> try next provider

    _LAST_ERROR = last_err or "all providers failed"
    return None


_ANSWER_CONTRACT = (
    "\n\nHOW TO REASON (mandatory, in this order):\n"
    "1. RELEVANCE FIRST — before answering, think through what data could bear on THIS specific question: "
    "internal portfolio data (vendor master; engagement register with inherent/residual bands, stage, criticality, "
    "value; assessments IRQ/DDQ/CLS; findings & remediation; contracts & obligations; performance/SLA scorecards; "
    "financial due diligence; fourth-party & concentration; tamper-evident audit history) AND external signals "
    "(PESTLE threat intelligence; open-source/SBOM vulnerability, KEV & licence exposure; reputation/adverse media; "
    "geopolitical/country exposure). Decide which of these are genuinely material to the question.\n"
    "2. CONSIDER ALL AVAILABLE DATA, THEN FILTER BY RELEVANCE — draw on every relevant data set provided, but use "
    "each only to the extent it bears on the question. If the question is purely internal/operational, do NOT pull in "
    "external signals (PESTLE, OSS, geopolitical, reputation) and do not let them skew the answer; mention their "
    "absence only if it is itself materially notable. Never inflate an answer with data that does not change it.\n"
    "3. ANSWER — be CONTEXTUAL (use the specific entities, figures and IDs provided; never generic) and VERY SPECIFIC "
    "and ACTION-ORIENTED (concrete, prioritised next steps with owner / timeframe where possible). Only where external "
    "factors are genuinely material, weave in a focused, relevant PESTLE reading — targeted to this question, not a "
    "generic sweep.\n"
    "- No filler and no restating of the question."
)
_REVIEWER_SYSTEM = (
    "You are a meticulous expert reviewer of third-party-risk analyst answers. Judge the answer on: RELEVANCE HANDLING "
    "(did it use the data that actually matters, and avoid dragging in or being skewed by external signals — PESTLE, "
    "OSS, geopolitical, reputation — that the question did not need?), contextual specificity, actionability, "
    "correctness, and — only where external factors genuinely apply — focused PESTLE coverage. Penalise both missing "
    "relevant data and irrelevant data that distorts the answer. "
    "Respond with ONLY a JSON object and nothing else: "
    '{"score": <integer 1-10>, "externally_influenced": <true|false>, '
    '"critique": "<one or two sentences naming the single most important improvement>"}'
)


def _parse_review(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    import json, re
    txt = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return {"score": int(d.get("score", 0)),
                "externally_influenced": bool(d.get("externally_influenced", False)),
                "critique": str(d.get("critique", ""))[:600]}
    except Exception:
        return None


def review_enabled() -> bool:
    return os.environ.get("BRO_LLM_REVIEW", "1").lower() not in ("0", "false", "no", "off")


def stream_complete(system_prompt: str, user_content: str,
                    domain: str = "general", max_tokens: Optional[int] = None,
                    timeout_s: Optional[float] = None):
    """Yield the model's answer as text chunks in near-real-time, for interactive
    chat. Single-pass (no review loop) so first tokens arrive fast. Yields nothing
    if AI is not live — the caller then streams its deterministic reply instead.
    Any streaming error mid-flight falls back to a single blocking completion."""
    provider = configured_provider()
    if not (is_enabled() and _sdk_installed(provider)):
        return
    try:
        adapter = _adapter_with_timeout(provider, timeout_s)
        streamer = getattr(adapter, "stream", None)
        if streamer is None:
            text = _raw_complete(system_prompt, user_content, domain, False, max_tokens, timeout_s)
            if text:
                yield text
            return
        got = False
        for delta in streamer(LLMRequest(
                system_prompt=system_prompt, user_content=user_content,
                domain=domain, web_search=False, max_tokens=max_tokens)):
            got = True
            yield delta
        if not got:
            text = _raw_complete(system_prompt, user_content, domain, False, max_tokens, timeout_s)
            if text:
                yield text
    except Exception as e:
        global _LAST_ERROR
        _LAST_ERROR = f"{type(e).__name__}: {str(e)[:200]}"
        try:
            text = _raw_complete(system_prompt, user_content, domain, False, max_tokens, timeout_s)
            if text:
                yield text
        except Exception:
            return


def complete(system_prompt: str, user_content: str,
             domain: str = "general", web_search: bool = False,
             max_tokens: Optional[int] = None,
             review: bool = False, pestle_context: Optional[str] = None,
             external_context: Optional[str] = None,
             feedback_context: Optional[str] = None,
             min_score: int = 8, max_rounds: int = 2,
             timeout_s: Optional[float] = None) -> Optional[str]:
    """Single entry point the features call. Returns the model's text, or None if
    AI is disabled or the call fails.

    When ``review=True`` (and AI is live), the prompt is given a relevance-first
    reasoning contract: the model first weighs which internal and external data sets
    bear on the question, then answers using only the relevant ones (so an internal
    question is not skewed by external PESTLE/OSS signals). Any attached signals
    (``pestle_context``, ``external_context``) are offered as optional context to be
    used strictly per relevance. The answer then goes through the expert-review loop:
    self-graded 1-10 and, if below ``min_score``, regenerated with the critique (up to
    ``max_rounds`` rounds). Structured/JSON callers leave ``review=False`` and are
    unaffected, so deterministic fallbacks and extraction paths never change."""
    if not (review and review_enabled() and is_enabled() and _sdk_installed(configured_provider())):
        return _raw_complete(system_prompt, user_content, domain, web_search, max_tokens, timeout_s)

    sys_full = system_prompt + _ANSWER_CONTRACT
    if feedback_context:
        sys_full += feedback_context[:1600]
    signals = []
    if external_context:
        signals.append(external_context.strip()[:2400])
    if pestle_context:
        signals.append("PESTLE signal (external — live threat surface):\n" + pestle_context[:1800])
    if signals:
        sys_full += (
            "\n\nATTACHED DATA SIGNALS — consider these, then use STRICTLY per relevance. "
            "If a signal is not material to the question, do not use it and do not let it skew the answer:\n"
            + "\n\n".join(signals))

    answer = _raw_complete(sys_full, user_content, domain, web_search, max_tokens, timeout_s)
    if not answer:
        return None
    best_ans, best_score = answer, -1
    for _ in range(max(1, max_rounds)):
        review_user = (f"QUESTION / CONTEXT:\n{user_content[:4000]}\n\n"
                       f"ANSWER TO REVIEW:\n{answer[:6000]}")
        rv = _parse_review(_raw_complete(_REVIEWER_SYSTEM, review_user, domain="review", max_tokens=300))
        score = rv["score"] if rv else min_score  # unparseable review → accept
        if score > best_score:
            best_ans, best_score = answer, score
        if score >= min_score or not rv:
            break
        regen = (f"{user_content}\n\n[A prior answer scored {score}/10. "
                 f"Reviewer critique: {rv['critique']}"
                 + (" External factors are material here — include a focused, relevant PESTLE reading."
                    if rv["externally_influenced"]
                    else " This is an internal question — keep it grounded in the internal data and do "
                         "not add external/PESTLE framing that would skew it.")
                 + " Produce an improved answer that fully satisfies the relevance-first contract.]")
        improved = _raw_complete(sys_full, regen, domain, web_search, max_tokens, timeout_s)
        if not improved:
            break
        answer = improved
    return best_ans
