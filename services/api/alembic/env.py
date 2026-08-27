from __future__ import annotations

import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

from services.api.app import models as _models  # noqa: F401
from services.api.app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _migration_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url") or (
        "postgresql+psycopg://recovery:recovery@localhost:55432/recovery_os"
    )
    url = os.getenv("DATABASE_URL", configured_url)
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


target_metadata = Base.metadata
_ENUM_CHECK_NAMES = {
    "ck_payment_attempts_payment_state",
    "ck_policy_decisions_policy_disposition",
    "ck_recovery_actions_action_status",
    "ck_recovery_actions_payment_surface_type",
    "ck_recovery_actions_recovery_action_type",
    "ck_recovery_cases_case_outcome",
    "ck_recovery_cases_case_payment_state",
    "ck_recovery_cases_case_subscription_state",
    "ck_recovery_cases_contact_disposition",
    "ck_recovery_cases_diagnosis",
    "ck_recovery_cases_revenue_attribution",
    "ck_recovery_events_evidence_kind",
    "ck_revenue_recognition_recognition_attribution",
    "ck_subscriptions_subscription_state",
}


def _include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    del object_, compare_to
    # PostgreSQL reflects SQLAlchemy's non-native Enum checks with normalized SQL
    # that Alembic cannot compare to the post-compiled metadata expression.
    return not (type_ == "check_constraint" and reflected and name in _ENUM_CHECK_NAMES)


def run_migrations_offline() -> None:
    context.configure(
        url=_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _migration_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
