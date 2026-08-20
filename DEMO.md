# Run the BRO Risk Oracle demo (2 commands)

Requires Python 3.10+ on your machine.

```bash
pip install -r requirements.txt
python run_demo.py
```

Then open **http://127.0.0.1:8000/docs** in your browser.

## What you get
FastAPI's interactive Swagger UI — every endpoint with a "Try it out"
button, request forms, and live responses. No separate front end needed
to test or demo the full API.

## Suggested click-through (the core story)
1. **POST /api/v1/login** → body `{"username":"admin","password":"admin"}`
   → returns a JWT. (Demo mode also accepts an `x-user: admin` header so you
   can skip token-pasting.)
2. **POST /api/v1/vendors** → `{"name":"Meridian Payments","tier":"Tier 1"}`
3. **POST /api/v1/engagements** → `{"vendor_id":1,"title":"Card processing"}`
4. **POST /api/v1/engagements/1/irq** →
   `{"answers":{"Q1":"No","Q2":"Mission-critical","Q3":["Payment Card"],"Q5":"Yes","Q4":">1,000,000"}}`
   → ELEVATED, routed FULL DILIGENCE.
5. **POST /api/v1/engagements/1/ddq** → `{"answers":{"IS2":"MARGINAL"}}`
   → residual **HIGH → DO NOT PROCEED** (critical-control override).
6. **POST /api/v1/vendors/1/critical** → `{"reason":"Systemic dependency"}`
   → Tier 0, human-designated.
7. **POST /api/v1/intel/financial / reputation / evidence** → the engines.
8. **GET /api/v1/audit/verify** → tamper-evident chain intact.

## Notes
- Demo uses SQLite (`bro_demo.db`) + deterministic-local AI — no API key needed.
- Demo settings (header trust, demo secret) are set by run_demo.py; do NOT use
  them in production — see docs/DEPLOYMENT.md for the real config.
- Default login: admin / admin.
