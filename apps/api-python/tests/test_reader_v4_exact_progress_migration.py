from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import inspect

from app.core.config import Settings
from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine


def test_reader_v4_exact_progress_migration_is_restart_safe_and_reversible(
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0020_comic_page_index"),
        )
        assert "revision" not in {
            column["name"]
            for column in inspect(engine).get_columns("LibraryReadingProgress")
        }

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))
        assert head_revision(engine) == "0021_reader_v4_exact_progress"
        inspector = inspect(engine)
        assert "revision" in {
            column["name"]
            for column in inspector.get_columns("LibraryReadingProgress")
        }
        assert "ReaderProgressMutation" in inspector.get_table_names()
        assert {
            "id",
            "userId",
            "volumeId",
            "mutationId",
            "clientId",
            "revision",
            "locatorJson",
            "contentFingerprint",
            "displayPercent",
            "capturedAt",
            "receivedAt",
        } == {
            column["name"]
            for column in inspector.get_columns("ReaderProgressMutation")
        }

        _run_alembic(
            engine,
            lambda config: command.downgrade(config, "0020_comic_page_index"),
        )
        downgraded = inspect(engine)
        assert "ReaderProgressMutation" not in downgraded.get_table_names()
        assert "revision" not in {
            column["name"]
            for column in downgraded.get_columns("LibraryReadingProgress")
        }

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))
        assert head_revision(engine) == "0021_reader_v4_exact_progress"
    finally:
        engine.dispose()
