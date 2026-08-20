"""
Enterprise identity: OIDC single sign-on + SCIM 2.0 provisioning.

SSO (OIDC / OAuth2 authorization-code):
  Works with Okta, Microsoft Entra ID, Ping, Auth0, Google Workspace, etc.
  Configure via env / secret store:
    BRO_OIDC_ISSUER         e.g. https://login.microsoftonline.com/<tenant>/v2.0
    BRO_OIDC_CLIENT_ID
    BRO_OIDC_CLIENT_SECRET  (secret)
    BRO_OIDC_REDIRECT_URI   https://app.example.com/auth/oidc/callback
    BRO_OIDC_SCOPES         default "openid email profile groups"
    BRO_OIDC_GROUPS_CLAIM   default "groups"
    BRO_OIDC_ROLE_MAP       JSON, IdP group -> Brata role key,
                            e.g. {"TPRM-Admins":"admin","TPRM-Assessors":"assessor"}
    BRO_OIDC_DEFAULT_ROLE   role for users with no mapped group (default "viewer")

SCIM 2.0 (RFC 7643/7644) lets the IdP push user lifecycle (create/activate/
deactivate). Protected by a bearer token the IdP is configured with:
    BRO_SCIM_TOKEN          (secret)

This module holds pure, testable helpers; the HTTP routes live in bro_app where
the DB session, token issuance and audit log are available.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import httpx
import jwt

from app.features.admin.secrets import get_secret

_disc_cache: dict = {}


# ------------------------- OIDC (provider-aware) -------------------------
#
# Brata supports three SSO providers side by side, each independently
# configured and independently enabled:
#
#   enterprise  Okta / Entra ID / Ping / Auth0 / Google Workspace (SAML-OIDC).
#               Uses the original un-prefixed BRO_OIDC_* variables so existing
#               deployments keep working unchanged.
#   google      Google Sign-In (accounts.google.com). Standard code flow.
#   apple       Sign in with Apple (appleid.apple.com). Client secret is a
#               short-lived ES256 JWT generated from an Apple private key.
#
# Per-provider variables (PROV = GOOGLE | APPLE, enterprise = un-prefixed):
#   BRO_OIDC_<PROV>_CLIENT_ID
#   BRO_OIDC_<PROV>_CLIENT_SECRET      (apple: optional; auto-generated if key set)
#   BRO_OIDC_<PROV>_REDIRECT_URI       (falls back to BRO_OIDC_REDIRECT_URI)
#   BRO_OIDC_<PROV>_SCOPES
# Apple key material (only if you don't pre-mint the client secret):
#   BRO_OIDC_APPLE_TEAM_ID, BRO_OIDC_APPLE_KEY_ID, BRO_OIDC_APPLE_PRIVATE_KEY
# Role mapping is shared: BRO_OIDC_ROLE_MAP / BRO_OIDC_GROUPS_CLAIM /
# BRO_OIDC_DEFAULT_ROLE apply to whichever provider signs the user in.

PROVIDERS = ("enterprise", "google", "apple")

_FIXED_ISSUER = {
    "google": "https://accounts.google.com",
    "apple": "https://appleid.apple.com",
}
_DEFAULT_SCOPES = {
    "enterprise": "openid email profile groups",
    "google": "openid email profile",
    "apple": "openid email name",
}


def _pfx(provider: str) -> str:
    """Secret-name prefix for a provider ('' for the legacy enterprise slot)."""
    return "" if provider == "enterprise" else provider.upper() + "_"


def _sec(provider: str, key: str, default: Optional[str] = None) -> Optional[str]:
    return get_secret(f"BRO_OIDC_{_pfx(provider)}{key}", default=default)


def _issuer(provider: str) -> Optional[str]:
    return _FIXED_ISSUER.get(provider) or _sec(provider, "ISSUER")


def oidc_enabled(provider: str = "enterprise") -> bool:
    """True when this provider has the minimum config to start a sign-in."""
    return bool(_issuer(provider) and _sec(provider, "CLIENT_ID"))


def enabled_providers() -> list[str]:
    return [p for p in PROVIDERS if oidc_enabled(p)]


def any_oidc_enabled() -> bool:
    return bool(enabled_providers())


def _apple_client_secret() -> str:
    """Apple's client_secret is an ES256 JWT signed with your Apple key.

    Prefer a pre-minted secret (BRO_OIDC_APPLE_CLIENT_SECRET); otherwise mint
    one on the fly from BRO_OIDC_APPLE_{TEAM_ID,KEY_ID,PRIVATE_KEY}. Raises a
    clear error if neither is present, so the button fails loud, not silent.
    """
    pre = _sec("apple", "CLIENT_SECRET")
    if pre:
        return pre
    team = get_secret("BRO_OIDC_APPLE_TEAM_ID")
    kid = get_secret("BRO_OIDC_APPLE_KEY_ID")
    pem = get_secret("BRO_OIDC_APPLE_PRIVATE_KEY")
    cid = _sec("apple", "CLIENT_ID")
    if not (team and kid and pem and cid):
        raise RuntimeError(
            "Apple SSO needs BRO_OIDC_APPLE_CLIENT_SECRET, or the trio "
            "BRO_OIDC_APPLE_TEAM_ID / _KEY_ID / _PRIVATE_KEY plus _CLIENT_ID")
    now = int(time.time())
    return jwt.encode(
        {"iss": team, "iat": now, "exp": now + 3600,
         "aud": "https://appleid.apple.com", "sub": cid},
        pem, algorithm="ES256", headers={"kid": kid})


def _client_secret(provider: str) -> Optional[str]:
    if provider == "apple":
        return _apple_client_secret()
    return _sec(provider, "CLIENT_SECRET")


def _cfg(provider: str = "enterprise") -> dict:
    return {
        "provider": provider,
        "issuer": _issuer(provider),
        "client_id": _sec(provider, "CLIENT_ID"),
        "redirect_uri": (_sec(provider, "REDIRECT_URI")
                         or get_secret("BRO_OIDC_REDIRECT_URI")),
        "scopes": _sec(provider, "SCOPES", default=_DEFAULT_SCOPES[provider]),
        "groups_claim": get_secret("BRO_OIDC_GROUPS_CLAIM", default="groups"),
        "default_role": get_secret("BRO_OIDC_DEFAULT_ROLE", default="vendor"),
    }


def discover(provider: str = "enterprise") -> dict:
    """Fetch and cache a provider's OIDC discovery document."""
    issuer = _issuer(provider)
    if not issuer:
        raise RuntimeError(f"OIDC provider '{provider}' not configured")
    if issuer in _disc_cache:
        return _disc_cache[issuer]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    doc = httpx.get(url, timeout=10).raise_for_status().json()
    _disc_cache[issuer] = doc
    return doc


