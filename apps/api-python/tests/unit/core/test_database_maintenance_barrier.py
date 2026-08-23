from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.maintenance import (
    DatabaseMaintenanceLockTimeout,
    database_restore_barrier,
    database_restore_connection,
)
from app.db.sqlite import create_sqlite_engine
from app.models.settings import SystemSetting


def test_restore_barrier_waits_for_writers_and_keeps_reads_available(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "maintenance.sqlite3"
    engine = create_sqlite_engine(database_path, timeout_seconds=0.05)
    SystemSetting.__table__.create(engine)
    with Session(engine) as seed:
        seed.add(SystemSetting(key="systemName", value="Shuku"))
        seed.commit()

    existing_writer = Session(engine)
    try:
        existing_writer.execute(
            update(SystemSetting)
            .where(SystemSetting.key == "systemName")
            .values(value="writer active")
        )
        with (
            pytest.raises(DatabaseMaintenanceLockTimeout),
            database_restore_barrier(database_path, timeout_seconds=0.05),
        ):
            raise AssertionError("exclusive barrier must not be entered")
    finally:
        existing_writer.rollback()
        existing_writer.close()

    with database_restore_barrier(database_path, timeout_seconds=0.05):
        with Session(engine) as reader:
            assert (
                reader.scalar(
                    select(SystemSetting.value).where(SystemSetting.key == "systemName")
                )
                == "Shuku"
            )

        with (
            Session(engine) as blocked_writer,
            pytest.raises(DatabaseMaintenanceLockTimeout),
        ):
            blocked_writer.execute(
                update(SystemSetting)
                .where(SystemSetting.key == "systemName")
                .values(value="must not write")
            )

        with Session(engine) as restore:
            connection = restore.connection()
            with database_restore_connection(connection):
                restore.execute(
                    update(SystemSetting)
                    .where(SystemSetting.key == "systemName")
                    .values(value="restored")
                )
                restore.commit()

    with Session(engine) as verify:
        assert (
            verify.scalar(
                select(SystemSetting.value).where(SystemSetting.key == "systemName")
            )
            == "restored"
        )
    engine.dispose()
