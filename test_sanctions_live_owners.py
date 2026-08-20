"""DOB/nationality disambiguation, OFSI live-feed ingestion + live screening, and
beneficial-owner / key-person screening."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app, make_session_factory, make_engine  # noqa: E402
from app.features.intelligence import sanctions as SANC  # noqa: E402
from app.features.domain.registry_models import VendorRecord, VendorPerson  # noqa: E402

H = {"x-user": "admin"}
DB = "sqlite:////tmp/sanc_live_test.db"
FIXTURE = "/home/claude/tprm/tests/fixtures/ofsi_sample.csv"


# ---- disambiguation (pure engine) ----
def test_dob_match_boosts_confidence():
    m = SANC.screen_name("Petrov Konstantin", dob="1968-03-12", nationality="RU")
    assert m["hits"] and m["hits"][0]["score"] >= 90


def test_dob_mismatch_demotes_or_clears():
    diff = SANC.screen_name("Petrov Konstantin", dob="1990-01-01", nationality="RU")
    # mismatch must push it below a confirmed match (often clearing it entirely)
    assert diff["band"] == "Clear" or diff["hits"][0]["score"] < 90


def test_nationality_mismatch_demotes():
    same = SANC.screen_name("Petrov Konstantin", dob="1968-03-12", nationality="RU")
    other = SANC.screen_name("Petrov Konstantin", dob="1968-03-12", nationality="GB")
    s0 = same["hits"][0]["score"]
    o0 = other["hits"][0]["score"] if other["hits"] else 0
    assert o0 < s0


# ---- OFSI parser + live feed ----
def test_ofsi_parser_groups_and_aliases():
    entries = SANC.load_ofsi_csv(open(FIXTURE).read())
    assert len(entries) == 2
    ind = [e for e in entries if e["entity_type"] == "individual"][0]
    assert ind["dob"] == "1972-07-19" and ind["nationality"] == "Iraq"
    assert any("RASHEED" in a.upper() for a in ind["aliases"])
    assert all(e["live"] and e["source"] == "OFSI (live)" for e in entries)


def test_ofsi_load_endpoint_then_live_screen():
    c = TestClient(create_app("sqlite:///:memory:"))
    lo = c.post("/api/v2/sanctions/load-ofsi", headers=H,
                json={"csv": open(FIXTURE).read()}).json()
    assert lo["loaded"] == 2 and lo["via"] == "uploaded file"
    feeds = c.get("/api/v2/sanctions/feeds", headers=H).json()
    assert any(f["source"] == "OFSI (live)" and f["count"] == 2 for f in feeds["feeds"])
    r = c.post("/api/v2/sanctions/screen", headers=H,
               json={"name": "Northwind Trading Company"}).json()
    assert r["band"] == "Hit" and "OFSI (live)" in r["live_sources"]


# ---- beneficial owners / key-person screening ----
def _vendor_app():
    p = "/tmp/sanc_live_test.db"
    if os.path.exists(p):
        os.remove(p)
    app = create_app(DB)
    s = make_session_factory(make_engine(DB))()
    s.add(VendorRecord(vendor_id="VEN-O1", legal_name="Clean Corp Ltd", hq_country="GB"))
    s.commit()
    return TestClient(app), s


def test_vendor_people_crud_and_clean_screen():
    c, s = _vendor_app()
    c.post("/api/v2/vendors/VEN-O1/people", headers=H,
           json={"name": "Eleanor Vance", "role": "UBO", "dob": "1970-01-01",
                 "nationality": "GB", "is_ubo": True})
    ppl = c.get("/api/v2/vendors/VEN-O1/people", headers=H).json()
    assert len(ppl) == 1 and ppl[0]["is_ubo"]
    res = c.post("/api/v2/sanctions/screen-vendor/VEN-O1", headers=H).json()
    assert res["overall_band"] == "Clear" and len(res["people"]) == 1


def test_screen_vendor_with_sanctioned_owner():
    c, s = _vendor_app()
    # plant a UBO whose identity matches a watchlist sanctioned individual
    c.post("/api/v2/vendors/VEN-O1/people", headers=H,
           json={"name": "Konstantin Petrov", "role": "UBO", "dob": "1968-03-12",
                 "nationality": "RU", "is_ubo": True})
    res = c.post("/api/v2/sanctions/screen-vendor/VEN-O1", headers=H).json()
    owner = res["people"][0]
    assert owner["result"]["band"] in ("Hit", "Review")
    assert res["overall_band"] in ("Hit", "Review")


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
