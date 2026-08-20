"""System configuration store.

A small key/value settings table with a typed defaults registry. Only settings
that are actually READ at runtime by the platform live here, so every value the
admin can change has a real effect (no dead toggles). Engine code calls
``get_config(s, key, default)`` at request time, falling back to the registry
default when the row is absent.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.features.domain.models_db import Base


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line.
    Never raises — observability must not change control flow."""
    try:
        from app.features.admin.security import log_json as _lj
    except Exception:
        return
    try:
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass



def _now():
    return datetime.now(timezone.utc)


class SystemConfig(Base):
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True, index=True)
    value_json: Mapped[str] = mapped_column(Text)            # JSON-encoded value
    category: Mapped[str] = mapped_column(String, default="General")
    label: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    value_type: Mapped[str] = mapped_column(String, default="int")  # int|number|text
    updated_by: Mapped[str] = mapped_column(String, default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# key, default, category, label, description, type
DEFAULTS = [
    ("criticality.threshold", 6, "Risk thresholds", "Critical-vendor score threshold",
     "Weighted score (max 11) at or above which the model designates a vendor Critical. "
     "Lower it to widen the critical population; raise it to tighten.", "int"),
    ("criticality.near_margin", 2, "Risk thresholds", "Near-miss margin",
     "Vendors scoring within this many points below the threshold are surfaced as near-misses "
     "for review.", "int"),
    ("incident.sla.Critical", 24, "Incident notification SLA (hours)", "Critical severity",
     "Hours within which a supplier must notify the firm of a Critical incident; drives the "
     "notification-compliance light.", "int"),
    ("incident.sla.High", 48, "Incident notification SLA (hours)", "High severity",
     "Notification window (hours) for High-severity supplier incidents.", "int"),
    ("incident.sla.Medium", 72, "Incident notification SLA (hours)", "Medium severity",
     "Notification window (hours) for Medium-severity supplier incidents.", "int"),
    ("incident.sla.Low", 120, "Incident notification SLA (hours)", "Low severity",
     "Notification window (hours) for Low-severity supplier incidents.", "int"),
    ("org.display_name", "Global Financial Institution (Demonstrator)", "General",
     "Organisation name", "Shown on the Board / Regulator pack and evidence exports.", "text"),
    ("format.date", "MM-DD-YYYY", "Formatting", "Date display format",
     "How dates are shown across the app. Options: MM-DD-YYYY, DD-MM-YYYY, YYYY-MM-DD.", "text"),
    ("format.currency", "USD", "Formatting", "Default currency",
     "Default currency for monetary inputs and displays; users can override it per money field.", "text"),
    ("reassessment.months.LOW", 36, "Reassessment cadence (months)", "Low inherent risk",
     "Months between assessments for LOW inherent-risk engagements (3 years). Next-due dates are auto-calculated from this.", "int"),
    ("reassessment.months.MODERATE", 24, "Reassessment cadence (months)", "Medium inherent risk",
     "Months between assessments for MODERATE inherent-risk engagements (2 years).", "int"),
    ("reassessment.months.ELEVATED", 12, "Reassessment cadence (months)", "Elevated inherent risk",
     "Months between assessments for ELEVATED inherent-risk engagements (annual).", "int"),
    ("reassessment.months.HIGH", 12, "Reassessment cadence (months)", "High inherent risk",
     "Months between assessments for HIGH inherent-risk engagements (annual).", "int"),
    ("reassessment.months.CRITICAL", 12, "Reassessment cadence (months)", "Critical inherent risk",
     "Months between assessments for CRITICAL inherent-risk engagements (annual).", "int"),
]

_DEFAULT_MAP = {k: d for (k, d, *_rest) in DEFAULTS}


def default_for(key):
    return _DEFAULT_MAP.get(key)


def seed_defaults(session) -> None:
    """Idempotent: insert any registry settings not already present."""
    have = {c.key for c in session.query(SystemConfig).all()}
    for key, default, cat, label, desc, typ in DEFAULTS:
        if key not in have:
            session.add(SystemConfig(key=key, value_json=json.dumps(default),
                                     category=cat, label=label, description=desc,
                                     value_type=typ, updated_by="system"))
    session.flush()


def get_config(session, key, default=None):
    """Effective value: stored row if present, else registry default, else ``default``."""
    row = session.query(SystemConfig).filter_by(key=key).first()
    if row is not None:
        try:
            return json.loads(row.value_json)
        except Exception as _e:
            _obs_swallow('config_store.py', _e)
    if key in _DEFAULT_MAP:
        return _DEFAULT_MAP[key]
    return default


def _coerce(value, value_type):
    if value_type == "int":
        return int(value)
    if value_type == "number":
        return float(value)
    return str(value)


def set_config(session, key, value, updated_by="admin"):
    """Update an existing registry-backed setting. Returns the row or None if unknown."""
    row = session.query(SystemConfig).filter_by(key=key).first()
    if row is None:
        return None
    row.value_json = json.dumps(_coerce(value, row.value_type))
    row.updated_by = updated_by
    row.updated_at = _now()
    session.flush()
    return row


def reset_config(session, key, updated_by="admin"):
    row = session.query(SystemConfig).filter_by(key=key).first()
    if row is None or key not in _DEFAULT_MAP:
        return None
    row.value_json = json.dumps(_DEFAULT_MAP[key])
    row.updated_by = updated_by
    row.updated_at = _now()
    session.flush()
    return row


def list_config(session):
    return session.query(SystemConfig).order_by(
        SystemConfig.category, SystemConfig.key).all()


def get_json(session, key, default=None):
    """Read a JSON-valued internal setting (not part of the scalar registry)."""
    row = session.query(SystemConfig).filter_by(key=key).first()
    if row is None:
        return default
    try:
        return json.loads(row.value_json)
    except Exception:
        return default


def upsert_json(session, key, value, updated_by="admin", category="_internal"):
    """Create-or-update a JSON-valued internal setting (e.g. nav ordering)."""
    row = session.query(SystemConfig).filter_by(key=key).first()
    if row is None:
        row = SystemConfig(key=key, category=category, label=key,
                           description="Internal setting", value_type="json")
        session.add(row)
    row.value_json = json.dumps(value)
    row.updated_by = updated_by
    row.updated_at = _now()
    session.flush()
    return row


def delete_key(session, key):
    row = session.query(SystemConfig).filter_by(key=key).first()
    if row is not None:
        session.delete(row)
        session.flush()
        return True
    return False


def incident_sla_map(session) -> dict:
    """Effective incident notification SLA hours by severity."""
    return {sev: get_config(session, f"incident.sla.{sev}", dflt)
            for sev, dflt in (("Critical", 24), ("High", 48), ("Medium", 72), ("Low", 120))}
