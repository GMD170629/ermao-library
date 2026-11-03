from dataclasses import replace
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.core.authorization import AuthorizationContext
from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibraryReadableResource
from app.modules.library.infrastructure.filter_options import (
    SqlAlchemyLibraryFilterQueries,
)
from tests.integration.modules.library.test_dashboard_query_scaling import (
    _seed_manual_library,
)


def test_filter_options_reuse_one_authorized_covering_aggregate(db_session):
    db = db_session
    _seed_manual_library(db, book_count=5000)
    for i, value in [(0, "PDF"), (1, " pdf "), (2, " ")]:
        db.get(LibraryReadableResource, f"scale-resource-{i:06d}").format = value
    db.get(LibraryReadableResource, "scale-resource-000003").enablement_state = "DISABLED"
    db.get(LibraryReadableResource, "scale-resource-000004").import_state = "FAILED"
    db.commit()
    context = AuthorizationContext("filter-user", True, True, True, (), 1)
    statements = []

    def before(_c, _cursor, sql, parameters, _context, _many):
        statements.append((sql, parameters))

    sa.event.listen(db.get_bind(), "before_cursor_execute", before)
    try:
        options = SqlAlchemyLibraryFilterQueries(db).schema_options(context)
    finally:
        sa.event.remove(db.get_bind(), "before_cursor_execute", before)
    assert [(o.value, o.count) for o in options.formats] == [("EPUB", 4995), ("PDF", 1), ("pdf", 1)]
    assert [(o.value, o.count) for o in options.import_statuses] == [("READY", 4998)]
    resource_queries = [(sql, args) for sql, args in statements if "LibraryReadableResource" in sql]
    assert len(resource_queries) == 1
    sql, args = resource_queries[0]
    plan = db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + sql, args).all()
    assert any("COVERING INDEX LibraryReadableResource_filter_cover_idx" in row[3] for row in plan)
    assert not SqlAlchemyLibraryFilterQueries(db).schema_options(replace(context, is_admin=False, library_ids=())).formats
    allowed = SqlAlchemyLibraryFilterQueries(db).schema_options(replace(context, is_admin=False, library_ids=("test-library",)))
    assert allowed.formats == options.formats
    db.get(Library, "test-library").deletion_requested_at = datetime.now(UTC)
    db.commit()
    assert not SqlAlchemyLibraryFilterQueries(db).schema_options(context).formats


@pytest.mark.parametrize("partial", [False, True])
def test_filter_cover_index_migration_restarts(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "filters.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0053_book_recent_import_page")
        if partial:
            with engine.begin() as c:
                Operations(MigrationContext.configure(c)).create_index(
                    "LibraryReadableResource_filter_cover_idx", "LibraryReadableResource", ["enablementState", "importState", "bookId", "libraryId", "format"]
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert next(i for i in sa.inspect(engine).get_indexes("LibraryReadableResource") if i["name"] == "LibraryReadableResource_filter_cover_idx")["column_names"] == ["enablementState", "importState", "bookId", "libraryId", "format"]
    finally:
        engine.dispose()
