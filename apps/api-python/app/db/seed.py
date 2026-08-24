"""Insert immutable baseline rows after schema initialization."""

from __future__ import annotations

import logging

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.bootstrap.metadata import (
    execute_metadata_source_seed_write,
    prepare_metadata_source_seed_rows,
    prepare_metadata_source_seed_write,
)
from app.core.i18n import DEFAULT_LOCALE
from app.models.common import db_timestamp
from app.models.settings import SystemSetting
from app.modules.metadata.public import BUILTIN_MANIFESTS
from app.modules.mobile.public import (
    SERVER_IDENTITY_SETTING_KEY,
    new_server_identity,
)

LOGGER = logging.getLogger(__name__)

SYSTEM_SETTING_SEEDS: tuple[tuple[str, str], ...] = (
    ("systemName", "二毛图书"),
    ("language", DEFAULT_LOCALE),
)


def seed_baseline_data(db: Session) -> None:
    """Insert missing defaults without changing existing v14 data."""

    now = db_timestamp()
    setting_seeds = (
        *SYSTEM_SETTING_SEEDS,
        (SERVER_IDENTITY_SETTING_KEY, new_server_identity()),
    )
    setting_rows = tuple(
        {
            "key": key,
            "value": value,
            "created_at": now,
            "updated_at": now,
        }
        for key, value in setting_seeds
    )
    setting_statement = (
        sqlite_insert(SystemSetting)
        .values(list(setting_rows))
        .on_conflict_do_nothing(index_elements=[SystemSetting.key])
    )
    provider_rows = prepare_metadata_source_seed_rows(BUILTIN_MANIFESTS)
    provider_write = prepare_metadata_source_seed_write(provider_rows, now=now)
    with db.begin():
        db.execute(setting_statement)
        execute_metadata_source_seed_write(db, provider_write)
    LOGGER.info("database baseline seeds ensured")
