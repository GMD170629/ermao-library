
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import LibraryReadableResource, LibraryResourceAsset
from app.modules.library.infrastructure.books import resource_import_summaries
from tests.integration.modules.library.test_dashboard_query_scaling import (
    _seed_manual_library,
    _sqlite_vm_steps,
)


def test_resource_summary_visits_only_page_books_in_all_import_states(db_session):
    db = db_session
    _seed_manual_library(db, book_count=10_000)
    db.get(LibraryReadableResource, "scale-resource-000000").enablement_state = "DISABLED"
    db.get(LibraryReadableResource, "scale-resource-000001").import_state = "FAILED"
    db.get(LibraryReadableResource, "scale-resource-000002").import_state = "PENDING"
    db.get(LibraryReadableResource, "scale-resource-000003").format = "AUDIOBOOK_DIR"
    db.get(LibraryResourceAsset, "scale-asset-000003").import_state = "FAILED"
    db.commit()
    ids = tuple(f"scale-book-{i:06d}" for i in range(50))
    result, steps = _sqlite_vm_steps(db, lambda: resource_import_summaries(db, ids))
    assert steps < 15_000
    assert result[ids[0]].as_record() == {"ready": 0, "pending": 0, "failed": 0, "failedFiles": 0}
    assert result[ids[1]].failed == 1
    assert result[ids[2]].pending == 1
    assert result[ids[3]].ready == 1 and result[ids[3]].failed_files == 1
    assert all(result[x].ready == 1 for x in ids[4:])
    assert resource_import_summaries(db, ()) == {}


@pytest.mark.parametrize("partial", [False, True])
def test_resource_summary_cover_migration_restarts(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "summary.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0054_resource_filter_cover_index")
        if partial:
            with engine.begin() as c:
                Operations(MigrationContext.configure(c)).create_index(
                    "LibraryReadableResource_book_summary_cover_idx", "LibraryReadableResource",
                    ["enablementState", "bookId", "importState", "format", "id"],
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert next(i for i in sa.inspect(engine).get_indexes("LibraryReadableResource") if i["name"] == "LibraryReadableResource_book_summary_cover_idx")["column_names"] == ["enablementState", "bookId", "importState", "format", "id"]
    finally:
        engine.dispose()
