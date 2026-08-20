"""supplier user scoping + backup flag

Revision ID: user_scope_backup
Revises: rbac_access_notif_tpl
Create Date: 2026-07-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'user_scope_backup'
down_revision = 'rbac_access_notif_tpl'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('users')}
    if 'vendor_id' not in cols:
        op.add_column('users', sa.Column('vendor_id', sa.String()))
    if 'is_backup' not in cols:
        op.add_column('users', sa.Column('is_backup', sa.Boolean(), server_default=sa.false()))
    if 'managed_by' not in cols:
        op.add_column('users', sa.Column('managed_by', sa.String()))


def downgrade() -> None:
    for col in ('vendor_id', 'is_backup', 'managed_by'):
        try:
            op.drop_column('users', col)
        except Exception:
            pass
