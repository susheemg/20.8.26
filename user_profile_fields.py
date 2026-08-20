"""user profile fields — phone, secondary_email, timezone

Revision ID: user_profile_fields
Revises: user_scope_backup
Create Date: 2026-07-05 06:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'user_profile_fields'
down_revision = 'user_scope_backup'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('users')}
    for col in ('phone', 'secondary_email', 'timezone'):
        if col not in cols:
            op.add_column('users', sa.Column(col, sa.String()))


def downgrade() -> None:
    for col in ('phone', 'secondary_email', 'timezone'):
        try:
            op.drop_column('users', col)
        except Exception:
            pass