def auth_url(state: str, provider: str = "enterprise") -> str:
    c = _cfg(provider)
    d = discover(provider)
    from urllib.parse import urlencode
    params = {
        "client_id": c["client_id"], "response_type": "code",
        "scope": c["scopes"], "redirect_uri": c["redirect_uri"], "state": state,
    }
    # Apple returns via POST when name/email scopes are requested.
    if provider == "apple":
        params["response_mode"] = "form_post"
    return f"{d['authorization_endpoint']}?{urlencode(params)}"


def exchange_code(code: str, provider: str = "enterprise") -> dict:
    c = _cfg(provider)
    d = discover(provider)
    resp = httpx.post(d["token_endpoint"], timeout=15, data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": c["redirect_uri"],
        "client_id": c["client_id"], "client_secret": _client_secret(provider),
    })
    resp.raise_for_status()
    return resp.json()


def verify_id_token(id_token: str, provider: str = "enterprise") -> dict:
    """Verify signature (via the provider JWKS), audience and issuer."""
    c = _cfg(provider)
    d = discover(provider)
    signing_key = jwt.PyJWKClient(d["jwks_uri"]).get_signing_key_from_jwt(id_token)
    return jwt.decode(id_token, signing_key.key,
                      algorithms=d.get("id_token_signing_alg_values_supported", ["RS256"]),
                      audience=c["client_id"], issuer=d["issuer"])


def claims_to_identity(claims: dict, provider: str = "enterprise") -> dict:
    """Pull a normalised identity (username/email/name/groups/role) from claims."""
    c = _cfg(provider)
    groups = claims.get(c["groups_claim"]) or []
    if isinstance(groups, str):
        groups = [groups]
    return {
        "username": claims.get("preferred_username") or claims.get("email") or claims.get("sub"),
        "email": claims.get("email"),
        "full_name": claims.get("name") or claims.get("preferred_username") or claims.get("email"),
        "groups": groups,
        "role": map_groups_to_role(groups),
    }


def map_groups_to_role(groups: list[str]) -> str:
    raw = get_secret("BRO_OIDC_ROLE_MAP", default="{}")
    try:
        mapping = json.loads(raw)
    except ValueError:
        mapping = {}
    for g in groups:
        if g in mapping:
            return mapping[g]
    return get_secret("BRO_OIDC_DEFAULT_ROLE", default="vendor")


def new_state(provider: str = "enterprise") -> str:
    """Signed, short-lived state token that also carries the provider."""
    return jwt.encode(
        {"n": os.urandom(8).hex(), "p": provider, "iat": int(time.time())},
        get_secret("BRO_SECRET_KEY", default="dev"), algorithm="HS256")


def read_state(state: str) -> dict:
    """Validate the state token and return its payload (raises on tamper)."""
    return jwt.decode(state, get_secret("BRO_SECRET_KEY", default="dev"),
                      algorithms=["HS256"])


# ------------------------- SCIM 2.0 -------------------------
def scim_enabled() -> bool:
    return bool(get_secret("BRO_SCIM_TOKEN"))


def scim_token_ok(authorization: Optional[str]) -> bool:
    tok = get_secret("BRO_SCIM_TOKEN")
    if not tok or not authorization:
        return False
    parts = authorization.split(" ", 1)
    return len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip() == tok


def user_to_scim(u, base_url: str = "") -> dict:
    """Render a Brata User as a SCIM 2.0 User resource."""
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": str(u.id),
        "userName": u.username,
        "name": {"formatted": u.full_name or u.username},
        "displayName": u.full_name or u.username,
        "emails": ([{"value": u.email, "primary": True}] if getattr(u, "email", None) else []),
        "active": bool(u.is_active),
        "roles": ([{"value": u.role.key}] if getattr(u, "role", None) else []),
        "meta": {"resourceType": "User", "location": f"{base_url}/scim/v2/Users/{u.id}"},
    }


def scim_extract(body: dict) -> dict:
    """Pull the fields we persist from an inbound SCIM User payload."""
    emails = body.get("emails") or []
    email = None
    if emails:
        email = next((e.get("value") for e in emails if e.get("primary")), emails[0].get("value"))
    name = body.get("name") or {}
    roles = body.get("roles") or []
    return {
        "username": body.get("userName"),
        "email": email,
        "full_name": name.get("formatted") or body.get("displayName") or body.get("userName"),
        "active": body.get("active", True),
        "role_hint": (roles[0].get("value") if roles else None),
    }


def scim_list_response(resources: list[dict]) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": len(resources),
        "startIndex": 1,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def scim_error(status: int, detail: str) -> dict:
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "status": str(status), "detail": detail}
