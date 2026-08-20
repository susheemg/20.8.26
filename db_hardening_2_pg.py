"""db hardening 2 (PostgreSQL only): referential and vocabulary constraints

Implements DB-04 and the enforcement half of DB-05 from the database design review.

WHY THIS IS SEPARATE AND OPT-IN
-------------------------------
Adding foreign keys converts a service-layer convention into a database guarantee,
which is the right end state — but it is the one change in the hardening set that can
reject writes that previously succeeded. It therefore ships as its own revision so it
can be applied deliberately, after the orphan check below has been run against the
target database.

SQLite cannot add constraints to an existing table (no ALTER TABLE ADD CONSTRAINT),
so this migration is a no-op there and the service layer remains the enforcement
point, exactly as before.

Constraints are added NOT VALID first and validated separately: NOT VALID takes only
a brief lock, and VALIDATE CONSTRAINT scans without blocking writes. On a large live
table the naive form would hold an ACCESS EXCLUSIVE lock for the duration of the scan.

PRE-FLIGHT — run this and expect zero rows before applying:

    SELECT 'engagement->vendor' AS rel, COUNT(*) FROM engagement_records c
      WHERE c.vendor_id IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM vendor_records p WHERE p.vendor_id = c.vendor_id)
    UNION ALL SELECT 'assessment->engagement', COUNT(*) FROM assessment_records c
      WHERE c.engagement_id IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM engagement_records p WHERE p.engagement_id = c.engagement_id);

Revision ID: db_hardening_2_pg
Revises: db_hardening_1
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "db_hardening_2_pg"
down_revision = "db_hardening_1"
branch_labels = None
depends_on = None

# (constraint, child table, child column, parent table, parent column)
FKS = [
    ("fk_eng_vendor",        "engagement_records",  "vendor_id",     "vendor_records",     "vendor_id"),
    ("fk_assess_engagement", "assessment_records",  "engagement_id", "engagement_records", "engagement_id"),
    ("fk_assess_vendor",     "assessment_records",  "vendor_id",     "vendor_records",     "vendor_id"),
    ("fk_find_vendor",       "finding_records",     "vendor_id",     "vendor_records",     "vendor_id"),
    ("fk_find_engagement",   "finding_records",     "engagement_id", "engagement_records", "engagement_id"),
    ("fk_contract_vendor",   "contract_records",    "vendor_id",     "vendor_records",     "vendor_id"),
    ("fk_artefact_vendor",   "artefact_records",    "vendor_id",     "vendor_records",     "vendor_id"),
    ("fk_incident_vendor",   "incident_records",    "vendor_id",     "vendor_records",     "vendor_id"),
    ("fk_riskprofile_vendor", "vendor_risk_profile", "vendor_id",    "vendor_records",     "vendor_id"),
]

# DB-05: enforce the canonical vocabularies at the database boundary.
CHECKS = [
    ("ck_finding_status", "finding_records", "status",
     ["Draft", "Open", "In Remediation", "Evidence Submitted", "Validated", "Closed", "Not Valid"]),
    ("ck_finding_severity", "finding_records", "severity",
     ["Critical", "High", "Medium", "Low"]),
    ("ck_engagement_inherent", "engagement_records", "inherent_band",
     ["HIGH", "ELEVATED", "MODERATE", "LOW"]),
    ("ck_engagement_residual", "engagement_records", "residual_band",
     ["HIGH", "ELEVATED", "MODERATE", "LOW"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite cannot add constraints in place; service layer remains authoritative
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    for name, child, ccol, parent, pcol in FKS:
        if child not in tables or parent not in tables:
            continue
        existing = {fk.get("name") for fk in insp.get_foreign_keys(child)}
        if name in existing:
            continue
        # ON DELETE RESTRICT encodes the existing no-hard-delete convention as a
        # guarantee. Deletion is already expressed as soft-delete / close.
        bind.exec_driver_sql(
            f'ALTER TABLE {child} ADD CONSTRAINT {name} '
            f'FOREIGN KEY ({ccol}) REFERENCES {parent} ({pcol}) '
            f'ON DELETE RESTRICT NOT VALID')
        bind.exec_driver_sql(f'ALTER TABLE {child} VALIDATE CONSTRAINT {name}')

    for name, table, col, allowed in CHECKS:
        if table not in tables:
            continue
        vals = ", ".join("'" + v.replace("'", "''") + "'" for v in allowed)
        try:
            bind.exec_driver_sql(
                f'ALTER TABLE {table} ADD CONSTRAINT {name} '
                f'CHECK ({col} IS NULL OR {col} IN ({vals})) NOT VALID')
            bind.exec_driver_sql(f'ALTER TABLE {table} VALIDATE CONSTRAINT {name}')
        except Exception:
            # A validation failure means undocumented values remain: fix the data
            # (db_hardening_1 normalises the known variants) and re-run.
            raise


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, table, _c, _a in CHECKS:
        bind.exec_driver_sql(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}')
    for name, child, _cc, _p, _pc in FKS:
        bind.exec_driver_sql(f'ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {name}')
