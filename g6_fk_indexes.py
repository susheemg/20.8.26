"""gap-6: composite FK indexes on hot lookup paths

Revision ID: g6_fk_indexes
Revises: f3c0b3726465
Create Date: 2026-06-12 18:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'g6_fk_indexes'
down_revision = 'f3c0b3726465'
branch_labels = None
depends_on = None

# (index_name, table, [columns]) — the six hottest FK lookup paths.
INDEXES = [
    ("ix_eng_vendor",        "engagement_records", ["vendor_id"]),
    ("ix_find_engagement",   "finding_records",    ["engagement_id"]),
    ("ix_find_vendor_status","finding_records",    ["vendor_id", "status"]),
    ("ix_assess_engagement", "assessment_records", ["engagement_id"]),
    ("ix_artefact_vendor",   "artefact_records",   ["vendor_id"]),
    ("ix_incident_vendor",   "incident_records",   ["vendor_id"]),
]


def _existing(insp, table):
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, cols in INDEXES:
        if table not in tables:
            continue
        if name in _existing(insp, table):
            continue
        op.create_index(name, table, cols)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, _cols in INDEXES:
        if table in tables and name in _existing(insp, table):
            op.drop_index(name, table_name=table)
