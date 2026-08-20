"""performance: SLA register, SLA measurements, performance issues

Revision ID: perf_sla_issues
Revises: g6_fk_indexes
Create Date: 2026-06-12 22:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'perf_sla_issues'
down_revision = 'g6_fk_indexes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if 'sla_records' not in tables:
        op.create_table(
            'sla_records',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('sla_id', sa.String(), nullable=False, unique=True),
            sa.Column('engagement_id', sa.String(), index=True),
            sa.Column('vendor_id', sa.String(), index=True),
            sa.Column('contract_id', sa.String()),
            sa.Column('description', sa.String(), nullable=False),
            sa.Column('threshold_type', sa.String(), server_default='min'),
            sa.Column('threshold', sa.Float(), server_default='0'),
            sa.Column('unit', sa.String(), server_default=''),
            sa.Column('baseline', sa.Float()),
            sa.Column('window', sa.String(), server_default='monthly'),
            sa.Column('source', sa.String(), server_default='manual'),
            sa.Column('active', sa.Boolean(), server_default=sa.true()),
            sa.Column('created_by', sa.String()),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
        )

    if 'sla_measurements' not in tables:
        op.create_table(
            'sla_measurements',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('sla_id', sa.String(), index=True),
            sa.Column('period', sa.String()),
            sa.Column('value', sa.Float()),
            sa.Column('recorded_by', sa.String()),
            sa.Column('recorded_at', sa.DateTime()),
        )
        op.create_index('ix_slameas_sla_period', 'sla_measurements', ['sla_id', 'period'])

    if 'performance_issues' not in tables:
        op.create_table(
            'performance_issues',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('pis_id', sa.String(), nullable=False, unique=True),
            sa.Column('engagement_id', sa.String(), index=True),
            sa.Column('vendor_id', sa.String(), index=True),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('description', sa.Text()),
            sa.Column('category', sa.String()),
            sa.Column('severity', sa.String(), server_default='Medium'),
            sa.Column('source', sa.String(), server_default='Manual'),
            sa.Column('status', sa.String(), server_default='Open'),
            sa.Column('owner', sa.String()),
            sa.Column('raised_by', sa.String()),
            sa.Column('raised_date', sa.String()),
            sa.Column('due_date', sa.String()),
            sa.Column('closed_date', sa.String()),
            sa.Column('linked_ref', sa.String()),
            sa.Column('sla_id', sa.String()),
            sa.Column('suggested_remediation', sa.Text()),
            sa.Column('progress_notes', sa.Text(), server_default='[]'),
            sa.Column('risk_accepted', sa.Boolean(), server_default=sa.false()),
            sa.Column('acceptance_rationale', sa.Text()),
            sa.Column('accepted_by', sa.String()),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for t in ('performance_issues', 'sla_measurements', 'sla_records'):
        if t in tables:
            op.drop_table(t)
