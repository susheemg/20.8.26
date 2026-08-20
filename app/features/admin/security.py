"""
Enterprise security utilities (Pass 1 hardening).

- Envelope encryption for secrets at rest (Fernet, key derived from BRO_SECRET_KEY).
  Fail-open by design: with no BRO_SECRET_KEY the app still works and values are
  stored with a 'plain:' prefix, surfaced as a warning in the admin UI.
- Production mode (BRO_ENV=production): the BRO_TRUST_HEADER dev escape hatch
  fails closed.
- In-memory token-bucket rate limiting + login lockout with exponential backoff
  (correct for single-worker deployments such as Render's default; use Redis for
  multi-worker).
- Upload hardening: extension allowlist + magic-byte sniffing + size cap.
- log_json: minimal structured logging helper.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from typing import Optional

_ENC_PREFIX = "enc:"
_PLAIN_PREFIX = "plain:"


def is_production() -> bool:
    return (os.environ.get("BRO_ENV") or "").lower().strip() in ("production", "prod")


def _secret_key() -> str:
    """Env-first (uncached, so rotation/tests work), then Docker/K8s secret file."""
    v = (os.environ.get("BRO_SECRET_KEY") or "").strip()
    if v:
        return v
    try:
        from app.features.admin.secrets import _from_file
        return (_from_file("BRO_SECRET_KEY") or "").strip()
    except Exception:
        return ""


def secret_key_set() -> bool:
    return bool(_secret_key())


def _fernet():
    from cryptography.fernet import Fernet
    raw = _secret_key().encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt_value(value: str) -> str:
    """Encrypt a secret for storage. Without BRO_SECRET_KEY, store with a plain marker."""
    if value is None:
        return value
    if not secret_key_set():
        return _PLAIN_PREFIX + value
    return _ENC_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_value(stored: str) -> str:
    """Decrypt a stored secret. Tolerates legacy unprefixed plaintext values."""
    if stored is None:
        return stored
    if stored.startswith(_PLAIN_PREFIX):
        return stored[len(_PLAIN_PREFIX):]
    if stored.startswith(_ENC_PREFIX):
        try:
            return _fernet().decrypt(stored[len(_ENC_PREFIX):].encode()).decode()
        except Exception:
            return ""  # wrong/missing key: never return ciphertext as if it were the secret
    return stored  # legacy plaintext


# ---------------- rate limiting & lockout (in-memory, single-worker) ----------------
_BUCKETS: dict = {}
_LOCKOUT: dict = {}  # username -> {"fails": n, "until": ts}

LOGIN_RATE_CAPACITY = 30      # requests
LOGIN_RATE_WINDOW = 60.0      # per seconds (per client IP)
LOCKOUT_THRESHOLD = 6         # consecutive failures
LOCKOUT_BASE_SECONDS = 60     # backoff: 60s * 2^(n-threshold), capped


def check_rate(key: str, capacity: int = LOGIN_RATE_CAPACITY,
               window: float = LOGIN_RATE_WINDOW) -> bool:
    """Token bucket; returns True if the request is allowed."""
    now = time.time()
    tokens, last = _BUCKETS.get(key, (float(capacity), now))
    tokens = min(float(capacity), tokens + (now - last) * (capacity / window))
    if tokens < 1.0:
        _BUCKETS[key] = (tokens, now)
        return False
    _BUCKETS[key] = (tokens - 1.0, now)
    return True


def login_locked(username: str) -> Optional[int]:
    """Seconds remaining if locked, else None."""
    e = _LOCKOUT.get((username or "").lower())
    if not e:
        return None
    rem = int(e.get("until", 0) - time.time())
    return rem if rem > 0 else None


def record_login_failure(username: str) -> None:
    u = (username or "").lower()
    e = _LOCKOUT.setdefault(u, {"fails": 0, "until": 0})
    e["fails"] += 1
    if e["fails"] >= LOCKOUT_THRESHOLD:
        over = e["fails"] - LOCKOUT_THRESHOLD
        e["until"] = time.time() + min(LOCKOUT_BASE_SECONDS * (2 ** over), 900)


def record_login_success(username: str) -> None:
    _LOCKOUT.pop((username or "").lower(), None)


def reset_limits() -> None:  # for tests
    _BUCKETS.clear()
    _LOCKOUT.clear()


# ---------------- password policy ----------------
def password_policy_error(pw: str) -> Optional[str]:
    pw = pw or ""
    if len(pw) < 10:
        return "password must be at least 10 characters"
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        return "password must contain letters and digits"
    return None


# ---------------- upload hardening ----------------
ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx", "pptx", "csv", "txt", "md", "json",
                      "png", "jpg", "jpeg", "zip", "eml", "msg"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_MAGIC = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG"],
    "jpg": [b"\xff\xd8\xff"], "jpeg": [b"\xff\xd8\xff"],
    "zip": [b"PK\x03\x04"], "docx": [b"PK\x03\x04"], "xlsx": [b"PK\x03\x04"],
    "pptx": [b"PK\x03\x04"],
}


def upload_check(filename: str, data: bytes) -> Optional[str]:
    """Return an error string if the upload should be rejected, else None."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext not in ALLOWED_EXTENSIONS:
        return f"file type .{ext or '?'} is not permitted"
    if len(data or b"") > MAX_UPLOAD_BYTES:
        return f"file exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit"
    sigs = _MAGIC.get(ext)
    if sigs and data and not any(data[:8].startswith(sg) for sg in sigs):
        return f"file content does not match its .{ext} extension"
    # NOTE: AV scanning hook — integrate ClamAV here in production deployments.
    return None


# ---------------- structured logging ----------------
def log_json(event: str, **kw) -> None:
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "event": event}
        rec.update(kw)
        print(json.dumps(rec, default=str), file=sys.stdout, flush=True)
    except Exception:
        pass
