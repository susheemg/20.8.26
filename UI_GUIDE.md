# BRO Web UI

A server-rendered web interface is served at the app root (`/`). It is a single
styled page that talks to the same `/api/v1` JSON API as any other client, holding
the JWT in sessionStorage — so the security model is identical (no separate auth path).

## Access
1. Run the app (`python run.py` or via Docker) and open `http://127.0.0.1:8000/`.
2. Sign in (default admin / admin, or your `BRO_ADMIN_PASSWORD`).
3. The token is obtained from `POST /api/v1/login` and sent as a Bearer header on
   every subsequent API call the UI makes.

## Screens
- **Dashboard** — portfolio counts, residual-risk distribution, operational by-stage.
- **Vendors** — register; create vendors; designate critical (Tier 0, human-only).
- **Engagements** — create and walk the lifecycle: IRQ → DDQ → contract → terminate,
  with inherent/residual bands and decision shown live.
- **Action Plan** — findings board with severity counts; raise and advance findings.
- **Monitoring** — run financial sweeps; ALERT/CRITICAL auto-raises a reassessment.
- **Intelligence** — run Vera / Mira / Matt / Isaac and view results.
- **Audit Trail** — view the hash-chained log; one-click chain verification.

## Notes
- The UI uses Google Fonts (Fraunces + Spline Sans). Offline, it falls back to
  system serif/sans — layout and colour are unaffected.
- Engagement list is per-session (the API has no list-all endpoint by design);
  created engagements are tracked client-side for the session. Add a
  `GET /engagements` endpoint if you want a persistent cross-session list.
