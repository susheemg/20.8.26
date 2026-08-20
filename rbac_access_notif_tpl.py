"""graded rbac access + notification templates

Revision ID: rbac_access_notif_tpl
Revises: layout_config
Create Date: 2026-07-02 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'rbac_access_notif_tpl'
down_revision = 'layout_config'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('role_permissions')}
    if 'access' not in cols:
        op.add_column('role_permissions',
                      sa.Column('access', sa.String(), server_default='modify'))
    if 'notif_template' not in set(insp.get_table_names()):
        op.create_table(
            'notif_template',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.Text()),
            sa.Column('subject', sa.Text()),
            sa.Column('body', sa.Text()),
            sa.Column('groups', sa.Text()),
            sa.Column('enabled', sa.Integer(), server_default='1'),
            sa.Column('updated_by', sa.String()),
            sa.Column('updated_at', sa.String()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'notif_template' in set(insp.get_table_names()):
        op.drop_table('notif_template')
    cols = {c['name'] for c in insp.get_columns('role_permissions')}
    if 'access' in cols:
        with op.batch_alter_table('role_permissions') as b:
            b.drop_column('access')
