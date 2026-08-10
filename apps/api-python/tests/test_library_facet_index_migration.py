from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import command
from sqlalchemy import inspect, select

from app.core.config import Settings
from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine


def test_library_facet_index_upgrade_marks_existing_work_pending(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0017_metadata_opf_queue_state"),
        )
        metadata = sa.MetaData()
        work = sa.Table("LibraryWork", metadata, autoload_with=engine)
        now = datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(
                sa.insert(work).values(
                    id="legacy-facet-work",
                    title="Legacy facet work",
                    normalizedTitle="legacy facet work",
                    tags="[]",
                    createdAt=now,
                    updatedAt=now,
                )
            )

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))

        columns = {
            column["name"] for column in inspect(engine).get_columns("LibraryWork")
        }
        indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspect(engine).get_indexes("LibraryWork")
        }
        upgraded_work = sa.Table("LibraryWork", sa.MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            version = connection.scalar(
                select(upgraded_work.c.facetIndexVersion).where(
                    upgraded_work.c.id == "legacy-facet-work"
                )
            )
        assert head_revision(engine) == "0018_library_facet_index_version"
        assert "facetIndexVersion" in columns
        assert indexes["LibraryWork_facetIndexVersion_id_idx"] == (
            "facetIndexVersion",
            "id",
        )
        assert version == 0
    finally:
        engine.dispose()
