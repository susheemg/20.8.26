"""Tests for inbound email certificate intake pipeline."""
import sys, os, base64, datetime as dt
os.environ["BRO_TRUST_HEADER"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H = {"x-user": "admin"}

def _c():
    return TestClient(create_app("sqlite:///:memory:"))

def _vendor_with_contact(c, email="am@acme.com"):
    v = c.post("/api/v2/vendors", json={"legal_name": "Acme Ltd", "website": "https://acme.com"}, headers=H).json()["vendor_id"]
    c.post("/api/v2/contacts", json={"owner_type": "vendor", "owner_id": v, "name": "AM",
            "email": email, "is_primary": True}, headers=H)
    return v

def test_intake_matches_by_contact_email():
    c = _c(); v = _vendor_with_contact(c, "am@acme.com")
    r = c.post("/api/v2/artefacts/email-intake", json={
        "sender": "am@acme.com", "subject": "ISO 27001 renewal",
        "body_text": "Valid until 2027-01-01"}, headers=H).json()
    assert r["status"] == "filed"
    assert r["vendor_id"] == v
    assert r["artefact_id"].startswith("ART-")

def test_intake_matches_by_domain():
    c = _c(); v = _vendor_with_contact(c, "other@acme.com")
    r = c.post("/api/v2/artefacts/email-intake", json={
        "sender": "newperson@acme.com", "subject": "SOC 2"}, headers=H).json()
    assert r["status"] == "filed" and r["vendor_id"] == v

def test_intake_unmatched_sender_parked():
    c = _c(); _vendor_with_contact(c)
    r = c.post("/api/v2/artefacts/email-intake", json={
        "sender": "stranger@nowhere.com", "subject": "Cert"}, headers=H).json()
    assert r["status"] == "unmatched"

def test_intake_extracts_expiry():
    c = _c(); _vendor_with_contact(c, "am@acme.com")
    r = c.post("/api/v2/artefacts/email-intake", json={
        "sender": "am@acme.com", "subject": "ISO cert",
        "body_text": "This certificate is valid until 2026-12-31."}, headers=H).json()
    assert r["expiry_date"] == "2026-12-31"

def test_intake_supersedes_and_closes_issue():
    c = _c(); v = _vendor_with_contact(c, "am@acme.com")
    old = (dt.date.today() - dt.timedelta(days=45)).isoformat()
    art = c.post("/api/v2/artefacts", json={"vendor_id": v, "name": "ISO 27001",
                 "expiry_date": old}, headers=H).json()
    c.post("/api/v2/artefacts/revalidate", headers=H)  # raises issue
    # refreshed cert arrives by email
    r = c.post("/api/v2/artefacts/email-intake", json={
        "sender": "am@acme.com", "subject": "ISO 27001",
        "body_text": "valid until 2027-06-01"}, headers=H).json()
    assert r["superseded"] == art["artefact_id"]
    issues = c.get("/api/v2/issues?status=Open", headers=H).json()
    assert not any(i["vendor_id"] == v for i in issues)  # auto-closed

def test_intake_decodes_attachment():
    c = _c(); _vendor_with_contact(c, "am@acme.com")
    payload = base64.b64encode(b"SOC 2 Type II report. Valid until 2028-03-15.").decode()
    r = c.post("/api/v2/artefacts/email-intake", json={
        "sender": "am@acme.com", "subject": "SOC 2", "attachment_name": "soc2.txt",
        "attachment_b64": payload}, headers=H).json()
    assert r["status"] == "filed" and r["expiry_date"] == "2028-03-15"

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
