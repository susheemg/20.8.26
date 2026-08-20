"""Screening wired into risk (auto-Issue + criticality escalation, re-screen closes)
and the OFAC / UN / EU issuer loaders."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app, make_session_factory, make_engine  # noqa: E402
from app.features.domain.registry_models import VendorRecord, IssueRecord  # noqa: E402

H = {"x-user": "admin"}
DB = "sqlite:////tmp/sanc_risk_test.db"
FX = "/home/claude/tprm/tests/fixtures"


def _app(*vendors):
    p = "/tmp/sanc_risk_test.db"
    if os.path.exists(p):
        os.remove(p)
    app = create_app(DB)
    s = make_session_factory(make_engine(DB))()
    for vid, name, country in vendors:
        s.add(VendorRecord(vendor_id=vid, legal_name=name, hq_country=country))
    s.commit()
    return TestClient(app), s


def test_hit_creates_issue_and_escalates_criticality():
    c, s = _app(("VEN-H", "Volkov Industrial", "RU"))
    r = c.post("/api/v2/sanctions/screen", headers=H, json={"vendor_id": "VEN-H"}).json()
    assert r["band"] == "Hit"
    assert r["risk"]["kind"] == "sanctions_hit" and r["risk"]["escalated"] is True
    s.expire_all()
    v = s.query(VendorRecord).filter_by(vendor_id="VEN-H").first()
    assert v.is_critical and "Sanctions" in (v.criticality_reason or "")
    assert s.query(IssueRecord).filter_by(vendor_id="VEN-H", status="Open").count() == 1


def test_clean_rescreen_closes_issue():
    c, s = _app(("VEN-H2", "Volkov Industrial", "RU"))
    c.post("/api/v2/sanctions/screen", headers=H, json={"vendor_id": "VEN-H2"})
    r2 = c.post("/api/v2/sanctions/screen", headers=H,
                json={"vendor_id": "VEN-H2", "name": "Acme Cloud Services"}).json()
    assert r2["band"] == "Clear" and r2["risk"]["issue"] is None
    s.expire_all()
    assert s.query(IssueRecord).filter_by(vendor_id="VEN-H2", status="Open").count() == 0


def test_review_creates_review_issue_without_escalation():
    c, s = _app(("VEN-R", "Adaeze Okonkwo", "NG"))
    r = c.post("/api/v2/sanctions/screen", headers=H, json={"vendor_id": "VEN-R"}).json()
    assert r["band"] == "Review"
    assert r["risk"]["kind"] == "sanctions_review" and r["risk"]["escalated"] is False
    s.expire_all()
    v = s.query(VendorRecord).filter_by(vendor_id="VEN-R").first()
    assert not v.is_critical   # Review (possible) must not auto-escalate criticality


def test_ofac_un_eu_loaders_and_live_screen():
    c, s = _app()
    for src, fx, key in [("OFAC", "ofac_sample.csv", "csv"),
                         ("UN", "un_sample.xml", "xml"), ("EU", "eu_sample.xml", "xml")]:
        lo = c.post("/api/v2/sanctions/load-feed", headers=H,
                    json={"source": src, key: open(f"{FX}/{fx}").read()}).json()
        assert lo["loaded"] >= 2 and lo["source"] == src
    feeds = {f["source"] for f in c.get("/api/v2/sanctions/feeds", headers=H).json()["feeds"]}
    assert {"OFAC (live)", "UN (live)", "EU (live)"} <= feeds
    r = c.post("/api/v2/sanctions/screen", headers=H, json={"name": "Al Rashid Trust"}).json()
    assert r["band"] == "Hit" and "UN (live)" in r["live_sources"]


def test_screen_vendor_owner_hit_raises_issue():
    c, s = _app(("VEN-OW", "Clean Corp Ltd", "GB"))
    c.post("/api/v2/vendors/VEN-OW/people", headers=H,
           json={"name": "Konstantin Petrov", "role": "UBO", "dob": "1968-03-12",
                 "nationality": "RU", "is_ubo": True})
    res = c.post("/api/v2/sanctions/screen-vendor/VEN-OW", headers=H).json()
    assert res["overall_band"] in ("Hit", "Review")
    assert res["risk"]["issue"] and res["risk"]["issue"].startswith("ISS")
    s.expire_all()
    assert s.query(IssueRecord).filter_by(vendor_id="VEN-OW", status="Open").count() == 1


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
