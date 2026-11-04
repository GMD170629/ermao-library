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
from app.modules.library.application.filter_ast import FilterCondition, FilterExpression
from app.modules.library.infrastructure.book_list import list_books
from app.modules.library.infrastructure.book_search import (
    book_matches_search,
    matching_search_book_ids,
)
from app.modules.library.infrastructure.books import book_ids_statement
from app.modules.reader.infrastructure.v5_library_queries import (
    SqlAlchemyReaderV5LibraryPresentationQueries,
)
from tests.integration.modules.library.test_dashboard_query_scaling import (
    _seed_manual_library,
    _sqlite_vm_steps,
)


@pytest.mark.parametrize("sort", ["title", "recent_read"])
def test_missing_substring_uses_index_without_catalog_scan(db_session, sort):
    db = db_session
    _seed_manual_library(db, book_count=5000)
    user = User(id="empty-search", email="empty@example.test", name="Empty", role="admin", password_hash="test")
    db.add(user)
    db.commit()
    db.connection().exec_driver_sql("ANALYZE")
    result, steps = _sqlite_vm_steps(db, lambda: list_books(
        db, user, BookListQuery(1, 20, search="NASPERF-flac-", sort=sort, projection="import-status"),
        reader_queries=SqlAlchemyReaderV5LibraryPresentationQueries(db),
    ))
    assert result.total == 0 and result.books == []
    assert steps < 5000, steps


def test_substring_index_preserves_like_unicode_null_and_wildcard_semantics(db_session):
    db = db_session
    samples = ["ASCII ABC", "École café", "中文阅读器💡", "Straße", "a%b_c", "Other"]
    _seed_manual_library(db, book_count=len(samples))
    for index, title in enumerate(samples):
        metadata = db.get(LibraryBookMetadata, f"scale-book-{index:06d}")
        metadata.title = title
        metadata.author = "Writer ABC" if index == 1 else None
        metadata.series_name = "Series 中文" if index == 2 else None
        metadata.description = "Description abc" if index == 3 else None
    db.commit()
    for term in ["ABC", "école", "café", "阅读器", "中文", "💡", "straße", "strasse", "%b_c", "a%b", "_", "%%", "abc\0"]:
        term = term.casefold()
        pattern = f"%{term}%"
        expected = set(db.scalars(sa.select(LibraryBookMetadata.book_id).where(sa.or_(
            sa.func.lower(LibraryBookMetadata.title).like(pattern),
            *(sa.func.lower(sa.func.coalesce(field, "")).like(pattern) for field in (
                LibraryBookMetadata.author, LibraryBookMetadata.series_name, LibraryBookMetadata.description,
            )),
        ))))
        assert set(db.scalars(matching_search_book_ids(term))) == expected, term
        assert set(db.scalars(sa.select(LibraryBook.id).where(book_matches_search(LibraryBook.id, term)))) == expected, term
    metadata = db.get(LibraryBookMetadata, "scale-book-000000")
    metadata.title = "replacement unique"
    db.flush()
    assert set(db.scalars(matching_search_book_ids("replacement"))) == {metadata.book_id}
    db.rollback()
    assert not list(db.scalars(matching_search_book_ids("replacement")))
    db.delete(db.get(LibraryBookMetadata, "scale-book-000001"))
    db.commit()
    assert not list(db.scalars(matching_search_book_ids("writer")))


@pytest.mark.parametrize("partial", [False, True])
def test_substring_index_migration_backfills_and_restarts(tmp_path, partial):
    from sqlalchemy.orm import Session
    engine = create_sqlite_engine(tmp_path / "substring.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0056_resource_identity_cover")
        from app.models import Library
        with Session(engine) as db:
            db.add(Library(id="test-library", name="Test", root_path="/test", organization_mode="FLAT"))
            db.commit()
            _seed_manual_library(db, book_count=2)
        if partial:
            with engine.begin() as connection:
                connection.execute(sa.DDL('CREATE VIRTUAL TABLE "LibraryBookSearch" USING fts5("bookId" UNINDEXED, title, author, "seriesName", description, tokenize=trigram, detail=none)'))
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with Session(engine) as db:
            assert len(list(db.scalars(matching_search_book_ids("scale")) )) == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize("direction", ["asc", "desc"])
@pytest.mark.parametrize("sort", ["title", "recent_import", "updated"])
def test_filtered_pages_preserve_missing_metadata_ties_and_exact_totals(db_session, direction, sort):
    db = db_session
    _seed_manual_library(db, book_count=80)
    user = User(id="title-user", email="title@example.test", name="Title", role="admin", password_hash="test")
    db.add(user)
    for index in (0, 1):
        db.delete(db.get(LibraryBookMetadata, f"scale-book-{index:06d}"))
    for index in (2, 3):
        db.get(LibraryBookMetadata, f"scale-book-{index:06d}").title = "duplicate"
    db.get(LibraryBook, "scale-book-000004").visibility_state = "HIDDEN"
    db.commit()
    key = LibraryBookMetadata.title if sort == "title" else (LibraryBook.created_at if sort == "recent_import" else LibraryBook.updated_at)
    order = key.desc() if direction == "desc" else key.asc()
    tie = LibraryBook.id.desc() if sort != "title" and direction == "desc" else LibraryBook.id.asc()
    expected = list(db.scalars(sa.select(LibraryBook.id).outerjoin(
        LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id,
    ).where(LibraryBook.visibility_state == "VISIBLE").order_by(order, tie)))
    reader = SqlAlchemyReaderV5LibraryPresentationQueries(db)
    for page, size in [(1, 20), (2, 20), (4, 20), (99, 20), (1, 100), (1, None), (2, None)]:
        result = list_books(db, user, BookListQuery(page, size, sort=sort, sort_direction=direction, projection="import-status", filter_expression=FilterExpression("ALL", (FilterCondition("library", "equals", "test-library"),))), reader_queries=reader)
        actual_size = size or len(expected)
        assert result.total == 79
        assert [x["id"] for x in result.books] == expected[(page - 1) * actual_size:page * actual_size]


