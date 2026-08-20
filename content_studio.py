"""content studio overrides

Revision ID: content_studio
Revises: connector_suite
Create Date: 2026-06-24 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'content_studio'
down_revision = 'connector_suite'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'content_override' not in set(insp.get_table_names()):
        op.create_table(
            'content_override',
            sa.Column('key', sa.String(), primary_key=True),
            sa.Column('value', sa.Text()),
            sa.Column('updated_by', sa.String()),
            sa.Column('updated_at', sa.DateTime()),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'content_override' in set(insp.get_table_names()):
        op.drop_table('content_override')
