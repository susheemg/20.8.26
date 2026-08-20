"""
BRO Risk Oracle — local demo launcher.

    python run_demo.py

Starts the API on http://127.0.0.1:8000 with demo settings:
  - in-memory-ish SQLite file (bro_demo.db), seeded with admin/admin
  - dev header trust ON so you can poke endpoints without juggling tokens
  - interactive API docs (Swagger UI) you can click through in a browser

Open http://127.0.0.1:8000/docs and click "Try it out" on any endpoint.
Log in via POST /api/v1/login  {"username":"admin","password":"admin"}.
"""
import os
os.environ.setdefault("BRO_TRUST_HEADER", "1")      # demo convenience
os.environ.setdefault("BRO_DB_URL", "sqlite:///bro_demo.db")
os.environ.setdefault("BRO_SECRET_KEY", "demo-only-not-for-production")

import uvicorn
from app.bro_app import app

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  BRO Risk Oracle — demo running")
    print("  Open:  http://127.0.0.1:8000/docs")
    print("  Login: admin / admin")
    print("="*60 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
