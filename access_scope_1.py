"""access scoping + chat history: user business_unit, conversation session provenance

Supports v4.25.8:
  * users.business_unit          — explicit BU assignment for buyer scoping. Nullable:
                                   when unset the BUs are derived from the engagements
                                   the user owns, so no backfill is required.
  * conversation_sessions.*      — owner, business unit, subject, vendor, status and
                                   last-activity, so unfinished chats can be listed,
                                   resumed and access-scoped.

Idempotent: every column is added only if absent, so this is safe on databases that
were created by create_all and later stamped.

Revision ID: access_scope_1
Revises: db_hardening_2_pg
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = "access_scope_1"
down_revision = "db_hardening_2_pg"
branch_labels = None
depends_on = None

USER_COLS = [("business_unit", sa.String())]
SESSION_COLS = [
    ("created_by", sa.String()),
    ("business_unit", sa.String()),
    ("vendor_id", sa.String()),
    ("subject_label", sa.String()),
    ("status", sa.String()),
    ("updated_at", sa.DateTime()),
]
INDEXES = [
    ("ix_session_created_by", "conversation_sessions", ["created_by"]),
    ("ix_session_bu", "conversation_sessions", ["business_unit"]),
    ("ix_session_vendor", "conversation_sessions", ["vendor_id"]),
    ("ix_session_status", "conversation_sessions", ["status"]),
    ("ix_session_updated", "conversation_sessions", ["updated_at"]),
]


def _cols(insp, table):
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "users" in tables:
        existing = _cols(insp, "users")
        for name, typ in USER_COLS:
            if name not in existing:
                op.add_column("users", sa.Column(name, typ, nullable=True))

    if "conversation_sessions" in tables:
        existing = _cols(insp, "conversation_sessions")
        for name, typ in SESSION_COLS:
            if name not in existing:
                op.add_column("conversation_sessions", sa.Column(name, typ, nullable=True))
        # Existing rows: treat as active, and seed last-activity from creation so the
        # ordering in Previous Chats is sensible from the first load.
        bind.exec_driver_sql(
            "UPDATE conversation_sessions SET status='active' WHERE status IS NULL")
        bind.exec_driver_sql(
            "UPDATE conversation_sessions SET updated_at=created_at WHERE updated_at IS NULL")

        have = {i["name"] for i in insp.get_indexes("conversation_sessions")}
        for name, table, cols in INDEXES:
            if name in have:
                continue
            try:
                op.create_index(name, table, cols)
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "conversation_sessions" in tables:
        have = {i["name"] for i in insp.get_indexes("conversation_sessions")}
        for name, table, _c in INDEXES:
            if name in have:
                try:
                    op.drop_index(name, table_name=table)
                except Exception:
                    pass
        existing = _cols(insp, "conversation_sessions")
        for name, _t in SESSION_COLS:
            if name in existing:
                try:
                    op.drop_column("conversation_sessions", name)
                except Exception:
                    pass
    if "users" in tables and "business_unit" in _cols(insp, "users"):
        try:
            op.drop_column("users", "business_unit")
        except Exception:
            pass
