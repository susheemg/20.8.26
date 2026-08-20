"""Pass 1 — security hardening: secrets at rest, prod fail-closed, headers,
lockout, upload validation, health probes."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"
os.environ.pop("BRO_ENV", None)
os.environ.pop("BRO_SECRET_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app  # noqa: E402
from app.features.admin import security as SEC  # noqa: E402

H = {"x-user": "admin"}
DB = "sqlite:////tmp/secp.db"


def _client():
    SEC.reset_limits()
    if os.path.exists("/tmp/secp.db"):
        os.remove("/tmp/secp.db")
    return TestClient(create_app(DB))


def test_encrypt_roundtrip_with_and_without_key():
    os.environ.pop("BRO_SECRET_KEY", None)
    p = SEC.encrypt_value("nvapi-secret")
    assert p.startswith("plain:") and SEC.decrypt_value(p) == "nvapi-secret"
    os.environ["BRO_SECRET_KEY"] = "a-long-random-deployment-secret"
    e = SEC.encrypt_value("nvapi-secret")
    assert e.startswith("enc:") and "nvapi-secret" not in e
    assert SEC.decrypt_value(e) == "nvapi-secret"
    os.environ["BRO_SECRET_KEY"] = "a-DIFFERENT-key"
    assert SEC.decrypt_value(e) == ""          # wrong key never leaks ciphertext
    assert SEC.decrypt_value("legacy-plain") == "legacy-plain"
    os.environ.pop("BRO_SECRET_KEY", None)


def test_keys_persisted_encrypted_and_restored():
    os.environ["BRO_SECRET_KEY"] = "deploy-secret-123"
    c = _client()
    c.post("/api/v1/ai/keys", headers=H, json={"nvidia": "nvapi-xyz"})
    from sqlalchemy import create_engine, text
    eng = create_engine(DB)
    with eng.connect() as cx:
        raw = cx.execute(text("SELECT value_json FROM system_config WHERE key='ai_provider_keys'")).scalar()
    assert "nvapi-xyz" not in (raw or "")       # ciphertext at rest
    st = c.get("/api/v1/ai/status", headers=H).json()
    assert st["secrets_encrypted"] is True
    # fresh boot restores the decrypted key into env
    os.environ.pop("NVIDIA_API_KEY", None)
    TestClient(create_app(DB))
    assert os.environ.get("NVIDIA_API_KEY") == "nvapi-xyz"
    os.environ.pop("BRO_SECRET_KEY", None)
    os.environ.pop("NVIDIA_API_KEY", None)


def test_production_mode_fails_trust_header_closed():
    c = _client()
    assert c.get("/api/v1/me", headers=H).status_code == 200   # dev: header works
    os.environ["BRO_ENV"] = "production"
    os.environ["BRO_ADMIN_PASSWORD"] = "Str0ngProdPassword!"
    os.environ["BRO_SECRET_KEY"] = "prod-signing-key-long-and-random"  # required in prod
    from app.features.admin import secrets as SS
    SS._cache.clear()
    try:
        c2 = _client()
        assert c2.get("/api/v1/me", headers=H).status_code == 401  # prod: closed
        # real login still works in production
        r = c2.post("/api/v1/login",
                    json={"username": "admin", "password": "Str0ngProdPassword!"})
        assert r.status_code == 200 and r.json()["token"]
    finally:
        os.environ.pop("BRO_ENV", None)
        os.environ.pop("BRO_ADMIN_PASSWORD", None)
        os.environ.pop("BRO_SECRET_KEY", None)
        SS._cache.clear()


def test_security_headers_on_responses():
    c = _client()
    r = c.get("/healthz")
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
    assert "Strict-Transport-Security" not in r.headers  # only in production


def test_login_lockout_after_repeated_failures():
    c = _client()
    for _ in range(SEC.LOCKOUT_THRESHOLD):
        assert c.post("/api/v1/login",
                      json={"username": "admin", "password": "wrong"}).status_code == 401
    r = c.post("/api/v1/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 423 and "locked" in r.json()["detail"]
    SEC.record_login_success("admin")          # unlock for later suites
    assert c.post("/api/v1/login",
                  json={"username": "admin", "password": "admin"}).status_code == 200


def test_upload_validation_blocks_bad_files():
    c = _client()
    r = c.post("/api/v1/documents/upload", headers=H,
               files={"file": ("evil.exe", b"MZ\x90\x00binary", "application/octet-stream")})
    assert r.status_code == 415
    r2 = c.post("/api/v1/documents/upload", headers=H,
                files={"file": ("fake.pdf", b"<html>not a pdf</html>", "application/pdf")})
    assert r2.status_code == 415               # magic-byte mismatch
    r3 = c.post("/api/v1/documents/upload", headers=H,
                files={"file": ("ok.txt", b"evidence: ISO 27001 certificate ref.", "text/plain")})
    assert r3.status_code == 200               # clean allowlisted file accepted


def test_health_probes():
    c = _client()
    assert c.get("/healthz").json()["status"] == "ok"
    assert c.get("/readyz").json()["status"] == "ready"


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
    SEC.reset_limits()
