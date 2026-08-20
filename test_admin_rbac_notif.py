"""v4.12 — graded RBAC access matrix, user search + email, notification templates."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


# ---- A: RBAC access matrix ----
def test_matrix_shape(client):
    m = client.get("/api/v1/admin/rbac/matrix", headers=H).json()
    assert m["levels"] == ["denied", "read", "write", "modify"]
    assert len(m["roles"]) >= 5 and len(m["permissions"]) >= 40


def test_set_cell_levels(client):
    for lvl in ("read", "write", "modify"):
        client.put("/api/v1/admin/rbac/cell",
                   json={"role_key": "buyer", "perm_key": "vendor.view", "access": lvl}, headers=H)
        g = client.get("/api/v1/admin/rbac/matrix", headers=H).json()["grants"]
        assert g.get("buyer|vendor.view") == lvl


def test_deny_removes_grant(client):
    client.put("/api/v1/admin/rbac/cell",
               json={"role_key": "buyer", "perm_key": "vendor.view", "access": "denied"}, headers=H)
    g = client.get("/api/v1/admin/rbac/matrix", headers=H).json()["grants"]
    assert "buyer|vendor.view" not in g


def test_admin_role_locked(client):
    r = client.put("/api/v1/admin/rbac/cell",
                   json={"role_key": "admin", "perm_key": "vendor.view", "access": "read"}, headers=H)
    assert r.status_code == 400


def test_proassess_brochat_buyer_usable(client):
    # buyer holds engagement.view (BroChat + ProAssess run) and engagement.create (register)
    from app.features.admin import rbac as R
    from app.features.domain.models_db import Role
    from sqlalchemy import select
    # the buyer role must grant engagement.view and engagement.create
    m = client.get("/api/v1/admin/rbac/matrix", headers=H).json()["grants"]
    assert "buyer|engagement.view" in m and "buyer|engagement.create" in m


# ---- B: users ----
def test_user_search(client):
    r = client.get("/api/v1/admin/users?q=admin", headers=H).json()
    assert any(u["username"] == "admin" for u in r)


def test_email_required_on_create(client):
    r = client.post("/api/v1/admin/users",
                    json={"username": "noeml", "password": "Str0ngPwd12", "role_key": "buyer"}, headers=H)
    assert r.status_code == 400
    ok = client.post("/api/v1/admin/users",
                     json={"username": "haseml", "password": "Str0ngPwd12",
                           "email": "haseml@corp.com", "role_key": "buyer"}, headers=H)
    assert ok.status_code == 200


# ---- C: notification templates ----
def test_templates_seeded(client):
    t = client.get("/api/v1/notifications/templates", headers=H).json()["templates"]
    assert len(t) >= 3


def test_template_crud_and_groups(client):
    g = client.get("/api/v1/notifications/groups", headers=H).json()["groups"]
    assert any("emailable" in x for x in g)
    made = client.post("/api/v1/notifications/templates",
                       json={"name": "T", "subject": "S", "body": "draft",
                             "groups": ["buyer", "vrm"]}, headers=H).json()
    tid = made["id"]
    up = client.put(f"/api/v1/notifications/templates/{tid}",
                    json={"body": "edited saved"}, headers=H).json()
    assert up["body"] == "edited saved" and up["groups"] == ["buyer", "vrm"]
    tr = client.post(f"/api/v1/notifications/templates/{tid}/trigger", headers=H).json()
    assert tr["triggered"] and "recipients" in tr
    client.delete(f"/api/v1/notifications/templates/{tid}", headers=H)


def test_template_permission_gate(client):
    assert client.get("/api/v1/notifications/templates", headers={"X-User": "buyer"}).status_code in (401, 403)
