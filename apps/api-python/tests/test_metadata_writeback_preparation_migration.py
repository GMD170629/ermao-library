from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.engine.reflection import Inspector

from app.core.config import Settings
from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine


def _column_names(inspector: Inspector, table_name: str) -> set[str]:
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _index_columns(inspector: Inspector, table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        str(index["name"]): tuple(str(name) for name in index["column_names"])
        for index in inspector.get_indexes(table_name)
    }


def test_writeback_preparation_upgrade_is_reversible_and_restart_safe(
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0018_library_facet_index_version"),
        )

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))

        inspector = inspect(engine)
        assert head_revision(engine) == "0021_reader_v4_exact_progress"
        assert {
            "id",
            "operationId",
            "workId",
            "mediaVersionId",
            "volumeId",
            "lookupTaskId",
            "source",
            "idempotencyKey",
            "sourceRevision",
            "snapshotJson",
            "status",
            "attempts",
            "leaseOwnerId",
            "leaseExpiresAt",
            "nextAttemptAt",
            "errorCode",
            "errorSummary",
            "createdAt",
            "updatedAt",
        } == _column_names(inspector, "MetadataWritebackPreparation")
        assert {"leaseOwnerId", "leaseExpiresAt"} <= _column_names(
            inspector, "MetadataLookupTask"
        )
        assert {"leaseOwnerId", "leaseExpiresAt"} <= _column_names(
            inspector, "MetadataWritebackTarget"
        )
        assert "pendingPreparations" in _column_names(
            inspector, "MetadataOpfQueueState"
        )
        assert _index_columns(inspector, "MetadataLookupTask")[
            "MetadataLookupTask_claim_idx"
        ] == ("status", "nextAttemptAt", "leaseExpiresAt", "createdAt")
        assert _index_columns(inspector, "MetadataWritebackTarget")[
            "MetadataWritebackTarget_claim_idx"
        ] == ("status", "nextAttemptAt", "leaseExpiresAt", "createdAt")

        queue_state = sa.Table(
            "MetadataOpfQueueState", sa.MetaData(), autoload_with=engine
        )
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(queue_state.c.pendingPreparations).where(
                        queue_state.c.id == "default"
                    )
                )
                == 0
            )

        _run_alembic(
            engine,
            lambda config: command.downgrade(
                config, "0018_library_facet_index_version"
            ),
        )
        downgraded = inspect(engine)
        assert "MetadataWritebackPreparation" not in downgraded.get_table_names()
        assert "leaseOwnerId" not in _column_names(downgraded, "MetadataLookupTask")
        assert "leaseOwnerId" not in _column_names(
            downgraded, "MetadataWritebackTarget"
        )
        assert "pendingPreparations" not in _column_names(
            downgraded, "MetadataOpfQueueState"
        )

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))
        assert "MetadataWritebackPreparation" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
