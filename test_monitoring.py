"""Scheduled monitoring engine: run-all orchestration, outcome application,
run log, status/next-due, and the scheduler claim guard."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app, make_session_factory, make_engine  # noqa: E402
from app.features.lifecycle import monitoring as MON  # noqa: E402
from app.features.domain.registry_models import (  # noqa: E402
    VendorRecord, IssueRecord, MonitoringRun,
)

H = {"x-user": "admin"}
DB = "sqlite:////tmp/mon_test.db"


def _app():
    p = "/tmp/mon_test.db"
    if os.path.exists(p):
        os.remove(p)
    app = create_app(DB)
    s = make_session_factory(make_engine(DB))()
    s.add(VendorRecord(vendor_id="VEN-M1", legal_name="Volkov Industrial", hq_country="RU"))
    s.add(VendorRecord(vendor_id="VEN-M2", legal_name="Clean Cloud Ltd", hq_country="GB"))
    s.commit()
    return TestClient(app), s


def test_run_all_executes_all_tasks():
    c, s = _app()
    rep = MON.run_all(s, by="test", trigger="manual")
    assert rep["ok"]
    assert set(rep["tasks"]) == {"sanctions_rescreen", "certificate_revalidation",
                                 "evidence_expiring", "reassessment_due"}
    sr = rep["tasks"]["sanctions_rescreen"]
    assert sr["screened"] == 2 and sr["hits"] == 1 and sr["clear"] == 1


def test_run_applies_outcomes():
    c, s = _app()
    MON.run_all(s, by="test")
    s.expire_all()
    assert s.query(IssueRecord).filter_by(vendor_id="VEN-M1", status="Open").count() == 1
    assert s.query(VendorRecord).filter_by(vendor_id="VEN-M1").first().is_critical


def test_run_is_logged():
    c, s = _app()
    MON.run_all(s, by="test")
    assert s.query(MonitoringRun).count() == 1


def test_status_reports_last_run_and_next_due():
    c, s = _app()
    MON.run_all(s, by="test")
    st = MON.status(s, 24)
    assert st["last_run"] and st["next_due"] and "sanctions_rescreen" in st["tasks"]


def test_claim_due_run_respects_interval():
    c, s = _app()
    MON.run_all(s, by="test")
    assert MON.claim_due_run(s, 24) is False   # just ran
    assert MON.claim_due_run(s, 0) is True      # any elapsed time is due


def test_endpoints_run_status_runs():
    c, s = _app()
    rep = c.post("/api/v2/monitoring/run", headers=H, json={}).json()
    assert rep["ok"] and rep["trigger"] == "manual"
    st = c.get("/api/v2/monitoring/status", headers=H).json()
    assert len(st["tasks_available"]) == 4
    runs = c.get("/api/v2/monitoring/runs", headers=H).json()
    assert len(runs) >= 1 and runs[0]["trigger"] == "manual"


def test_rerun_does_not_duplicate_issue():
    c, s = _app()
    MON.run_all(s, by="test")
    MON.run_all(s, by="test")
    s.expire_all()
    assert s.query(IssueRecord).filter_by(vendor_id="VEN-M1", status="Open").count() == 1


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
