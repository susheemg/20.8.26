"""
Tests for the gap-closing batch: CRUD/edit, admin, VRM sign-off, auth
self-service, reporting/export, email, notifications, reassessment, gap review.
"""
import sys, os
os.environ["BRO_TRUST_HEADER"] = "1"
sys.path.insert(0, "/home/claude/tprm")

from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"x-user": "admin"}


def _c():
    return TestClient(create_app("sqlite:///:memory:"))


def _vendor(c, **kw):
    body = {"name": "Acme", "tier": "Tier 1"}; body.update(kw)
    return c.post("/api/v1/vendors", json=body, headers=H).json()["vendor_id"]


def _eng(c, vid):
    return c.post("/api/v1/engagements", json={"vendor_id": vid, "title": "T"}, headers=H).json()["engagement_id"]


# ---- vendor CRUD ----
def test_vendor_edit_and_contact_change():
    c = _c(); vid = _vendor(c)
    r = c.patch(f"/api/v1/vendors/{vid}", json={"name": "Acme Renamed",
                "contact_email": "new@acme.com", "industry": "Fintech"}, headers=H)
    assert r.status_code == 200
    v = c.get(f"/api/v1/vendors/{vid}", headers=H).json()
    assert v["name"] == "Acme Renamed" and v["contact_email"] == "new@acme.com"

def test_vendor_detail_and_archive():
    c = _c(); vid = _vendor(c)
    assert c.get(f"/api/v1/vendors/{vid}", headers=H).status_code == 200
    assert c.delete(f"/api/v1/vendors/{vid}", headers=H).json()["archived"] is True
    # archived vendor drops out of search
    found = c.get("/api/v1/vendors-search", headers=H).json()
    assert not any(x["vendor_id"] == vid for x in found)

def test_vendor_search_filter():
    c = _c(); _vendor(c, name="Alpha", tier="Tier 1"); _vendor(c, name="Beta", tier="Tier 3")
    assert len(c.get("/api/v1/vendors-search?q=alph", headers=H).json()) == 1
    assert len(c.get("/api/v1/vendors-search?tier=Tier 3", headers=H).json()) == 1

def test_remove_critical():
    c = _c(); vid = _vendor(c)
    c.post(f"/api/v1/vendors/{vid}/critical", json={"reason": "x"}, headers=H)
    r = c.delete(f"/api/v1/vendors/{vid}/critical", headers=H)
    assert r.json()["is_critical"] is False


# ---- engagement CRUD ----
def test_engagement_edit_list_cancel():
    c = _c(); vid = _vendor(c); eid = _eng(c, vid)
    c.patch(f"/api/v1/engagements/{eid}", json={"title": "Renamed"}, headers=H)
    lst = c.get("/api/v1/engagements", headers=H).json()
    assert any(e["engagement_id"] == eid and e["title"] == "Renamed" for e in lst)
    assert c.delete(f"/api/v1/engagements/{eid}", headers=H).json()["cancelled"] is True

def test_engagement_list_filter_by_stage():
    c = _c(); vid = _vendor(c); _eng(c, vid)
    rows = c.get("/api/v1/engagements?stage=sourcing", headers=H).json()
    assert all(e["stage"] == "sourcing" for e in rows)


# ---- finding CRUD ----
def test_finding_edit_and_reopen():
    c = _c()
    fid = c.post("/api/v1/findings", json={"title": "Gap", "severity": "high"}, headers=H).json()["finding_id"]
    c.patch(f"/api/v1/findings/{fid}", json={"severity": "critical"}, headers=H)
    # advance to closed then reopen
    for _ in range(5):
        c.post(f"/api/v1/findings/{fid}/advance", headers=H)
    r = c.post(f"/api/v1/findings/{fid}/reopen", headers=H)
    assert r.json()["status"] == "open"


# ---- VRM sign-off + review queue ----
def test_signoff_and_review_queue():
    c = _c(); vid = _vendor(c); eid = _eng(c, vid)
    c.post(f"/api/v1/engagements/{eid}/irq",
           json={"answers": {"Q1": "No", "Q2": "Mission-critical", "Q3": ["Payment Card"],
                             "Q5": "Yes", "Q4": ">1,000,000"}}, headers=H)
    c.post(f"/api/v1/engagements/{eid}/ddq", json={"answers": {"IS2": "MARGINAL"}}, headers=H)
    q = c.get("/api/v1/review-queue", headers=H).json()
    assert any(e["engagement_id"] == eid for e in q)   # HIGH residual in queue
    r = c.post(f"/api/v1/engagements/{eid}/signoff",
               json={"decision": "approved", "note": "ok"}, headers=H)
    assert r.json()["status"] == "signed_off"


