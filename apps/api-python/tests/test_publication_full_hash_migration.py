from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import inspect

from app.core.config import Settings
from app.db.runner import _run_alembic, apply_schema, head_revision
from app.db.sqlite import create_sqlite_engine


def test_fresh_database_has_no_file_content_hash_columns(tmp_path: Path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite_engine = create_sqlite_engine(settings.database_path)
    apply_schema(sqlite_engine, settings)

    inspector = inspect(sqlite_engine)
    library_file_columns = {column["name"] for column in inspector.get_columns("LibraryFile")}
    import_task_columns = {column["name"] for column in inspector.get_columns("ImportTask")}
    conversion_columns = {column["name"] for column in inspector.get_columns("BookConversionTask")}

    assert head_revision(sqlite_engine) == "0030_library_version"
    assert {"fingerprint", "fullHash", "hashStatus"}.isdisjoint(library_file_columns)
    assert "contentHash" not in import_task_columns
    assert "sourceHash" not in conversion_columns
    assert "sourceKey" in conversion_columns
    sqlite_engine.dispose()


def test_0022_upgrade_removes_file_content_hash_columns_and_is_repeat_safe(
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(
                config, "0022_reader_v4_location_morphologies"
            ),
        )
        _run_alembic(engine, lambda config: command.upgrade(config, "head"))
        _run_alembic(engine, lambda config: command.upgrade(config, "head"))

        columns = {column["name"] for column in inspect(engine).get_columns("LibraryFile")}
        assert head_revision(engine) == "0030_library_version"
        assert {"fingerprint", "fullHash", "hashStatus"}.isdisjoint(columns)
    finally:
        engine.dispose()
