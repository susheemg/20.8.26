"""external connector suite

Revision ID: connector_suite
Revises: platform_learnings
Create Date: 2026-06-22 22:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'connector_suite'
down_revision = 'platform_learnings'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    names = set(insp.get_table_names())
    if 'connector_config' not in names:
        op.create_table(
            'connector_config',
            sa.Column('connector_key', sa.String(), primary_key=True),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('0')),
            sa.Column('base_url', sa.String()),
            sa.Column('secret_name', sa.String()),
            sa.Column('config_json', sa.Text()),
            sa.Column('last_sync_at', sa.DateTime()),
            sa.Column('last_status', sa.String()),
            sa.Column('updated_by', sa.String()),
            sa.Column('updated_at', sa.DateTime()),
        )
    if 'connector_sync_log' not in names:
        op.create_table(
            'connector_sync_log',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('connector_key', sa.String()),
            sa.Column('vendor_id', sa.String()),
            sa.Column('action', sa.String(), server_default='sync'),
            sa.Column('mode', sa.String()),
            sa.Column('status', sa.String(), server_default='ok'),
            sa.Column('records', sa.Integer(), server_default='0'),
            sa.Column('message', sa.Text()),
            sa.Column('created_at', sa.DateTime()),
        )
        op.create_index('ix_connsync_key', 'connector_sync_log', ['connector_key'])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    names = set(insp.get_table_names())
    if 'connector_sync_log' in names:
        op.drop_table('connector_sync_log')
    if 'connector_config' in names:
        op.drop_table('connector_config')
