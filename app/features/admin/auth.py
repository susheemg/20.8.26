"""
Real authentication for the deployed app.

Replaces the insecure x-user header (which let any caller claim any identity)
with signed JWT bearer tokens:
  - POST /login verifies username + password, returns a signed token.
  - Protected routes require Authorization: Bearer <token>; the token is
    verified (signature + expiry) and the subject resolved to a real user.

The signing secret comes from BRO_SECRET_KEY. In production this MUST be set to
a strong random value; if unset we generate an ephemeral one and log a warning
(tokens won't survive a restart, which is a safe failure for a forgotten secret).
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Optional

import jwt

_ALGO = "HS256"
_TTL_SECONDS = 8 * 3600  # 8-hour working session


def _secret() -> str:
    from app.features.admin.secrets import get_secret, is_production
    s = get_secret("BRO_SECRET_KEY", required=True)
    if s:
        return s
    # Non-production only: ephemeral fallback, resets on restart.
    if is_production():
        # get_secret(required=True) already raises in prod; defensive guard.
        raise RuntimeError("BRO_SECRET_KEY must be set in production.")
    if not hasattr(_secret, "_ephemeral"):
        _secret._ephemeral = secrets.token_hex(32)  # type: ignore[attr-defined]
        print("WARNING: BRO_SECRET_KEY not set — using an ephemeral signing key "
              "(dev only). Set BRO_SECRET_KEY so tokens survive restarts.")
    return _secret._ephemeral  # type: ignore[attr-defined]


def issue_token(username: str, role_key: str) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "role": role_key,
        "iat": now,
        "exp": now + _TTL_SECONDS,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


class TokenError(Exception):
    pass


def verify_token(token: str) -> dict:
    """Return the decoded claims, or raise TokenError on any problem."""
    try:
        return jwt.decode(token, _secret(), algorithms=[_ALGO])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("token expired") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("invalid token") from e


def bearer_subject(authorization: Optional[str]) -> str:
    """Extract and verify the subject from an Authorization header value.
    Raises TokenError if missing/malformed/invalid."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise TokenError("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    claims = verify_token(token)
    sub = claims.get("sub")
    if not sub:
        raise TokenError("token has no subject")
    return sub
