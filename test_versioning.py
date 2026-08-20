"""Version-control framework: VERSION ⇄ app ⇄ CHANGELOG must agree."""
import os
import re
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app  # noqa: E402

BASE = "/home/claude/tprm"
DB = "sqlite:////tmp/ver.db"


def _version():
    return open(f"{BASE}/VERSION").read().strip()


def test_version_file_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _version())


def test_app_reports_version():
    if os.path.exists("/tmp/ver.db"):
        os.remove("/tmp/ver.db")
    c = TestClient(create_app(DB))
    assert c.get("/healthz").json()["version"] == _version()
    assert c.app.version == _version()


def test_changelog_has_current_version_and_release_assets():
    log = open(f"{BASE}/CHANGELOG.md").read()
    assert f"[{_version()}]" in log
    assert os.path.exists(f"{BASE}/RELEASING.md")
    assert os.access(f"{BASE}/release.sh", os.X_OK)


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
