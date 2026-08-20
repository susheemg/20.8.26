"""platform documentation store (SOP / TDA)

Revision ID: platform_docs
Revises: perf_sla_issues
Create Date: 2026-06-12 23:50:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'platform_docs'
down_revision = 'perf_sla_issues'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'platform_docs' not in set(insp.get_table_names()):
        op.create_table(
            'platform_docs',
            sa.Column('kind', sa.String(), primary_key=True),
            sa.Column('html', sa.Text()),
            sa.Column('doc_version', sa.String()),
            sa.Column('updated_by', sa.String()),
            sa.Column('updated_at', sa.DateTime()),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'platform_docs' in set(insp.get_table_names()):
        op.drop_table('platform_docs')
