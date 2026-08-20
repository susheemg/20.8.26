"""Enterprise foundation tests: secret resolution + prod fail-fast, Postgres
pooling config, OIDC group->role mapping + SSO callback provisioning, SCIM 2.0
user lifecycle, and the production admin-seed guard."""
import os
import sys
sys.path.insert(0, "/home/claude/tprm")

os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app  # noqa: E402
from app.features.admin import secrets as SEC
from app.features.admin import identity as IDP
from app.features.admin import auth as AUTH  # noqa: E402
from app.features.domain.models_db import make_engine  # noqa: E402


def _clean_env(*keys):
    for k in keys:
        os.environ.pop(k, None)
    SEC.clear_cache()


def test_secret_env_resolution():
    os.environ["BRO_TEST_SECRET_X"] = "value-123"
    SEC.clear_cache()
    assert SEC.get_secret("BRO_TEST_SECRET_X") == "value-123"
    _clean_env("BRO_TEST_SECRET_X")


def test_secret_required_failfast_in_prod():
    _clean_env("BRO_MISSING_ONE")
    os.environ["BRO_ENV"] = "production"
    SEC.clear_cache()
    raised = False
    try:
        SEC.get_secret("BRO_MISSING_ONE", required=True)
    except RuntimeError:
        raised = True
    _clean_env("BRO_ENV")
    assert raised


def test_auth_secret_failfast_in_prod():
    _clean_env("BRO_SECRET_KEY")
    os.environ["BRO_ENV"] = "production"
    SEC.clear_cache()
    raised = False
    try:
        AUTH._secret()
    except Exception:
        raised = True
    _clean_env("BRO_ENV")
    assert raised


def test_postgres_engine_has_pool():
    # Engine object should build with a sized pool for Postgres (no connection made).
    eng = make_engine("postgresql://u:p@localhost:5432/db")
    assert eng.url.drivername == "postgresql+psycopg"
    assert eng.pool.size() == 10  # default BRO_DB_POOL_SIZE


def test_oidc_group_role_mapping():
    os.environ["BRO_OIDC_ROLE_MAP"] = '{"TPRM-Admins":"admin","TPRM-Assessors":"vrm"}'
    os.environ["BRO_OIDC_DEFAULT_ROLE"] = "vendor"
    SEC.clear_cache()
    assert IDP.map_groups_to_role(["x", "TPRM-Admins"]) == "admin"
    assert IDP.map_groups_to_role(["nope"]) == "vendor"
    ident = IDP.claims_to_identity({"email": "a@b.com", "name": "A", "groups": ["TPRM-Assessors"]})
    assert ident["role"] == "vrm" and ident["username"] == "a@b.com"
    _clean_env("BRO_OIDC_ROLE_MAP", "BRO_OIDC_DEFAULT_ROLE")


def test_sso_callback_provisions_user():
    os.environ["BRO_SECRET_KEY"] = "k" * 40
    os.environ["BRO_OIDC_ISSUER"] = "https://idp.example.com"
    os.environ["BRO_OIDC_CLIENT_ID"] = "cid"
    os.environ["BRO_OIDC_ROLE_MAP"] = '{"TPRM-Admins":"admin"}'
    SEC.clear_cache()
    IDP.exchange_code = lambda code: {"id_token": "fake"}
    IDP.verify_id_token = lambda t: {"preferred_username": "alice@corp.com",
                                     "email": "alice@corp.com", "name": "Alice",
                                     "groups": ["TPRM-Admins"]}
    c = TestClient(create_app("sqlite:///:memory:"), follow_redirects=False)
    assert c.get("/api/v1/auth/sso-status").json()["oidc_enabled"] is True
    r = c.get("/auth/oidc/callback?code=abc&state=xyz")
    assert r.status_code == 200 and "bro_tok" in r.text
    _clean_env("BRO_OIDC_ISSUER", "BRO_OIDC_CLIENT_ID", "BRO_OIDC_ROLE_MAP", "BRO_SECRET_KEY")


def test_scim_user_lifecycle():
    os.environ["BRO_SCIM_TOKEN"] = "scim-secret-123"
    SEC.clear_cache()
    c = TestClient(create_app("sqlite:///:memory:"))
    H = {"Authorization": "Bearer scim-secret-123"}
    assert c.get("/scim/v2/Users", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = c.post("/scim/v2/Users", headers=H, json={
        "userName": "j.doe", "name": {"formatted": "Jane Doe"},
        "emails": [{"value": "jane@corp.com", "primary": True}],
        "active": True, "roles": [{"value": "vrm"}]})
    assert r.status_code == 201 and r.json()["userName"] == "j.doe"
    uid = r.json()["id"]
    assert len(c.get('/scim/v2/Users?filter=userName eq "j.doe"', headers=H).json()["Resources"]) == 1
    pr = c.patch(f"/scim/v2/Users/{uid}", headers=H,
                 json={"Operations": [{"op": "replace", "path": "active", "value": False}]})
    assert pr.status_code == 200 and pr.json()["active"] is False
    assert c.delete(f"/scim/v2/Users/{uid}", headers=H).status_code == 204
    _clean_env("BRO_SCIM_TOKEN")


def test_admin_seed_guard_in_prod():
    from app.features.domain.models_db import make_session_factory, Base
    from app.features.admin.rbac import seed
    _clean_env("BRO_ADMIN_PASSWORD")
    os.environ["BRO_ENV"] = "production"
    SEC.clear_cache()
    eng = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = make_session_factory(eng)()
    raised = False
    try:
        seed(s)
    except RuntimeError:
        raised = True
    _clean_env("BRO_ENV")
    assert raised


def test_scim_disabled_by_default():
    _clean_env("BRO_SCIM_TOKEN")
    c = TestClient(create_app("sqlite:///:memory:"))
    assert c.get("/scim/v2/Users").status_code == 404


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception:
            print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
