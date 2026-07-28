"""Insert immutable baseline rows after schema initialization."""

from __future__ import annotations

import json
import logging

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.i18n import DEFAULT_LOCALE
from app.models.settings import SystemSetting
from app.bootstrap.metadata import ensure_metadata_sources
from app.modules.metadata.public import BUILTIN_MANIFESTS

LOGGER = logging.getLogger(__name__)

SYSTEM_SETTING_SEEDS: tuple[tuple[str, str], ...] = (
    ("systemName", "二毛图书"),
    ("language", DEFAULT_LOCALE),
    (
        "workDetail.tabOrder",
        json.dumps(["EBOOK", "COMIC", "AUDIOBOOK", "STRUCTURE"], ensure_ascii=False),
    ),
)


def seed_baseline_data(db: Session) -> None:
    """Insert missing defaults without changing existing v14 data."""

    with db.begin():
        for key, value in SYSTEM_SETTING_SEEDS:
            statement = (
                sqlite_insert(SystemSetting)
                .values(key=key, value=value)
                .on_conflict_do_nothing(index_elements=[SystemSetting.key])
            )
            db.execute(statement)
        ensure_metadata_sources(db, BUILTIN_MANIFESTS)
    LOGGER.info("database baseline seeds ensured")
