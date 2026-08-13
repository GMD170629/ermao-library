from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import inspect

from app.core.config import Settings
from app.db.runner import _run_alembic, apply_schema, head_revision
from app.db.sqlite import create_sqlite_engine


def test_fresh_database_has_non_unique_publication_hash_lookup(tmp_path: Path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite_engine = create_sqlite_engine(settings.database_path)
    apply_schema(sqlite_engine, settings)

    indexes = {index["name"]: index for index in inspect(sqlite_engine).get_indexes("LibraryFile")}

    assert head_revision(sqlite_engine) == "0023_publication_full_hash_identity"
    assert "LibraryFile_fullHash_key" not in indexes
    assert not indexes["LibraryFile_fullHash_idx"]["unique"]
    sqlite_engine.dispose()


def test_0022_upgrade_removes_only_the_unique_hash_index_and_is_repeat_safe(
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
        before = {
            index["name"]: index
            for index in inspect(engine).get_indexes("LibraryFile")
        }
        assert before["LibraryFile_fullHash_key"]["unique"]

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))
        _run_alembic(engine, lambda config: command.upgrade(config, "head"))

        after = {
            index["name"]: index
            for index in inspect(engine).get_indexes("LibraryFile")
        }
        assert head_revision(engine) == "0023_publication_full_hash_identity"
        assert "LibraryFile_fullHash_key" not in after
        assert not after["LibraryFile_fullHash_idx"]["unique"]
    finally:
        engine.dispose()
