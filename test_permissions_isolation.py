"""v4.15 — menu visibility by permission, row-level isolation, supplier backup
users, unique username (passwords need not be unique)."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    import shutil
    db = tmp_path / "d.db"
    shutil.copy("bro_demo.db", db)
    return TestClient(create_app(f"sqlite:///{db}"))


# ---- A: menu visibility by permission ----
def test_me_returns_nav_denied(client):
    me = client.get("/api/v1/me", headers={"X-User": "demo.buyer"}).json()
    assert "nav_denied" in me and "permissions" in me
    assert "admin" in me["nav_denied"]            # buyer can't see Admin
    assert "supplierusers" in me["nav_denied"]    # buyer can't manage suppliers


def test_admin_sees_all_navs(client):
    me = client.get("/api/v1/me", headers=H).json()
    assert me["nav_denied"] == []


def test_assessor_sees_supplier_users(client):
    me = client.get("/api/v1/me", headers={"X-User": "demo.assessor"}).json()
    assert "supplierusers" not in me["nav_denied"]
    assert "admin" in me["nav_denied"]


# ---- B: row-level isolation ----
def test_buyer_sees_only_owned_vendors(client):
    allv = client.get("/api/v2/vendors?slim=true", headers=H).json()
    buyv = client.get("/api/v2/vendors?slim=true", headers={"X-User": "demo.buyer"}).json()
    assert len(buyv) < len(allv)                  # scoped
    assert len(buyv) >= 1


# ---- C: supplier backup users ----
def test_supplier_user_lifecycle(client):
    vid = client.get("/api/v2/vendors?slim=true", headers=H).json()[0]["vendor_id"]
    r = client.post("/api/v1/supplier-users",
                    json={"username": "t.primary", "email": "tp@v.com",
                          "password": "UniqTest#01", "vendor_id": vid}, headers=H)
    assert r.status_code == 200
    bk = client.post("/api/v1/supplier-users",
                     json={"username": "t.backup", "email": "tb@v.com",
                           "password": "UniqTest#02", "vendor_id": vid, "is_backup": True}, headers=H)
    assert bk.status_code == 200
    # only one backup per vendor
    bk2 = client.post("/api/v1/supplier-users",
                      json={"username": "t.backup2", "email": "tb2@v.com",
                            "password": "UniqTest#03", "vendor_id": vid, "is_backup": True}, headers=H)
    assert bk2.status_code == 409
    uid = r.json()["id"]
    assert client.post(f"/api/v1/supplier-users/{uid}/disable", headers=H).json()["is_active"] is False
    assert client.post(f"/api/v1/supplier-users/{uid}/enable", headers=H).json()["is_active"] is True


def test_supplier_manage_gated(client):
    assert client.get("/api/v1/supplier-users", headers={"X-User": "demo.buyer"}).status_code == 403
    assert client.get("/api/v1/supplier-users", headers={"X-User": "demo.assessor"}).status_code == 200
    assert client.get("/api/v1/supplier-users", headers={"X-User": "demo.controller"}).status_code == 200


# ---- D: unique username / password ----

def test_unique_username(client):
    r = client.post("/api/v1/admin/users",
                    json={"username": "admin", "email": "x@y.com",
                          "password": "WhateverPw#1", "role_key": "buyer"}, headers=H)
    assert r.status_code == 409


# ---- B (extended): full-sweep row-level isolation across record lists ----
def test_all_record_lists_scoped_for_buyer(client):
    hb = {"X-User": "demo.buyer"}
    for path in ("/api/v2/vendors?slim=true", "/api/v2/engagements",
                 "/api/v2/assessments", "/api/v2/findings"):
        allc = len(client.get(path, headers=H).json())
        buyc = len(client.get(path, headers=hb).json())
        assert buyc <= allc                       # never sees more than admin
    # buyer sees at least their owned vendors, strictly fewer than all
    assert len(client.get("/api/v2/vendors?slim=true", headers=hb).json()) < \
           len(client.get("/api/v2/vendors?slim=true", headers=H).json())


def test_buyer_cannot_fetch_foreign_vendor(client):
    hb = {"X-User": "demo.buyer"}
    allowed = {v["vendor_id"] for v in client.get("/api/v2/vendors?slim=true", headers=hb).json()}
    allv = [v["vendor_id"] for v in client.get("/api/v2/vendors?slim=true", headers=H).json()]
    foreign = next(v for v in allv if v not in allowed)
    assert client.get(f"/api/v2/vendors/{foreign}", headers=hb).status_code == 403
    own = sorted(allowed)[0]
    assert client.get(f"/api/v2/vendors/{own}", headers=hb).status_code == 200


def test_admin_unrestricted_after_sweep(client):
    allv = [v["vendor_id"] for v in client.get("/api/v2/vendors?slim=true", headers=H).json()]
    assert client.get(f"/api/v2/vendors/{allv[0]}", headers=H).status_code == 200
