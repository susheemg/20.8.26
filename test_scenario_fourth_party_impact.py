"""Scenario Simulator — downstream 4th-party impact: vendors that declared a (critical)
vendor as a sub-processor dependency are surfaced as indirect impact."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app, make_session_factory, make_engine  # noqa: E402
from app.features.domain.registry_models import (  # noqa: E402
    VendorRecord, EngagementRecord, FourthPartyRecord, FourthPartyVendor,
)

H = {"x-user": "admin"}
DB = "sqlite:////tmp/s4p.db"


def _app():
    p = "/tmp/s4p.db"
    if os.path.exists(p):
        os.remove(p)
    app = create_app(DB)
    s = make_session_factory(make_engine(DB))()
    # the critical shared sub-processor (registered vendor) + two dependents
    s.add(VendorRecord(vendor_id="VEN-CP", legal_name="CloudCore Ltd", hq_country="GB",
                       is_critical=True, tier="Tier 1"))
    s.add(VendorRecord(vendor_id="VEN-D1", legal_name="Dependent One", tier="Tier 2"))
    s.add(VendorRecord(vendor_id="VEN-D2", legal_name="Dependent Two", tier="Tier 3"))
    s.add(EngagementRecord(engagement_id="ENG-D1", vendor_id="VEN-D1", title="Payments"))
    s.add(FourthPartyRecord(fourth_party_id="F4P-CP", legal_name="CloudCore Ltd",
                            concentration_flag=True))
    s.add(FourthPartyVendor(fourth_party_id="F4P-CP", vendor_id="VEN-D1"))
    s.add(FourthPartyVendor(fourth_party_id="F4P-CP", vendor_id="VEN-D2"))
    s.commit()
    return TestClient(app)


def test_impact_lists_dependents_and_engagements():
    c = _app()
    r = c.get("/api/v2/scenario/fourth-party-impact/VEN-CP", headers=H).json()
    assert r["is_fourth_party"] is True
    assert r["dependent_count"] == 2
    assert r["engagement_count"] == 1
    names = {d["legal_name"] for d in r["dependents"]}
    assert names == {"Dependent One", "Dependent Two"}
    d1 = [d for d in r["dependents"] if d["vendor_id"] == "VEN-D1"][0]
    assert d1["engagements"][0]["title"] == "Payments"


def test_vendor_with_no_dependents_is_empty():
    c = _app()
    r = c.get("/api/v2/scenario/fourth-party-impact/VEN-D2", headers=H).json()
    assert r["dependent_count"] == 0 and r["dependents"] == []


def test_unknown_vendor_404():
    c = _app()
    assert c.get("/api/v2/scenario/fourth-party-impact/VEN-NOPE", headers=H).status_code == 404


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
