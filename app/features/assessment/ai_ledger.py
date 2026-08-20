"""
AI call ledger + budget caps (Pass 2 governance).

Privacy-first by design: the ledger stores ONLY metadata (provider, model, domain,
timing, sizes, success/error) — never prompt or response content — so no PII can
leak into it. Error strings are redacted as defence-in-depth.
"""
from __future__ import annotations

import re
import time
from typing import Optional


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line."""
    try:
        from app.features.admin.security import log_json as _lj
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass

from sqlalchemy import text as _sql

_REDACT = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "<number>"),
    (re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b", re.I), "<nino>"),
    (re.compile(r"\+?\d[\d ()-]{8,}\d"), "<phone>"),
]


def redact(text: str) -> str:
    out = text or ""
    for rx, repl in _REDACT:
        out = rx.sub(repl, out)
    return out


def ensure_table(s) -> None:
    s.execute(_sql(
        "CREATE TABLE IF NOT EXISTS ai_call_log ("
        "id INTEGER PRIMARY KEY, ts TEXT, provider TEXT, model TEXT, domain TEXT, "
        "web_search INTEGER, duration_ms INTEGER, prompt_chars INTEGER, "
        "response_chars INTEGER, input_tokens INTEGER DEFAULT 0, "
        "output_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0, "
        "cache_write_tokens INTEGER DEFAULT 0, success INTEGER, error TEXT)"))
    # AI-03: self-heal older tables so cache effectiveness starts being recorded
    # without waiting for a migration window.
    for _c in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
        try:
            s.execute(_sql(f"ALTER TABLE ai_call_log ADD COLUMN {_c} INTEGER DEFAULT 0"))
        except Exception:
            pass
    s.commit()


def safe_record(session_factory, payload: dict) -> None:
    """Best-effort insert from the llm_config telemetry hook. Never raises."""
    try:
        with session_factory() as s:
            ensure_table(s)
            s.execute(_sql(
                "INSERT INTO ai_call_log (ts, provider, model, domain, web_search, "
                "duration_ms, prompt_chars, response_chars, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, success, error) "
                "VALUES (:ts,:p,:m,:d,:w,:dur,:pc,:rc,:it,:ot,:cr,:cw,:ok,:err)"),
                {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "p": payload.get("provider"), "m": payload.get("model"),
                 "d": payload.get("domain"), "w": 1 if payload.get("web_search") else 0,
                 "dur": payload.get("duration_ms"), "pc": payload.get("prompt_chars"),
                 "rc": payload.get("response_chars"),
                             "it": payload.get("input_tokens", 0),
                             "ot": payload.get("output_tokens", 0),
                             "cr": payload.get("cache_read_tokens", 0),
                             "cw": payload.get("cache_write_tokens", 0),
                 "ok": 1 if payload.get("success") else 0,
                 "err": redact(str(payload.get("error") or ""))[:400] or None})
            s.commit()
    except Exception as _e:
        # SQLite only: the insert can hit 'database is locked' when the calling
        # request's own session still holds the write transaction (the telemetry
        # hook fires mid-request, so busy_timeout cannot win against its own
        # caller). Retry once on a background thread after the request has had
        # time to commit — the lock is gone and the row lands.
        if "locked" in str(_e).lower():
            import threading as _th

            def _deferred():
                for _wait in (1.5, 4.0, 8.0):
                    time.sleep(_wait)
                    try:
                        with session_factory() as s2:
                            ensure_table(s2)
                            s2.execute(_sql(
                                "INSERT INTO ai_call_log (ts, provider, model, domain, web_search, "
                                "duration_ms, prompt_chars, response_chars, input_tokens, "
                                "output_tokens, cache_read_tokens, cache_write_tokens, "
                                "success, error) "
                                "VALUES (:ts,:p,:m,:d,:w,:dur,:pc,:rc,:it,:ot,:cr,:cw,:ok,:err)"),
                                {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "p": payload.get("provider"), "m": payload.get("model"),
                                 "d": payload.get("domain"), "w": 1 if payload.get("web_search") else 0,
                                 "dur": payload.get("duration_ms"), "pc": payload.get("prompt_chars"),
                                 "rc": payload.get("response_chars"),
                             "it": payload.get("input_tokens", 0),
                             "ot": payload.get("output_tokens", 0),
                             "cr": payload.get("cache_read_tokens", 0),
                             "cw": payload.get("cache_write_tokens", 0),
                                 "ok": 1 if payload.get("success") else 0,
                                 "err": redact(str(payload.get("error") or ""))[:400] or None})
                            s2.commit()
                        return
                    except Exception as _e2:
                        if "locked" not in str(_e2).lower():
                            _obs_swallow('ai_ledger.record.retry', _e2); return
                _obs_swallow('ai_ledger.record.retry', RuntimeError("still locked after backoff"))

            _th.Thread(target=_deferred, daemon=True).start()
        else:
            _obs_swallow('ai_ledger.record', _e)


def today_count(s) -> int:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    ensure_table(s)
    return int(s.execute(_sql(
        "SELECT COUNT(*) FROM ai_call_log WHERE ts LIKE :d"), {"d": day + "%"}).scalar() or 0)


def recent(s, n: int = 25) -> list:
    ensure_table(s)
    rows = s.execute(_sql(
        "SELECT ts, provider, model, domain, web_search, duration_ms, prompt_chars, "
        "response_chars, success, error FROM ai_call_log ORDER BY id DESC LIMIT :n"),
        {"n": n}).fetchall()
    keys = ["ts", "provider", "model", "domain", "web_search", "duration_ms",
            "prompt_chars", "response_chars", "success", "error"]
    return [dict(zip(keys, r)) for r in rows]


def get_budget(s) -> Optional[int]:
    from app.features.domain import config_store as CFG
    b = CFG.get_json(s, "ai_budget", {}) or {}
    v = b.get("daily_calls")
    return int(v) if v is not None else None


def set_budget(s, daily_calls: Optional[int]) -> None:
    from app.features.domain import config_store as CFG
    CFG.upsert_json(s, "ai_budget",
                    {"daily_calls": int(daily_calls)} if daily_calls is not None else {},
                    updated_by="admin", category="ai")
    s.commit()


def budget_check(session_factory):
    """Telemetry hook: (allowed, reason)."""
    try:
        with session_factory() as s:
            cap = get_budget(s)
            if cap is None:
                return True, ""
            used = today_count(s)
            if used >= cap:
                return False, f"daily cap {cap} reached ({used} calls today)"
            return True, ""
    except Exception:
        return True, ""
