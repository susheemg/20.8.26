"""
Group A: persistence + RBAC (ported from the uploaded Flask app's database.py).

SQLAlchemy 2.0 models. Works on SQLite (zero-infra, matches their default and
keeps our 'runs offline' stance) and Postgres (our production target) via the
same models — only the engine URL changes.

Faithful port of their roles / permissions / users / vendors / engagements,
reconciled with our engine's concepts (Tier, bands, lifecycle stage). The 49
permissions across 10 categories and the 4 system roles are reproduced exactly.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker,
)


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- RBAC ----------

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)
    label: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    color: Mapped[str] = mapped_column(String, default="#1A4D3C")
    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions", back_populates="roles")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)
    label: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    roles: Mapped[list[Role]] = relationship(
        secondary="role_permissions", back_populates="permissions")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    perm_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"), primary_key=True)
    # graded access when the grant exists: read | write | modify  (denied = no row)
    access: Mapped[str] = mapped_column(String, default="modify")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    email: Mapped[Optional[str]] = mapped_column(String, default=None)
    full_name: Mapped[Optional[str]] = mapped_column(String, default=None)
    password_hash: Mapped[str] = mapped_column(String)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # supplier-user scoping (row-level access) + backup-user support
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None)   # supplier users: their vendor
    # Buyer scoping: the business unit(s) this user acts for. Comma-separated where a
    # buyer covers more than one. When unset, the BUs are derived from the engagements
    # they own, so existing deployments scope correctly without a backfill.
    business_unit: Mapped[Optional[str]] = mapped_column(String, default=None)
    is_backup: Mapped[bool] = mapped_column(Boolean, default=False)          # backup supplier user
    managed_by: Mapped[Optional[str]] = mapped_column(String, default=None)  # assessor/controller who created
    phone: Mapped[Optional[str]] = mapped_column(String, default=None)
    secondary_email: Mapped[Optional[str]] = mapped_column(String, default=None)
    timezone: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    role: Mapped[Role] = relationship()


# ---------- core domain ----------

class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    legal_entity: Mapped[Optional[str]] = mapped_column(String, default=None)
    industry: Mapped[Optional[str]] = mapped_column(String, default=None)
    country: Mapped[Optional[str]] = mapped_column(String, default=None)
    contact_email: Mapped[Optional[str]] = mapped_column(String, default=None)
    tier: Mapped[str] = mapped_column(String, default="Tier 3")
    # Tier 0 (critical) — human-only, kept SEPARATE from computed tier (our Q5).
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_reason: Mapped[Optional[str]] = mapped_column(Text, default=None)
    critical_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    critical_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    ext_ref: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EngagementRow(Base):
    __tablename__ = "engagements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    title: Mapped[str] = mapped_column(String)
    service_description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), default=None)
    stage: Mapped[str] = mapped_column(String, default="sourcing")
    status: Mapped[str] = mapped_column(String, default="draft")
    route: Mapped[Optional[str]] = mapped_column(String, default=None)
    inherent_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    inherent_pct: Mapped[Optional[float]] = mapped_column(Float, default=None)
    residual_band: Mapped[Optional[str]] = mapped_column(String, default=None)
    decision: Mapped[Optional[str]] = mapped_column(String, default=None)
    business_contact_name: Mapped[Optional[str]] = mapped_column(String, default=None)
    business_contact_email: Mapped[Optional[str]] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- password hashing ----------
# Their app uses Werkzeug; we use a dependency-free PBKDF2 so the port runs
# anywhere. Format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return secrets.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False



# ---------- engine / session factory ----------

def _enable_sqlite_wal(engine) -> None:
    """Set WAL journal mode + a busy timeout on every SQLite connection.

    WAL lets the background monitoring scheduler write concurrently with web
    requests without 'database is locked' errors. busy_timeout makes a writer
    wait (up to 5s) for a lock instead of failing immediately. Both are no-ops
    on the shared in-memory engine (handled separately) and irrelevant to
    Postgres. Safe and non-breaking.
    """
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _rec):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()


def make_engine(url: Optional[str] = None):
    url = url or os.environ.get("BRO_DB_URL", "sqlite:///bro.db")
    if url == "sqlite:///:memory:" or url == "sqlite://":
        # Shared in-memory DB: every connection must see the same tables.
        from sqlalchemy.pool import StaticPool
        return create_engine(
            "sqlite://", future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    # Normalise managed-Postgres URLs (Render/Heroku give 'postgres://...').
    # SQLAlchemy 2.x needs 'postgresql://' and psycopg 3 wants the '+psycopg' driver.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args=connect_args, future=True)
        _enable_sqlite_wal(eng)
        return eng
    # Managed Postgres: tuned pool + pre-ping + recycle to survive proxy/idle drops.
    def _envint(k, d):
        try:
            return int(os.environ.get(k, d))
        except ValueError:
            return d
    return create_engine(
        url, connect_args=connect_args, future=True,
        pool_pre_ping=True,
        pool_size=_envint("BRO_DB_POOL_SIZE", 10),
        max_overflow=_envint("BRO_DB_MAX_OVERFLOW", 20),
        pool_timeout=_envint("BRO_DB_POOL_TIMEOUT", 30),
        pool_recycle=_envint("BRO_DB_POOL_RECYCLE", 1800),
    )


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
