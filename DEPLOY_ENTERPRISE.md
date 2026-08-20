# Enterprise deployment — foundation

This build adds the production-foundation pieces (multi-tenancy excluded).

## Database & migrations
- Set `BRO_DB_URL` to managed Postgres, e.g. `postgresql://user:pass@host:5432/bro`
  (`postgres://` and `postgresql://` are auto-normalised to the psycopg driver).
- Tuned pool via `BRO_DB_POOL_SIZE` (10), `BRO_DB_MAX_OVERFLOW` (20),
  `BRO_DB_POOL_TIMEOUT` (30), `BRO_DB_POOL_RECYCLE` (1800); `pool_pre_ping` is on.
- In production set `BRO_DB_AUTO_CREATE=0` and manage schema with Alembic:
  `alembic upgrade head`. The baseline migration is in `migrations/versions/`.
  Generate new ones with `alembic revision --autogenerate -m "<change>"`.

## Secrets
All secrets resolve through `app/features/secrets.py` in order:
env var → `<NAME>_FILE` (Docker/K8s secret) → AWS Secrets Manager → Vault.
- `BRO_SECRET_KEY` (JWT signing) is **required** in production — the app fails fast if missing.
- Backend select: `BRO_SECRETS_BACKEND=aws` (+ `BRO_AWS_SECRET_PREFIX`, `AWS_REGION`)
  or `=vault` (+ `BRO_VAULT_ADDR`, `BRO_VAULT_TOKEN`, `BRO_VAULT_MOUNT`, `BRO_VAULT_PATH`).
- Admin seed: in production set a strong `BRO_ADMIN_PASSWORD` (>=12 chars) — the app
  refuses to seed `admin/admin`. `BRO_ADMIN_USERNAME` / `BRO_ADMIN_EMAIL` optional.

## SSO (OIDC) — Okta / Entra ID / Ping / Auth0 / Google
Set: `BRO_OIDC_ISSUER`, `BRO_OIDC_CLIENT_ID`, `BRO_OIDC_CLIENT_SECRET`,
`BRO_OIDC_REDIRECT_URI` (`https://<host>/auth/oidc/callback`).
- Scopes default `openid email profile groups`; groups claim `BRO_OIDC_GROUPS_CLAIM`.
- Map IdP groups to roles: `BRO_OIDC_ROLE_MAP` (JSON, e.g.
  `{"TPRM-Admins":"admin","TPRM-Assessors":"vrm"}`), `BRO_OIDC_DEFAULT_ROLE` (default `vendor`).
- Flow: `/auth/oidc/login` → IdP → `/auth/oidc/callback` provisions/updates the user,
  maps the role and signs them in. id_token is verified against the provider JWKS.

## SCIM 2.0 provisioning
Set `BRO_SCIM_TOKEN` and point your IdP at `/scim/v2`. Endpoints: Users (GET/POST/
GET{id}/PATCH/PUT/DELETE) and Groups (GET). DELETE deactivates (audit trail preserved).

## Frontend
The SPA JavaScript now lives in `app/static/app.js` (served at `/static/app.js`),
extracted from the page template so it is browser-cacheable and editable with JS tooling.
