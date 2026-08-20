# Database hardening — operator guide (v4.25.7)

Implements findings DB-01 through DB-08 from the database design review
(`DOC-DBR-001`). This note tells an operator what changed, what to run, and what to
check afterwards.

## What changed

| Finding | Change | Where |
|---|---|---|
| DB-01 | Fresh databases are stamped at the Alembic head on creation; existing unstamped or unrecognised databases log a warning at boot | `bro_app._schema_revision_check()` |
| DB-02 | Business-key columns carry `index=True` on the models, so **both** provisioning paths create them; 29 indexes also added by migration | `registry_models.py`, `db_hardening_1` |
| DB-03 | `audit_log` gains indexed `vendor_id` / `engagement_id`; all four unbounded audit loads are bounded | `models_feature.py`, `routers/domain.py` |
| DB-04 | PostgreSQL foreign keys and CHECK constraints (**opt-in, separate revision**) | `db_hardening_2_pg` |
| DB-05 | One canonical vocabulary module; legacy values normalised in the database | `features/domain/vocab.py`, `db_hardening_1` |
| DB-06 | `next_id()` locks the counter row on PostgreSQL | `registry_service.next_id()` |
| DB-08 | Band divergence detected by a monitoring sweep task | `lifecycle/monitoring.py` |

## Upgrading an existing deployment

### 1. Databases already managed by Alembic

```bash
alembic upgrade db_hardening_1
```

This adds the audit subject columns, backfills them from the JSON already stored in
`detail`, creates the indexes, and normalises finding status and severity values. It
is idempotent and safe to re-run.

### 2. Databases built by `create_all` (no `alembic_version` table)

The application will log at boot:

```
SCHEMA: database has no Alembic stamp ... run: alembic stamp db_hardening_1
```

Verify the schema matches the models, then:

```bash
alembic stamp user_profile_fields   # the revision the schema actually reflects
alembic upgrade db_hardening_1
```

Do **not** stamp straight to `db_hardening_1` unless the audit columns and indexes
already exist — stamping asserts that a migration has run, and a false assertion
means the change never happens.

As a safety net, the application also self-heals the audit columns at boot on SQLite,
so a demo or development database keeps working without operator action.

### 3. New deployments

Nothing to do. A fresh database is created from the models and stamped
automatically, and both paths now produce the same schema.

## Optional: PostgreSQL constraints (DB-04)

This converts service-layer conventions into database guarantees, and is the one
change that can reject writes that previously succeeded. Apply it deliberately.

**Pre-flight — expect zero rows:**

```sql
SELECT 'engagement->vendor' AS rel, COUNT(*) FROM engagement_records c
  WHERE c.vendor_id IS NOT NULL AND NOT EXISTS
    (SELECT 1 FROM vendor_records p WHERE p.vendor_id = c.vendor_id)
UNION ALL SELECT 'assessment->engagement', COUNT(*) FROM assessment_records c
  WHERE c.engagement_id IS NOT NULL AND NOT EXISTS
    (SELECT 1 FROM engagement_records p WHERE p.engagement_id = c.engagement_id)
UNION ALL SELECT 'finding->vendor', COUNT(*) FROM finding_records c
  WHERE c.vendor_id IS NOT NULL AND NOT EXISTS
    (SELECT 1 FROM vendor_records p WHERE p.vendor_id = c.vendor_id);
```

If any row is non-zero, resolve the orphans first — the constraint will not validate
and the migration will fail loudly rather than skip them.

Then:

```bash
alembic upgrade db_hardening_2_pg
```

Constraints are added `NOT VALID` and validated separately, so the table is not
locked for the duration of the scan. The migration is a no-op on SQLite, which cannot
add constraints to an existing table.

## API changes

`GET /api/v1/audit` previously returned a bare list of every entry. It now returns a
bounded object:

```json
{ "entries": [...], "count": 200, "has_more": true, "next_before_seq": 1234 }
```

Filters: `vendor_id`, `engagement_id`, `actor`, `action`, `limit` (max 500),
`before_seq` for paging.

`GET /api/v1/audit/verify` verifies the most recent 5,000 entries by default and
reports its scope. Pass `full=1` for a whole-chain walk — use this for periodic
assurance runs and when producing evidence.

`GET /api/v1/audit/export.csv` accepts `vendor_id`, `engagement_id` and `max_rows`,
and now includes the subject columns.

**The hash chain is unchanged.** The subject columns are not part of the hash input,
so chains written by earlier releases still verify.

## Post-upgrade checks

```bash
# 1. schema is stamped and recognised (no SCHEMA: warning at boot)
# 2. chain still verifies end to end
curl -s "$BASE/api/v1/audit/verify?full=1" | jq '.intact'          # expect true

# 3. subject columns populated for new writes
curl -s "$BASE/api/v1/audit?vendor_id=VEN-000001" | jq '.count'

# 4. vocabulary normalised — expect only canonical values
#    Draft | Open | In Remediation | Evidence Submitted | Validated | Closed | Not Valid
SELECT status, COUNT(*) FROM finding_records GROUP BY 1;

# 5. band divergence surfaced by the sweep
curl -s "$BASE/api/v1/monitoring/run" -X POST | jq '.tasks.band_reconciliation'
```

## Not included in this release

Deferred deliberately, with the reasoning recorded in the design review:

- **DB-07** temporal columns stored as text — needs a conversion pass with a
  parse-failure report; the failures are latent data-quality defects and want
  handling, not silent coercion.
- **DB-09** `engagement_ext` (126 columns) split by concern — touches every
  engagement read and write path.
- **DB-10** JSON columns to `JSONB` — low risk, but each field needs a
  promote-or-keep decision.
- **DB-11** nullability tightening — requires a per-table judgement on whether each
  reference is genuinely optional.
- **DB-12** retention and partitioning — best designed before production volume
  accrues, but not urgent at current scale.
- **DB-13** dropping the 13 empty legacy v1 tables — trivial, but wants explicit
  sign-off that no external report reads them.
