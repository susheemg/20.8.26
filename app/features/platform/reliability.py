"""Runtime reliability primitives (APP-02, APP-03).

Two controls the architecture assessment found missing:

* **Idempotency** — mutating endpoints previously accepted no idempotency key, so a
  retried creation minted a second supplier, engagement or assessment. Agent clients
  and mobile clients retry aggressively; the register is the system of record, and
  duplicate records in it reach the regulator's evidence pack.

* **Circuit breakers** — retries existed but nothing stopped them retrying into a
  wall. During a provider outage the monitoring sweep retries once per supplier,
  which converts a dependency failure into a platform-wide stall.

Both are deliberately small and dependency-free: they use the application's own
database and process memory rather than introducing Redis for two features.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Callable, Optional

from sqlalchemy import text as _sql

# ─────────────────────────────────────────────────────────── idempotency

_IDEM_TTL_SECONDS = 24 * 3600


def _ensure_idem_table(s) -> None:
    s.execute(_sql(
        "CREATE TABLE IF NOT EXISTS idempotency_keys ("
        "key TEXT NOT NULL, actor TEXT NOT NULL, route TEXT NOT NULL, "
        "request_hash TEXT NOT NULL, response_json TEXT, status TEXT NOT NULL, "
        "created_at REAL NOT NULL, PRIMARY KEY (key, actor, route))"))
    s.commit()


def _hash_request(body: Any) -> str:
    try:
        blob = json.dumps(body, sort_keys=True, default=str)
    except Exception:
        blob = str(body)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class IdempotencyConflict(Exception):
    """Same key, different request body — the client has reused a key incorrectly."""


def idempotent(s, *, key: Optional[str], actor: str, route: str, body: Any,
               produce: Callable[[], Any]) -> Any:
    """Run ``produce`` at most once for a given (key, actor, route).

    Returns the stored response on a repeat call. Scoping the key by actor and route
    prevents one tenant's key from colliding with another's, and prevents a key
    minted for one operation from short-circuiting a different one.

    With no key supplied the behaviour is unchanged — this is additive, so existing
    clients keep working and can adopt the header when they are ready.
    """
    if not key:
        return produce()

    _ensure_idem_table(s)
    rh = _hash_request(body)
    row = s.execute(_sql(
        "SELECT request_hash, response_json, status FROM idempotency_keys "
        "WHERE key=:k AND actor=:a AND route=:r"),
        {"k": key, "a": actor, "r": route}).fetchone()

    if row:
        prior_hash, stored, status = row
        if prior_hash != rh:
            # Reusing a key with a different payload is a client bug, not a retry.
            # Returning the first response would silently discard the second request.
            raise IdempotencyConflict(
                "This idempotency key was already used with a different request body.")
        if status == "in_progress":
            raise IdempotencyConflict(
                "A request with this idempotency key is still in progress.")
        try:
            return json.loads(stored) if stored else None
        except Exception:
            return None

    try:
        s.execute(_sql(
            "INSERT INTO idempotency_keys (key,actor,route,request_hash,status,created_at) "
            "VALUES (:k,:a,:r,:h,'in_progress',:t)"),
            {"k": key, "a": actor, "r": route, "h": rh, "t": time.time()})
        s.commit()
    except Exception:
        # Lost the insert race: another request holds the key. Treat as in-progress.
        raise IdempotencyConflict(
            "A request with this idempotency key is already being processed.")

    try:
        result = produce()
    except Exception:
        try:  # release the key so a corrected retry can proceed
            s.execute(_sql("DELETE FROM idempotency_keys WHERE key=:k AND actor=:a AND route=:r"),
                      {"k": key, "a": actor, "r": route})
            s.commit()
        except Exception:
            pass
        raise

    try:
        s.execute(_sql(
            "UPDATE idempotency_keys SET status='done', response_json=:v "
            "WHERE key=:k AND actor=:a AND route=:r"),
            {"v": json.dumps(result, default=str)[:400000], "k": key, "a": actor, "r": route})
        s.execute(_sql("DELETE FROM idempotency_keys WHERE created_at < :c"),
                  {"c": time.time() - _IDEM_TTL_SECONDS})
        s.commit()
    except Exception:
        pass
    return result


# ─────────────────────────────────────────────────────── circuit breakers

class CircuitOpen(Exception):
    """The dependency is failing; the call was not attempted."""


class _Breaker:
    __slots__ = ("name", "threshold", "cooldown", "fails", "opened_at", "lock", "probe_at")

    def __init__(self, name: str, threshold: int, cooldown: float):
        self.name = name
        self.threshold = threshold
        self.cooldown = cooldown
        self.fails = 0
        self.opened_at = 0.0
        self.probe_at = 0.0      # when the last half-open probe was released
        self.lock = threading.Lock()

    def state(self) -> str:
        with self.lock:
            if not self.opened_at:
                return "closed"
            if time.time() - self.opened_at >= self.cooldown:
                return "half_open"
            return "open"

    def allow(self) -> bool:
        st = self.state()
        if st == "closed":
            return True
        if st == "half_open":
            with self.lock:
                # Exactly one probe at a time — but a probe that never reports back
                # (process died mid-call) must not wedge the breaker shut forever, so
                # the reservation expires after one cooldown period.
                now = time.time()
                if now - self.probe_at >= self.cooldown:
                    self.probe_at = now
                    return True
            return False
        return False

    def record(self, ok: bool) -> None:
        with self.lock:
            if ok:
                self.fails = 0
                self.opened_at = 0.0
                self.probe_at = 0.0
            else:
                self.fails += 1
                self.probe_at = 0.0
                if self.fails >= self.threshold:
                    self.opened_at = time.time()


_BREAKERS: dict = {}
_BREAKERS_LOCK = threading.Lock()


def breaker(name: str, threshold: int = 5, cooldown: float = 60.0) -> _Breaker:
    with _BREAKERS_LOCK:
        b = _BREAKERS.get(name)
        if b is None:
            b = _Breaker(name, threshold, cooldown)
            _BREAKERS[name] = b
        return b


def call_protected(name: str, fn: Callable, *, threshold: int = 5,
                   cooldown: float = 60.0, on_open: Optional[Callable] = None):
    """Invoke ``fn`` behind a named circuit breaker.

    Open circuits fail fast rather than adding load to a dependency that is already
    failing. ``on_open`` supplies the degraded path where one exists; where it does
    not, CircuitOpen propagates — some routes should fail rather than answer worse.
    """
    b = breaker(name, threshold, cooldown)
    if not b.allow():
        if on_open is not None:
            return on_open()
        raise CircuitOpen(f"{name} circuit is open after {b.fails} consecutive failures")
    try:
        out = fn()
    except Exception:
        b.record(False)
        raise
    b.record(True)
    return out


def breaker_states() -> list:
    """Operator view: every breaker and its current state."""
    with _BREAKERS_LOCK:
        items = list(_BREAKERS.values())
    return [{"name": b.name, "state": b.state(), "consecutive_failures": b.fails,
             "threshold": b.threshold, "cooldown_s": b.cooldown} for b in items]