@pytest.mark.parametrize("match_count", [1, 10, 5000])
@pytest.mark.parametrize("sort", ["updated", "recent_import", "title"])
def test_metadata_search_is_a_covering_scan_not_per_book_heap_lookups(db_session, match_count, sort):
    db = db_session
    now = datetime.now(UTC)
    user = User(
        id="search-admin",
        email="search-admin@example.test",
        name="search",
        role="admin",
        password_hash="test",
    )
    db.add(user)
    for start in range(0, 5000, 1000):
        db.execute(
            sa.insert(LibrarySourceNode),
            [
                {
                    "id": f"source-{i}",
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
                    "id": f"book-{i}",
                    "library_id": "test-library",
                    "source_node_id": f"source-{i}",
                }
                for i in range(start, start + 1000)
            ],
        )
        db.execute(
            sa.insert(LibraryBookMetadata),
            [
                {
                    "book_id": f"book-{i}",
                    "title": f"NASPERF {i}" if i < match_count else f"Other {i}",
                    "normalized_title": str(i),
                    "description": "metadata " * 100,
                }
                for i in range(start, start + 1000)
            ],
        )
    db.commit()
    reader = SqlAlchemyReaderV5LibraryPresentationQueries(db)
    statements = []

    def before(_c, _cursor, sql, parameters, _context, _many):
        statements.append((sql, parameters))

    sa.event.listen(db.get_bind(), "before_cursor_execute", before)
    try:
        positive = list_books(
            db,
            user,
            BookListQuery(
                page=1,
                requested_page_size=10,
                search="NASPERF",
                sort=sort,
                projection="import-status",
            ),
            reader_queries=reader,
        )
        count_statement = statements[0]
        hydration_statement = statements[1]
        statements.clear()
        negative = list_books(
            db,
            user,
            BookListQuery(
                page=1,
                requested_page_size=10,
                search="no-such-NASPERF",
                projection="import-status",
            ),
            reader_queries=reader,
        )
    finally:
        sa.event.remove(db.get_bind(), "before_cursor_execute", before)
    assert positive.total == match_count and len(positive.books) == min(match_count, 10)
    assert negative.total == 0 and negative.books == []
    assert len(statements) == 1
    assert 'LEFT OUTER JOIN "LibraryBookMetadata"' not in count_statement[0]
    plan = (
        db.connection()
        .exec_driver_sql("EXPLAIN QUERY PLAN " + count_statement[0], count_statement[1])
        .all()
    )
    assert sum("LibraryBookSearch VIRTUAL TABLE INDEX" in r[3] and "L" in r[3] for r in plan) == 4, plan
    assert not any("SCAN LibraryBookMetadata" in r[3] for r in plan)
    assert all("COVERING INDEX" in r[3] for r in plan if "SEARCH LibraryBookMetadata" in r[3])
    if match_count <= 10:
        hydration_plan = db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + hydration_statement[0], hydration_statement[1]).all()
        assert "authorized_selected_books" in hydration_statement[0]
        assert any("COVERING INDEX LibraryBook_identity_scope_cover_idx (id>? AND id<?)" in r[3] for r in hydration_plan), hydration_plan
        assert not any("LibraryBook_visible_imported_page_idx" in r[3] or "LibraryBook_visible_updated_page_idx" in r[3] for r in hydration_plan)

    nested = book_ids_statement(
        [LibraryBook.id.in_(sa.select(LibraryBookMetadata.book_id))]
    )
    assert "LEFT OUTER JOIN" not in str(nested)


@pytest.mark.parametrize("partial", [False, True])
def test_search_cover_index_restart(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "search.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0050_book_import_status_page")
        if partial:
            with engine.begin() as c:
                Operations(MigrationContext.configure(c)).create_index(
                    "LibraryBookMetadata_search_cover_idx",
                    "LibraryBookMetadata",
                    ["bookId", "title", "author", "seriesName", "description"],
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert next(
            i
            for i in sa.inspect(engine).get_indexes("LibraryBookMetadata")
            if i["name"] == "LibraryBookMetadata_search_cover_idx"
        )["column_names"] == ["bookId", "title", "author", "seriesName", "description"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("partial", [0, 1, 2])
def test_candidate_cover_migration_preserves_restart_and_columns(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "covers.sqlite3")
    indexes = [
        ("LibraryBook_identity_scope_cover_idx", "LibraryBook", ["id", "visibilityState", "libraryId"]),
        ("LibraryBookMetadata_identity_title_cover_idx", "LibraryBookMetadata", ["bookId", "title"]),
    ]
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0057_book_substring_search")
        with engine.begin() as connection:
            for name, table, columns in indexes[:partial]:
                Operations(MigrationContext.configure(connection)).create_index(name, table, columns)
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        for name, table, columns in indexes:
            assert next(i for i in sa.inspect(engine).get_indexes(table) if i["name"] == name)["column_names"] == columns
    finally:
        engine.dispose()
