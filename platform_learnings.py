"""platform learnings log

Revision ID: platform_learnings
Revises: platform_docs
Create Date: 2026-06-15 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'platform_learnings'
down_revision = 'platform_docs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'platform_learnings' not in set(insp.get_table_names()):
        op.create_table(
            'platform_learnings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('category', sa.String(), server_default='Risk pattern'),
            sa.Column('insight', sa.Text()),
            sa.Column('source_engagement', sa.String()),
            sa.Column('source_vendor', sa.String()),
            sa.Column('source_assessment', sa.String()),
            sa.Column('origin', sa.String(), server_default='auto'),
            sa.Column('confidence', sa.String(), server_default='Medium'),
            sa.Column('applied_count', sa.Integer(), server_default='0'),
            sa.Column('created_by', sa.String()),
            sa.Column('created_at', sa.DateTime()),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'platform_learnings' in set(insp.get_table_names()):
        op.drop_table('platform_learnings')
