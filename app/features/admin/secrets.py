"""
Centralised secret resolution for enterprise deployment.

Secrets (signing keys, OAuth client secrets, DB URLs, API keys, SCIM tokens)
must never live in source or be read ad-hoc from os.environ scattered across the
codebase. Everything funnels through get_secret(), which resolves in this order:

  1. Process env var               BRO_SECRET_KEY=...
  2. Docker/K8s secret file        BRO_SECRET_KEY_FILE=/run/secrets/bro_key
  3. AWS Secrets Manager           when BRO_SECRETS_BACKEND=aws
  4. HashiCorp Vault (KV v2)       when BRO_SECRETS_BACKEND=vault

Backends are imported lazily so boto3 / hvac are optional dependencies — the app
runs with env-only resolution out of the box. Resolved values are cached for the
process lifetime.

In production (BRO_ENV=production, or BRO_REQUIRE_SECRETS=1) a missing *required*
secret raises immediately — fail fast rather than booting with an insecure default.
"""
from __future__ import annotations

import os
from typing import Optional

_cache: dict[str, Optional[str]] = {}


def is_production() -> bool:
    return (os.environ.get("BRO_ENV", "").lower() in ("production", "prod")
            or os.environ.get("BRO_REQUIRE_SECRETS") == "1")


def _from_file(name: str) -> Optional[str]:
    path = os.environ.get(f"{name}_FILE")
    if path and os.path.exists(path):
        try:
            return open(path, "r", encoding="utf-8").read().strip()
        except OSError:
            return None
    return None


def _from_aws(name: str) -> Optional[str]:
    if os.environ.get("BRO_SECRETS_BACKEND") != "aws":
        return None
    try:
        import boto3  # lazy, optional
        import json as _json
        prefix = os.environ.get("BRO_AWS_SECRET_PREFIX", "")
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        client = boto3.client("secretsmanager", region_name=region)
        resp = client.get_secret_value(SecretId=f"{prefix}{name}")
        raw = resp.get("SecretString")
        if not raw:
            return None
        # Support either a raw string secret or a JSON blob keyed by name.
        try:
            blob = _json.loads(raw)
            if isinstance(blob, dict):
                return blob.get(name) or blob.get("value") or raw
        except ValueError:
            pass
        return raw
    except Exception as e:  # never let a backend hiccup crash resolution
        print(f"secrets: AWS lookup for {name} failed: {e}")
        return None


def _from_vault(name: str) -> Optional[str]:
    if os.environ.get("BRO_SECRETS_BACKEND") != "vault":
        return None
    try:
        import hvac  # lazy, optional
        client = hvac.Client(url=os.environ.get("BRO_VAULT_ADDR"),
                             token=os.environ.get("BRO_VAULT_TOKEN"))
        mount = os.environ.get("BRO_VAULT_MOUNT", "secret")
        path = os.environ.get("BRO_VAULT_PATH", "bro")
        data = client.secrets.kv.v2.read_secret_version(path=path, mount_point=mount)
        return data["data"]["data"].get(name)
    except Exception as e:
        print(f"secrets: Vault lookup for {name} failed: {e}")
        return None


def get_secret(name: str, default: Optional[str] = None,
               required: bool = False) -> Optional[str]:
    """Resolve a secret by name. Caches the first successful resolution."""
    if name in _cache:
        val = _cache[name]
    else:
        val = (os.environ.get(name)
               or _from_file(name)
               or _from_aws(name)
               or _from_vault(name))
        _cache[name] = val
    if val is None:
        if required and is_production():
            raise RuntimeError(
                f"Required secret {name} is not set. Configure it via env, "
                f"{name}_FILE, AWS Secrets Manager or Vault before starting in production.")
        return default
    return val


def clear_cache() -> None:
    _cache.clear()
