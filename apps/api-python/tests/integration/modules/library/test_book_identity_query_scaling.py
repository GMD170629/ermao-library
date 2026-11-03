from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import LibraryBook, LibraryBookMetadata, LibrarySourceNode, User
from app.modules.library.application.book_list import BookListQuery
from app.modules.library.infrastructure.book_list import list_books
from app.modules.library.infrastructure.books import book_ids_statement
from app.modules.reader.infrastructure.v5_library_queries import (
    SqlAlchemyReaderV5LibraryPresentationQueries,
)


@pytest.mark.parametrize("metadata", [False, True])
def test_identity_query_joins_metadata_only_for_used_expressions(metadata):
    predicates = [LibraryBook.visibility_state == "VISIBLE"]
    if metadata:
        predicates.append(LibraryBookMetadata.title == "Title")
    statement = str(book_ids_statement(predicates))
    assert ("LEFT OUTER JOIN" in statement) is metadata
    assert ("LibraryBookMetadata" in statement) is metadata
    ordered = str(book_ids_statement(predicates, [LibraryBookMetadata.title.asc()]))
    assert "LEFT OUTER JOIN" in ordered


def test_book_count_is_metadata_free_and_page_hydration_is_bounded(db_session):
    db = db_session
    now = datetime.now(UTC)
    user = User(
        id="scale-admin",
        email="scale-admin@example.test",
        name="scale",
        role="admin",
        password_hash="test",
    )
    db.add(user)
    for start in range(0, 20_000, 1000):
        db.execute(
            sa.insert(LibrarySourceNode),
            [
                {
                    "id": f"node-{i:06d}",
                    "library_id": "test-library",
                    "name": str(i),
                    "relative_path": str(i),
                    "path_key": "v1:" + f"{i:064x}",
                    "physical_kind": "DIRECTORY",
                    "observed_mtime_ns": 1,
                    "observed_at": now,
                }
                for i in range(start, start + 1000)
            ],
        )
        db.execute(
            sa.insert(LibraryBook),
            [
                {
                    "id": f"book-{i:06d}",
                    "library_id": "test-library",
                    "source_node_id": f"node-{i:06d}",
                    "visibility_state": "VISIBLE",
                    "updated_at": now,
                }
                for i in range(start, start + 1000)
            ],
        )
        db.execute(
            sa.insert(LibraryBookMetadata),
            [
                {
                    "book_id": f"book-{i:06d}",
                    "title": str(i),
                    "normalized_title": str(i),
                    "description": "metadata " * 100,
                }
                for i in range(start, start + 1000)
            ],
        )
    db.commit()
    raw = db.connection().connection.driver_connection
    records = []

    def progress():
        records[-1]["steps"] += 100
        return 0

    def before(_c, _cursor, sql, parameters, _context, _many):
        records.append({"sql": sql, "parameters": parameters, "steps": 0})
        raw.set_progress_handler(progress, 100)

    sa.event.listen(db.get_bind(), "before_cursor_execute", before)
    try:
        result = list_books(
            db,
            user,
            BookListQuery(page=1, requested_page_size=20),
            reader_queries=SqlAlchemyReaderV5LibraryPresentationQueries(db),
        )
    finally:
        raw.set_progress_handler(None, 0)
        sa.event.remove(db.get_bind(), "before_cursor_execute", before)
    assert result.total == 20_000
    assert len(result.books) == 20
    assert [b["id"] for b in result.books] == [
        f"book-{i:06d}" for i in range(19999, 19979, -1)
    ]
    assert "LibraryBookMetadata" not in records[0]["sql"]
    assert "LEFT OUTER JOIN" in records[1]["sql"]
    assert records[1]["steps"] < 30_000
    plan = (
        db.connection()
        .exec_driver_sql(
            "EXPLAIN QUERY PLAN " + records[1]["sql"], records[1]["parameters"]
        )
        .all()
    )
    assert any(
        "LibraryBook_visible_updated_page_idx" in row[3]
        or "LibraryBook_library_updated_page_idx" in row[3]
        for row in plan
    )


@pytest.mark.parametrize("partial", [False, True])
def test_book_identity_indexes_restart(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "book-indexes.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0048_import_task_state_totals")
        if partial:
            with engine.begin() as c:
                Operations(MigrationContext.configure(c)).create_index(
                    "LibraryBook_library_visibility_idx",
                    "LibraryBook",
                    ["libraryId", "visibilityState"],
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        indexes = {i["name"] for i in sa.inspect(engine).get_indexes("LibraryBook")}
        assert {
            "LibraryBook_library_visibility_idx",
            "LibraryBook_library_updated_page_idx",
            "LibraryBook_visible_updated_page_idx",
        } <= indexes
    finally:
        engine.dispose()
