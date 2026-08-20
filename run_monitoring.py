#!/usr/bin/env python3
"""Standalone monitoring runner — invoke from a scheduler (e.g. Render Cron Job):

    python run_monitoring.py

Runs all monitoring sweeps once against BRO_DB_URL and prints a JSON summary.
"""
import json
import os
import sys

from app.bro_app import create_app, make_session_factory, make_engine  # noqa: E402
from app.features import monitoring as MON  # noqa: E402


def main() -> int:
    url = os.environ.get("BRO_DB_URL", "sqlite:///bro_demo.db")
    create_app(url)  # ensure models/metadata are registered
    s = make_session_factory(make_engine(url))()
    report = MON.run_all(s, by="cron", trigger="cron")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