# ---- auth self-service ----
def test_change_password_and_profile():
    c = _c()
    assert c.get("/api/v1/me", headers=H).json()["username"] == "admin"
    c.patch("/api/v1/me", json={"full_name": "Boss"}, headers=H)
    assert c.get("/api/v1/me", headers=H).json()["full_name"] == "Boss"
    bad = c.post("/api/v1/me/password", json={"current_password": "wrong", "new_password": "newpass1"}, headers=H)
    assert bad.status_code == 403
    ok = c.post("/api/v1/me/password", json={"current_password": "admin", "new_password": "newpass1"}, headers=H)
    assert ok.json()["changed"] is True


# ---- admin: users + roles ----
def test_admin_user_crud():
    c = _c()
    uid = c.post("/api/v1/admin/users",
                 json={"username": "jane", "password": "pw123456", "role_key": "buyer",
                       "full_name": "Jane B"}, headers=H).json()["id"]
    assert any(x["username"] == "jane" for x in c.get("/api/v1/admin/users", headers=H).json())
    c.patch(f"/api/v1/admin/users/{uid}", json={"role_key": "vrm"}, headers=H)
    assert c.delete(f"/api/v1/admin/users/{uid}", headers=H).json()["is_active"] is False

def test_admin_role_permissions_edit():
    c = _c()
    roles = c.get("/api/v1/admin/roles", headers=H).json()
    assert len(roles) == 6
    perms = c.get("/api/v1/admin/permissions", headers=H).json()
    assert len(perms) >= 40
    r = c.put("/api/v1/admin/roles/buyer/permissions",
              json={"permission_keys": ["vendor.view", "engagement.view"]}, headers=H)
    assert set(r.json()["permissions"]) == {"vendor.view", "engagement.view"}

def test_admin_webhooks():
    c = _c()
    wid = c.post("/api/v1/admin/webhooks", json={"url": "https://x/hook", "event": "*"}, headers=H).json()["webhook_id"]
    assert any(w["id"] == wid for w in c.get("/api/v1/admin/webhooks", headers=H).json())
    assert c.delete(f"/api/v1/admin/webhooks/{wid}", headers=H).json()["deleted"] is True


# ---- notifications ----
def test_notifications_mark_read():
    c = _c(); vid = _vendor(c); _eng(c, vid)   # generates notifications
    n = c.get("/api/v1/notifications", headers=H).json()
    assert n["unread"] >= 1
    c.post("/api/v1/notifications/read-all", headers=H)
    assert c.get("/api/v1/notifications", headers=H).json()["unread"] == 0


# ---- email (simulation outbox) ----
def test_email_simulation_outbox():
    c = _c()
    r = c.post("/api/v1/email/send",
               json={"to_addr": "v@x.com", "subject": "Hi", "body": "Test"}, headers=H)
    assert r.json()["mode"] == "simulation" and r.json()["sent"] is False
    assert len(c.get("/api/v1/email/outbox", headers=H).json()) == 1


# ---- reporting / export ----
def test_register_and_audit_csv_export():
    c = _c(); vid = _vendor(c); _eng(c, vid)
    reg = c.get("/api/v1/reports/register.csv", headers=H)
    assert reg.status_code == 200 and "vendor_id,name,tier" in reg.text
    aud = c.get("/api/v1/audit/export.csv", headers=H)
    assert aud.status_code == 200 and "seq,action,actor" in aud.text


# ---- reassessment cadence + contract gap review ----
def test_reassessment_run_due():
    c = _c()
    r = c.post("/api/v1/reassessments/run-due", headers=H)
    assert "created" in r.json()

def test_contract_gap_review():
    c = _c(); vid = _vendor(c, tier="Tier 1"); eid = _eng(c, vid)
    cid = c.post(f"/api/v1/engagements/{eid}/contract", headers=H).json()["contract_id"]
    r = c.post(f"/api/v1/contracts/{cid}/gap-review", headers=H)
    assert "gap_count" in r.json()


# ---- vendor portal ----
def test_vendor_portal_status():
    c = _c()
    # admin has all perms incl portal.self via ALL
    r = c.get("/api/v1/portal/my-status", headers=H)
    assert r.status_code == 200 and "portal" in r.json()["message"].lower()


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
