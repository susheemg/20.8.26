"""The SPA script must be served with a content-version query so a redeploy never
serves a stale cached app.js (the cause of 'new UI not visible')."""
import os
import re
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app  # noqa: E402


def test_index_serves_versioned_app_js():
    c = TestClient(create_app("sqlite:///:memory:"))
    html = c.get("/").text
    assert re.search(r'/static/app\.js\?v=[a-f0-9]+', html), "app.js must carry a ?v= cache-bust"


def test_app_js_served():
    c = TestClient(create_app("sqlite:///:memory:"))
    r = c.get("/static/app.js")
    assert r.status_code == 200 and "V.admin" in r.text


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
