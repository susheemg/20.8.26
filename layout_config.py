"""nav & layout config

Revision ID: layout_config
Revises: content_studio
Create Date: 2026-06-24 17:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'layout_config'
down_revision = 'content_studio'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'layout_setting' not in set(insp.get_table_names()):
        op.create_table(
            'layout_setting',
            sa.Column('scope', sa.String(), primary_key=True),
            sa.Column('ref', sa.String(), primary_key=True),
            sa.Column('hidden', sa.Boolean(), default=False),
            sa.Column('sort_order', sa.Integer()),
            sa.Column('updated_by', sa.String()),
            sa.Column('updated_at', sa.DateTime()),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'layout_setting' in set(insp.get_table_names()):
        op.drop_table('layout_setting')
