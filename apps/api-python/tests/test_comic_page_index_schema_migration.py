from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import inspect

from app.core.config import Settings
from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine


def test_comic_page_index_version_upgrade_is_restart_safe_and_reversible(
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0019_writeback_preparation"),
        )
        assert "pageIndexVersion" not in {
            column["name"] for column in inspect(engine).get_columns("LibraryFile")
        }

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))
        inspector = inspect(engine)
        columns = {
            column["name"]: column for column in inspector.get_columns("LibraryFile")
        }
        indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("LibraryFile")
        }
        assert head_revision(engine) == "0021_reader_v4_exact_progress"
        assert columns["pageIndexVersion"]["nullable"] is False
        assert str(columns["pageIndexVersion"]["default"]).strip("'\"") == "0"
        assert indexes["LibraryFile_kind_pageIndexVersion_id_idx"] == (
            "kind",
            "pageIndexVersion",
            "id",
        )

        _run_alembic(
            engine,
            lambda config: command.downgrade(
                config,
                "0019_writeback_preparation",
            ),
        )
        assert "pageIndexVersion" not in {
            column["name"] for column in inspect(engine).get_columns("LibraryFile")
        }

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))
        assert head_revision(engine) == "0021_reader_v4_exact_progress"
    finally:
        engine.dispose()
