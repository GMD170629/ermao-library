"""SystemSetting-backed library scan configuration adapter."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.settings import SystemSetting
from app.modules.imports.application.library_scan_settings import (
    LibraryScanSettingsRepositoryPort,
)
from app.modules.imports.domain.library_scan_schedule import (
    LIBRARY_SCAN_INTERVAL_MINUTES_KEY,
    LIBRARY_SCAN_WATCH_ENABLED_KEY,
    LibraryScanSettings,
    legacy_interval_minutes,
)


class SqlAlchemyLibraryScanSettingsRepository(LibraryScanSettingsRepositoryPort):
    def __init__(
        self, session: Session, *, legacy_interval_ms: int | None = None
    ) -> None:
        self._session = session
        self._legacy_interval_ms = legacy_interval_ms

    def load(self) -> LibraryScanSettings:
        rows = self._session.execute(
            select(SystemSetting.key, SystemSetting.value).where(
                SystemSetting.key.in_(
                    (
                        LIBRARY_SCAN_WATCH_ENABLED_KEY,
                        LIBRARY_SCAN_INTERVAL_MINUTES_KEY,
                    )
                )
            )
        ).all()
        raw = {key: value for key, value in rows}
        stored_watch = self._parse(raw.get(LIBRARY_SCAN_WATCH_ENABLED_KEY))
        stored_interval = self._parse(raw.get(LIBRARY_SCAN_INTERVAL_MINUTES_KEY))
        watch_enabled = stored_watch if isinstance(stored_watch, bool) else True
        interval_minutes = (
            stored_interval
            if isinstance(stored_interval, int)
            and not isinstance(stored_interval, bool)
            else legacy_interval_minutes(self._legacy_interval_ms)
        )
        try:
            return LibraryScanSettings(
                watch_enabled=watch_enabled,
                interval_minutes=interval_minutes,
            )
        except ValueError:
            return LibraryScanSettings(watch_enabled=watch_enabled)

    @staticmethod
    def _parse(raw: str | None) -> object | None:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def save(self, settings: LibraryScanSettings) -> None:
        now = db_timestamp()
        statement = sqlite_insert(SystemSetting)
        upsert = statement.on_conflict_do_update(
            index_elements=[SystemSetting.key],
            set_={
                SystemSetting.value: statement.excluded.value,
                SystemSetting.updated_at: statement.excluded["updatedAt"],
            },
        )
        self._session.execute(
            upsert,
            [
                {
                    "key": LIBRARY_SCAN_WATCH_ENABLED_KEY,
                    "value": json.dumps(settings.watch_enabled),
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "key": LIBRARY_SCAN_INTERVAL_MINUTES_KEY,
                    "value": json.dumps(settings.interval_minutes),
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        self._session.flush()


__all__ = ["SqlAlchemyLibraryScanSettingsRepository"]
