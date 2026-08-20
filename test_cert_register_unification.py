"""Certifications-register unification: a cert added via the v1 /certifications
register must write through to the canonical artefact pipeline so it is covered by
the revalidation engine, the expiring view, the Issues Log, supersession and
auto-close — closing the gap where the register sat outside that pipeline."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app, make_session_factory, make_engine  # noqa: E402
from app.features.domain.models_db import Vendor  # noqa: E402
from app.features.domain.models_feature import Certification  # noqa: E402
from app.features.domain.registry_models import VendorRecord, ArtefactRecord, IssueRecord  # noqa: E402

DB = "sqlite:////tmp/cert_unify_test.db"
H = {"x-user": "admin"}


def _fresh():
    p = "/tmp/cert_unify_test.db"
    if os.path.exists(p):
        os.remove(p)
    app = create_app(DB)
    s = make_session_factory(make_engine(DB))()
    vr = VendorRecord(vendor_id="VEN-CT1", legal_name="Contoso Cloud Ltd")
    s.add(vr)
    v1 = Vendor(name="Contoso Cloud Ltd")
    s.add(v1)
    s.commit()
    return TestClient(app), s, v1.id


def test_register_writes_through_to_artefact():
    c, s, vid = _fresh()
    past = (date.today() - timedelta(days=45)).isoformat()
    r = c.post("/api/v1/certifications", headers=H,
               json={"vendor_id": vid, "name": "ISO 27001", "valid_until": past})
    assert r.status_code == 200
    aid = r.json()["artefact_id"]
    assert aid
    art = s.query(ArtefactRecord).filter_by(artefact_id=aid).first()
    assert art is not None and art.vendor_id == "VEN-CT1"


def test_register_cert_surfaces_in_expiring():
    c, s, vid = _fresh()
    past = (date.today() - timedelta(days=10)).isoformat()
    c.post("/api/v1/certifications", headers=H,
           json={"vendor_id": vid, "name": "SOC 2", "valid_until": past})
    exp = c.get("/api/v1/evidence/expiring", headers=H).json()
    assert any(e.get("source") == "certification" and e["name"] == "SOC 2" for e in exp)


def test_register_cert_revalidation_creates_issue():
    c, s, vid = _fresh()
    past = (date.today() - timedelta(days=45)).isoformat()
    c.post("/api/v1/certifications", headers=H,
           json={"vendor_id": vid, "name": "PCI DSS", "valid_until": past})
    c.post("/api/v2/artefacts/revalidate", headers=H)
    s.expire_all()
    n = s.query(IssueRecord).filter(IssueRecord.vendor_id == "VEN-CT1",
                                    IssueRecord.status == "Open",
                                    IssueRecord.detail.like("%PCI DSS%")).count()
    assert n == 1


def test_register_refresh_supersedes_and_closes():
    c, s, vid = _fresh()
    past = (date.today() - timedelta(days=45)).isoformat()
    c.post("/api/v1/certifications", headers=H,
           json={"vendor_id": vid, "name": "ISO 27017", "valid_until": past})
    c.post("/api/v2/artefacts/revalidate", headers=H)
    fut = (date.today() + timedelta(days=300)).isoformat()
    c.post("/api/v1/certifications", headers=H,
           json={"vendor_id": vid, "name": "ISO 27017", "valid_until": fut})
    s.expire_all()
    open_issues = s.query(IssueRecord).filter(IssueRecord.vendor_id == "VEN-CT1",
                                              IssueRecord.status == "Open",
                                              IssueRecord.detail.like("%ISO 27017%")).count()
    superseded = s.query(Certification).filter_by(name="ISO 27017", superseded=True).count()
    assert open_issues == 0 and superseded == 1


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
