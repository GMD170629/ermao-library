"""The default-cover reset migration clears stale bundled cover references."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from app.db.runner import alembic_config_for_engine

_PREVIOUS_REVISION = "0016_library_sort_order"
_DEFAULT_COVER = "covers/default-book-cover-v1.png"
_REAL_COVER = "covers/books/real.png"
_UPDATED_AT = 1_700_000_000_000


def _engine(path: Path):
    # Foreign keys stay off so the migration can be exercised without building
    # the full library topology; the tested statement only touches these tables.
    return sa.create_engine(f"sqlite+pysqlite:///{path}")


def _table(name: str, *columns: str) -> sa.TableClause:
    return sa.table(name, *(sa.column(column, sa.Text) for column in columns))


def _metadata_tables() -> tuple[sa.TableClause, sa.TableClause, sa.TableClause]:
    return (
        _table(
            "LibraryBookMetadata",
            "bookId",
            "title",
            "normalizedTitle",
            "coverPath",
            "coverStatus",
            "updatedAt",
        ),
        _table(
            "LibraryReadableResourceMetadata",
            "resourceId",
            "title",
            "coverPath",
            "coverStatus",
            "updatedAt",
        ),
        _table(
            "LibrarySourceNodeMetadata",
            "sourceNodeId",
            "coverPath",
            "coverStatus",
            "updatedAt",
        ),
    )


def _cover_state(
    connection, table, id_column: str, row_id: str
) -> tuple[object, object]:
    row = connection.execute(
        sa.select(table.c.coverPath, table.c.coverStatus).where(
            table.c[id_column] == row_id
        )
    ).one()
    return row.coverPath, row.coverStatus


def test_upgrade_resets_only_bundled_default_cover_rows(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "shuku.sqlite3")
    config = alembic_config_for_engine(engine)
    command.upgrade(config, _PREVIOUS_REVISION)

    book_metadata, resource_metadata, source_metadata = _metadata_tables()
    asset = _table(
        "LibraryResourceAsset",
        "id",
        "libraryId",
        "resourceId",
        "sourceNodeId",
        "role",
        "localCoverPath",
        "updatedAt",
    )
    with engine.begin() as connection:
        connection.execute(
            sa.insert(book_metadata),
            [
                {
                    "bookId": "book-stale",
                    "title": "Stale",
                    "normalizedTitle": "stale",
                    "coverPath": _DEFAULT_COVER,
                    "coverStatus": "READY",
                    "updatedAt": _UPDATED_AT,
                },
                {
                    "bookId": "book-real",
                    "title": "Real",
                    "normalizedTitle": "real",
                    "coverPath": _REAL_COVER,
                    "coverStatus": "READY",
                    "updatedAt": _UPDATED_AT,
                },
            ],
        )
        connection.execute(
            sa.insert(resource_metadata),
            [
                {
                    "resourceId": "resource-stale",
                    "title": "Stale",
                    "coverPath": _DEFAULT_COVER,
                    "coverStatus": "READY",
                    "updatedAt": _UPDATED_AT,
                },
            ],
        )
        connection.execute(
            sa.insert(source_metadata),
            [
                {
                    "sourceNodeId": "node-stale",
                    "coverPath": _DEFAULT_COVER,
                    "coverStatus": "READY",
                    "updatedAt": _UPDATED_AT,
                },
            ],
        )
        connection.execute(
            sa.insert(asset),
            [
                {
                    "id": "asset-stale",
                    "libraryId": "library",
                    "resourceId": "resource-stale",
                    "sourceNodeId": "node-stale",
                    "role": "PRIMARY",
                    "localCoverPath": _DEFAULT_COVER,
                    "updatedAt": _UPDATED_AT,
                },
            ],
        )

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert _cover_state(connection, book_metadata, "bookId", "book-stale") == (
            None,
            "PENDING",
        )
        assert _cover_state(connection, book_metadata, "bookId", "book-real") == (
            _REAL_COVER,
            "READY",
        )
        assert _cover_state(
            connection, resource_metadata, "resourceId", "resource-stale"
        ) == (None, "PENDING")
        assert _cover_state(
            connection, source_metadata, "sourceNodeId", "node-stale"
        ) == (None, "PENDING")
        assert (
            connection.execute(
                sa.select(asset.c.localCoverPath).where(asset.c.id == "asset-stale")
            ).scalar_one()
            is None
        )
