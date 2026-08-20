# BRO Risk Oracle — Deployment Guide

The unified FastAPI app, deployment-ready. Runs offline on SQLite for demos;
scales to PostgreSQL with real JWT auth for production.

## Files added for deployment
- `Dockerfile` — production image (gunicorn + uvicorn workers)
- `Procfile` — for Render / Railway / Heroku-style PaaS
- `.dockerignore` — keeps tests, docs, db files out of the image
- `requirements.txt` — pinned, production deps
- `app/features/auth.py` — JWT bearer authentication

## Environment variables
| Variable | Purpose | Production? |
|---|---|---|
| `BRO_DB_URL` | DB connection. Unset → SQLite. | **Set to Postgres** |
| `BRO_SECRET_KEY` | JWT signing secret. Unset → ephemeral (resets on restart). | **Set to a strong random value** |
| `BRO_ADMIN_PASSWORD` | Seeded admin password. Unset → `admin`. | **Set, or rotate after first login** |
| `BRO_TRUST_HEADER` | `1` enables the dev `x-user` header. Leave UNSET in prod. | **Leave unset** |

Generate a secret: `python -c "import secrets; print(secrets.token_hex(32))"`

## Authentication model
- `POST /api/v1/login` with username + password returns a signed **JWT bearer token**.
- All protected routes require `Authorization: Bearer <token>`.
- The token is verified (signature + 8h expiry) and resolved to a real user; RBAC
  then checks the user's role permissions per route.
- The old `x-user` header only works when `BRO_TRUST_HEADER=1` (dev/test). In
  production it is ignored, so a caller cannot impersonate a user by setting a header.

## Option 1 — Local / VM
```bash
pip install -r requirements.txt
export BRO_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export BRO_DB_URL="postgresql+psycopg://user:pass@host:5432/bro"   # or omit for SQLite
gunicorn app.bro_app:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --workers 2
```
Put nginx/Caddy in front for TLS. Never expose gunicorn directly.

## Option 2 — Docker (recommended)
```bash
docker build -t bro-risk-oracle .
docker run -p 8000:8000 \
  -e BRO_SECRET_KEY=... \
  -e BRO_ADMIN_PASSWORD=... \
  -e BRO_DB_URL="postgresql+psycopg://user:pass@host:5432/bro" \
  bro-risk-oracle
```
Deploy the same image to Google Cloud Run, AWS App Runner/ECS, or Azure
Container Apps — they provide HTTPS and autoscaling. Cloud Run is the simplest:
push image → set env vars (use the secrets store) → done.

## Option 3 — PaaS (fastest to a public URL)
Push the repo to Render or Railway, add a Postgres add-on, set `BRO_DB_URL`,
`BRO_SECRET_KEY`, `BRO_ADMIN_PASSWORD`. The `Procfile` handles the rest; HTTPS
is automatic.

## First-boot behaviour
On startup the app creates all tables and seeds the 49 permissions, 4 system
roles, and the admin user. Idempotent — safe to restart.

## Pre-launch checklist
- [ ] `BRO_SECRET_KEY` set to a strong random value
- [ ] `BRO_ADMIN_PASSWORD` set (or admin password rotated after first login)
- [ ] `BRO_DB_URL` points at managed Postgres (not SQLite)
- [ ] `BRO_TRUST_HEADER` is NOT set
- [ ] TLS terminating in front of the app
- [ ] Secrets in the platform's secrets manager, not in the repo

## Still to harden beyond this guide
- Token refresh / revocation (currently 8h expiry, no refresh endpoint)
- Rate limiting on `/login`
- DB migrations (currently create-all on boot; add Alembic for schema evolution)
- The four intelligence engines run deterministic-local; wire live providers via
  the provider abstraction when desired.

103 tests passing, including JWT auth verification.

## Document uploads
- `POST /api/v1/documents/upload` (multipart) accepts PDF/text up to 25 MB.
- Files are stored under `BRO_UPLOAD_DIR` (default /tmp/bro_uploads); point this
  at a persistent volume, or swap store_bytes/read_bytes in uploads.py for S3/Blob.
- PDFs are parsed with pdfplumber; assurance docs (SOC 2/ISO) are read by Isaac
  and filed as evidence automatically. Scanned PDFs (no text layer) are flagged
  scanned=True for OCR routing (OCR not yet wired).

## AI integration (Claude / ChatGPT API keys)
The single place to enable AI is environment variables — read by `app/agents/llm_config.py`.
Keys are never stored in the app or committed; they live only in the environment / your
secrets manager.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (Anthropic) |
| `OPENAI_API_KEY` | ChatGPT API key (OpenAI) |
| `BRO_LLM_PROVIDER` | `claude` (default) or `openai` — which to use if both keys present |
| `BRO_LLM_MODEL` | optional model override (default `claude-sonnet-4-20250514` / `gpt-4o`) |

Install the SDK for whichever you use: `pip install anthropic` and/or `pip install openai`.

Examples:
```bash
# Claude
export ANTHROPIC_API_KEY=sk-ant-...
# ChatGPT
export BRO_LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
```

What AI powers when enabled:
- **AI Assessment** — the 10 specialist agents' conversational turns (Stage 0–7).
- Falls back automatically to the tested **deterministic-local** path when no key is set,
  so the app always runs.

Check status any time: **Admin → AI integration**, or `GET /api/v1/ai/status`
(reports enabled/provider/model and which keys are present — never the key itself).
