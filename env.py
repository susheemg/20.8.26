"""Alembic migration environment for Brata.

Resolves the DB URL the same way the app does (BRO_DB_URL, with postgres://
normalisation and secret resolution) and targets the full SQLAlchemy metadata so
`alembic revision --autogenerate` sees every table.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# Import Base and every model module so all tables register on the metadata.
from app.features.domain.models_db import Base, make_engine  # noqa: E402
from app.features.domain import (  # noqa: E402,F401
    models_feature, registry_models, master_ext, config_store,
)
from app.features.lifecycle import documents, exit_planning  # noqa: E402,F401
from app.features.assessment import methodology  # noqa: E402,F401
try:  # optional/feature modules that define tables
    from app.features.intelligence import oss as _oss  # noqa: F401
    from app.features.assessment import feedback as _fb  # noqa: F401
    from app.features.intelligence import pestle as _pes  # noqa: F401
except Exception:
    pass

target_metadata = Base.metadata


def _url() -> str:
    from app.features.admin.secrets import get_secret
    return get_secret("BRO_DB_URL", default="sqlite:///bro.db")


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata,
                       literal_binds=True, compare_type=True,
                       dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Reuse the app's engine builder so URL normalisation/pooling matches runtime.
    connectable = make_engine(_url())
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
