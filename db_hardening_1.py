"""db hardening 1: audit subject columns + indexes, join indexes, canonical vocabulary

Implements findings DB-02, DB-03, DB-05 from the database design review
(DOC-DBR-001). Idempotent throughout: every object is created only if absent, so the
migration is safe on databases that were built by create_all and later stamped.

Revision ID: db_hardening_1
Revises: user_profile_fields
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "db_hardening_1"
down_revision = "user_profile_fields"
branch_labels = None
depends_on = None

# DB-02: business-key columns that carry joins and scoped filters.
INDEXES = [
    ("ix_audit_vendor",          "audit_log",            ["vendor_id"]),
    ("ix_audit_engagement",      "audit_log",            ["engagement_id"]),
    ("ix_audit_actor",           "audit_log",            ["actor"]),
    ("ix_audit_action",          "audit_log",            ["action"]),
    ("ix_audit_created",         "audit_log",            ["created_at"]),
    ("ix_audit_seq",             "audit_log",            ["seq"]),
    ("ix_eng_vendor",            "engagement_records",   ["vendor_id"]),
    ("ix_eng_assessment",        "engagement_records",   ["assessment_id"]),
    ("ix_assess_engagement",     "assessment_records",   ["engagement_id"]),
    ("ix_assess_vendor",         "assessment_records",   ["vendor_id"]),
    ("ix_find_vendor_status",    "finding_records",      ["vendor_id", "status"]),
    ("ix_find_engagement",       "finding_records",      ["engagement_id"]),
    ("ix_find_assessment",       "finding_records",      ["assessment_id"]),
    ("ix_remediation_finding",   "remediation_records",  ["finding_id"]),
    ("ix_contract_vendor",       "contract_records",     ["vendor_id"]),
    ("ix_contract_engagement",   "contract_records",     ["engagement_id"]),
    ("ix_artefact_vendor",       "artefact_records",     ["vendor_id"]),
    ("ix_incident_vendor",       "incident_records",     ["vendor_id"]),
    ("ix_issue_vendor",          "issue_records",        ["vendor_id"]),
    ("ix_riskprofile_vendor",    "vendor_risk_profile",  ["vendor_id"]),
    ("ix_screening_vendor",      "vendor_screening",     ["vendor_id"]),
    ("ix_sla_vendor",            "sla_records",          ["vendor_id"]),
    ("ix_sla_engagement",        "sla_records",          ["engagement_id"]),
    ("ix_slameas_sla",           "sla_measurements",     ["sla_id"]),
    ("ix_storeddoc_vendor",      "stored_documents",     ["vendor_id"]),
    ("ix_storeddoc_engagement",  "stored_documents",     ["engagement_id"]),
    ("ix_fourthparty_vendor",    "fourth_party_vendors", ["vendor_id"]),
    ("ix_scorecard_dim",         "scorecard_dimension",  ["scorecard_id"]),
    ("ix_scorecard_kpi_dim",     "scorecard_kpi",        ["dimension_id"]),
]

# DB-05: historical values → canonical vocabulary (see app/features/domain/vocab.py).
FINDING_STATUS_FIXES = [
    ("In remediation", "In Remediation"),
    ("in remediation", "In Remediation"),
    ("Under Remediation", "In Remediation"),
    ("in-progress", "In Remediation"),
    ("In-Progress", "In Remediation"),
    ("Published", "Open"),
    ("open", "Open"),
    ("closed", "Closed"),
    ("Remediated", "Validated"),
    ("Verified", "Validated"),
    ("validated", "Validated"),
    ("evidence-submitted", "Evidence Submitted"),
    ("draft", "Draft"),
]
SEVERITY_FIXES = [("critical", "Critical"), ("high", "High"),
                  ("medium", "Medium"), ("moderate", "Medium"), ("low", "Low")]


def _tables(insp):
    return set(insp.get_table_names())


def _cols(insp, table):
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _indexes(insp, table):
    try:
        return {i["name"] for i in insp.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = _tables(insp)

    # ── DB-03: audit subject columns ───────────────────────────────────────────
    if "audit_log" in tables:
        existing = _cols(insp, "audit_log")
        if "vendor_id" not in existing:
            op.add_column("audit_log", sa.Column("vendor_id", sa.String(), nullable=True))
        if "engagement_id" not in existing:
            op.add_column("audit_log", sa.Column("engagement_id", sa.String(), nullable=True))
        # Backfill from the JSON payload already stored in `detail`. Uses a LIKE-based
        # extraction so it works identically on SQLite and PostgreSQL without a
        # JSON function dependency. The hash chain is untouched: these columns are
        # not part of the hash input, so existing chains remain verifiable.
        for col, prefix in (("vendor_id", "VEN-"), ("engagement_id", "ENG-")):
            bind.exec_driver_sql(f"""
                UPDATE audit_log
                   SET {col} = substr(detail,
                                      instr(detail, '"{col}": "{prefix}') + length('"{col}": "'),
                                      10)
                 WHERE {col} IS NULL
                   AND detail LIKE '%"{col}": "{prefix}%'
            """) if bind.dialect.name == "sqlite" else bind.exec_driver_sql(f"""
                UPDATE audit_log
                   SET {col} = substring(detail from '"{col}": "({prefix}[0-9A-Za-z_-]+)"')
                 WHERE {col} IS NULL
                   AND detail LIKE '%"{col}": "{prefix}%'
            """)

    # ── DB-02: indexes on join and filter columns ──────────────────────────────
    for name, table, cols in INDEXES:
        if table not in tables:
            continue
        if not set(cols).issubset(_cols(insp, table)):
            continue
        if name in _indexes(insp, table):
            continue
        try:
            op.create_index(name, table, cols)
        except Exception:
            pass  # index already present under another name

    # ── DB-05: normalise controlled vocabularies ───────────────────────────────
    if "finding_records" in tables:
        for old, new in FINDING_STATUS_FIXES:
            bind.exec_driver_sql(
                "UPDATE finding_records SET status = %s WHERE status = %s"
                if bind.dialect.name != "sqlite" else
                "UPDATE finding_records SET status = ? WHERE status = ?", (new, old))
        for old, new in SEVERITY_FIXES:
            bind.exec_driver_sql(
                "UPDATE finding_records SET severity = %s WHERE severity = %s"
                if bind.dialect.name != "sqlite" else
                "UPDATE finding_records SET severity = ? WHERE severity = ?", (new, old))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = _tables(insp)
    for name, table, _c in INDEXES:
        if table in tables and name in _indexes(insp, table):
            try:
                op.drop_index(name, table_name=table)
            except Exception:
                pass
    if "audit_log" in tables:
        existing = _cols(insp, "audit_log")
        for col in ("vendor_id", "engagement_id"):
            if col in existing:
                try:
                    op.drop_column("audit_log", col)
                except Exception:
                    pass
    # Vocabulary normalisation is deliberately not reversed: the prior values were
    # inconsistent variants, and restoring them would reintroduce the defect.
