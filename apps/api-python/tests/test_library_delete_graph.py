from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from app.models import (
    DownloadTask,
    KindleSendTask,
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.auth import User, UserLibraryAccess
from app.models.library import Library
from app.models.organize import (
    MetadataLookupTask,
    MetadataProviderExecution,
    MetadataSuggestion,
    MetadataWritebackOperation,
    MetadataWritebackPreparation,
    MetadataWritebackTarget,
    OrganizeJob,
)
from app.modules.imports.infrastructure.library_write import SqlAlchemyLibraryWriteStore
from app.modules.metadata.infrastructure import lookup_queue
from tests.test_library_root_isolation import _book_graph, _login_admin


def seed_delete_graph(db, library_id, *, record_prefix=None):
    """Include both nullable parents and children that cascade on deletion."""
    # Reflect Library so the same graph can exercise historical migrations.
    table = sa.Table("Library", sa.MetaData(), autoload_with=db.connection())
    now = int(datetime.now(UTC).timestamp() * 1000)
    if db.scalar(sa.select(table.c.id).where(table.c.id == library_id)) is None:
        db.execute(table.insert().values(id=library_id, name=library_id,
            rootPath=f"/{library_id}", organizationMode="FLAT", createdAt=now, updatedAt=now))
    db.flush()
    prefix = record_prefix or library_id
    graph = _book_graph(book_id=f"{prefix}-book", library_id=library_id,
                        title=record_prefix or "Book")
    for row in graph:
        db.add(row)
        db.flush()
    node, book, _, _, resource, _, asset = graph
    task = LibraryImportTask(id=f"{prefix}-import", kind="IMPORT_BOOK",
                             library_id=library_id, book_id=book.id,
                             source_node_id=node.id, state="RUNNING",
                             phase="IDENTIFY", book_work="{}")
    db.add(task)
    db.flush()
    job = OrganizeJob(id=f"{prefix}-job", book_id=book.id, resource_id=resource.id,
                      asset_id=asset.id, import_task_id=task.id, trigger="MANUAL",
                      status="RUNNING", issue_codes="[]")
    db.add(job)
    db.flush()
    lookup = MetadataLookupTask(id=f"{prefix}-lookup", book_id=book.id,
                                resource_id=resource.id, asset_id=asset.id,
                                import_task_id=task.id, organize_job_id=job.id,
                                provider_order='["douban"]', status="RUNNING")
    db.add(lookup)
    db.flush()
    operation = MetadataWritebackOperation(
        id=f"{prefix}-operation", book_id=book.id, source_node_id=node.id,
        resource_id=resource.id, asset_id=asset.id, lookup_task_id=lookup.id,
        source="AUTOMATIC")
    db.add(operation)
    db.flush()
    db.add_all([
        MetadataWritebackPreparation(
            id=f"{prefix}-preparation", book_id=book.id, source_node_id=node.id,
            resource_id=resource.id, asset_id=asset.id, lookup_task_id=lookup.id,
            operation_id=operation.id, source="AUTOMATIC",
            idempotency_key=f"{prefix}-intent", source_revision="1",
            snapshot_json='{"title":"Book"}'),
        MetadataWritebackTarget(
            id=f"{prefix}-target", operation_id=operation.id, asset_id=asset.id,
            target_key=f"{prefix}-target", source_path="/book.epub", format="EPUB",
            payload_json='{"title":"Book"}'),
        MetadataProviderExecution(id=f"{prefix}-provider", job_id=job.id,
                                  lookup_task_id=lookup.id, provider_id="douban"),
        MetadataProviderExecution(id=f"{prefix}-job-provider", job_id=job.id,
                                  provider_id="bangumi"),
        MetadataSuggestion(id=f"{prefix}-suggestion", job_id=job.id, field="title",
                           suggested_value="Book", source="douban", reason="match"),
        DownloadTask(id=f"{prefix}-download", book_id=book.id, task_type="http",
                     status="downloaded", display_name="Book"),
        KindleSendTask(id=f"{prefix}-kindle", book_id=book.id,
                       resource_id=resource.id, asset_id=asset.id, book_title="Book",
                       file_name="book.epub", format="EPUB", mime_type="application/epub+zip",
                       recipient_email="reader@example.com", subject="Book", status="sent"),
    ])
    db.commit()


def graph_snapshot(db):
    tables = [sa.Table("Library", sa.MetaData(), autoload_with=db.connection()), *[sa.inspect(model).local_table for model in (
        LibraryBook, LibraryBookMetadata, LibraryReadableResource, LibraryReadableResourceMetadata,
        LibraryResourceAsset, LibrarySourceNode,
        LibraryImportTask, OrganizeJob, MetadataLookupTask, MetadataProviderExecution,
        MetadataSuggestion, MetadataWritebackOperation, MetadataWritebackPreparation,
        MetadataWritebackTarget, DownloadTask, KindleSendTask,
    )]]
    return {table.name: sorted(
        [dict(row) for row in db.execute(sa.select(table)).mappings()],
        key=lambda row: tuple(row[column.name] for column in table.primary_key),
    ) for table in tables}


def row_id(row):
    return str(row.get("id") or row.get("bookId") or row.get("resourceId"))


@pytest.mark.parametrize(("book_count", "batch_size"), [(2, 1), (3, 2)])
def test_cleanup_batch_owns_whole_books_and_resumes_after_rollback(
    db_session, monkeypatch, book_count, batch_size,
):
    from sqlalchemy.orm import Session

    from app.bootstrap.library_cleanup import build_library_cleanup

    monkeypatch.setattr(
        "app.modules.imports.infrastructure.library_cleanup._BOOK_BATCH_SIZE", batch_size,
    )
    for index in range(book_count):
        seed_delete_graph(db_session, "remove", record_prefix=f"remove-{index}")
    seed_delete_graph(db_session, "keep")
    db_session.add(LibraryImportTask(
        id="remove-scan", kind="SCAN_LIBRARY", library_id="remove", state="QUEUED",
    ))
    library = db_session.get(Library, "remove")
    library.deletion_requested_at = datetime.now(UTC)
    library.enabled = False
    db_session.commit()
    before = graph_snapshot(db_session)
    db_session.commit()
    engine = db_session.get_bind()

    # Fail after deleting the selected books, when all their task deletions
    # have also run. None of the partial work may survive the rollback.
    def interrupt_batch(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().startswith('DELETE FROM "LibraryBook" '):
            raise RuntimeError("injected inside book batch")

    sa.event.listen(engine, "after_cursor_execute", interrupt_batch)
    try:
        with Session(engine) as cleanup, pytest.raises(RuntimeError, match="inside book batch"):
            build_library_cleanup(cleanup).execute()
    finally:
        sa.event.remove(engine, "after_cursor_execute", interrupt_batch)
    assert graph_snapshot(db_session) == before
    db_session.commit()

    with Session(engine) as cleanup:
        assert build_library_cleanup(cleanup).execute()
    db_session.expire_all()
    assert db_session.scalar(sa.select(sa.func.count()).select_from(LibraryBook).where(
        LibraryBook.library_id == "remove",
    )) == book_count - batch_size
    assert db_session.get(Library, "remove") is not None
    assert db_session.get(LibraryImportTask, "remove-scan") is not None
    first = graph_snapshot(db_session)
    for table, rows in first.items():
        # A book in the next batch and the other library are wholly untouched.
        untouched = (f"remove-{batch_size}", f"source-remove-{batch_size}", "keep", "source-keep")
        assert [r for r in rows if row_id(r).startswith(untouched)] == [
            r for r in before[table] if row_id(r).startswith(untouched)
        ]
        if table in {"DownloadTask", "KindleSendTask", "LibrarySourceNode"}:
            continue
        assert not any(row_id(r).startswith(tuple(
            f"remove-{index}" for index in range(batch_size)
        )) for r in rows)
    # Each selected book has two provider rows: the book limit must not cap
    # dependent-table deletes and leave part of a selected book behind.
    assert db_session.scalar(sa.select(sa.func.count()).select_from(
        MetadataProviderExecution,
    ).where(MetadataProviderExecution.id.like("remove-%"))) == 2 * (book_count - batch_size)
    db_session.commit()

    # Resume using a new session; the last book batch also removes the library.
    with Session(engine) as cleanup:
        assert build_library_cleanup(cleanup).execute()
    with Session(engine) as cleanup:
        assert not build_library_cleanup(cleanup).execute()
    db_session.expire_all()
    assert db_session.get(Library, "remove") is None
    assert db_session.get(LibraryImportTask, "remove-scan") is None
    assert db_session.get(Library, "keep") is not None
    assert not db_session.connection().exec_driver_sql("PRAGMA foreign_key_check").all()


@pytest.mark.parametrize("failure_stage", ["none", "removal", "cleanup"])
def test_delete_graph_is_scoped_resumable_and_preserves_external_tasks(
    client, db_session, monkeypatch, failure_stage, tmp_path
):
    from sqlalchemy.orm import Session

    from app.bootstrap.library_cleanup import build_library_cleanup
    from app.core.authorization import (
        authorization_context,
        book_visibility_predicate,
        can_access_library,
    )
    from app.modules.imports.infrastructure.library_cleanup import (
        SqlAlchemyLibraryCleanupStore,
    )
    from app.modules.imports.infrastructure.library_queries import (
        get_library,
        list_libraries,
    )

    admin = _login_admin(client, db_session)
    monkeypatch.setattr("app.modules.imports.infrastructure.library_cleanup._BOOK_BATCH_SIZE", 1)
    seed_delete_graph(db_session, "remove")
    seed_delete_graph(db_session, "keep")
    source_file = tmp_path / "Book.epub"
    source_file.write_bytes(b"untouched source")
    db_session.get(Library, "remove").root_path = str(tmp_path)
    db_session.add(UserLibraryAccess(user_id=admin.id, library_id="remove"))
    db_session.commit()
    for table, columns in (
        ("MetadataLookupTask", '"resourceId", "assetId", "importTaskId", "organizeJobId"'),
        ("OrganizeJob", '"resourceId", "assetId", "importTaskId"'),
        ("MetadataWritebackPreparation", '"assetId", "lookupTaskId"'),
        ("MetadataWritebackOperation", '"assetId", "lookupTaskId"'),
        ("MetadataWritebackTarget", '"assetId"'),
    ):
        db_session.connection().exec_driver_sql(
            f'CREATE TRIGGER "reject_rewrite_{table}" BEFORE UPDATE OF {columns} '
            f"ON \"{table}\" BEGIN SELECT RAISE(ABORT, 'redundant nullable update'); END"
        )
    db_session.commit()
    version = db_session.get(User, admin.id).authz_version
    before = graph_snapshot(db_session)
    original_delete = SqlAlchemyLibraryWriteStore.delete

    if failure_stage == "removal":
        def fail_removal(self, prepared):
            original_delete(self, prepared)
            raise RuntimeError("injected before removal commit")
        monkeypatch.setattr(SqlAlchemyLibraryWriteStore, "delete", fail_removal)
        response = client.delete("/api/libraries/remove")
        assert response.status_code == 500
        db_session.expire_all()
        assert graph_snapshot(db_session) == before
        assert db_session.get(User, admin.id).authz_version == version
        return

    response = client.delete("/api/libraries/remove")
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"deleted": True, "id": "remove"}
    db_session.expire_all()
    assert db_session.get(Library, "remove").deletion_requested_at is not None
    assert db_session.get(LibraryBook, "remove-book") is not None
    assert get_library(db_session, "remove") is None
    assert "remove" not in {row["id"] for row in list_libraries(db_session)}
    assert not can_access_library(db_session, admin, "remove")
    context = authorization_context(db_session, admin)
    assert db_session.scalar(sa.select(LibraryBook.id).where(
        LibraryBook.id == "remove-book", book_visibility_predicate(context),
    )) is None
    assert not lookup_queue.lookup_task_is_active(db_session, "remove-lookup")
    from app.modules.imports.infrastructure.readable_resource.task_queue import (
        SqlAlchemyLibraryImportTaskQueue,
    )
    from app.modules.media.infrastructure.resource_repository import (
        SqlAlchemyMediaResourceRepository,
    )
    from app.modules.metadata.infrastructure import writeback_queue
    from app.modules.reader.infrastructure.resource_catalog_repository import (
        SqlAlchemyReaderResourceCatalogRepository,
    )

    imports = SqlAlchemyLibraryImportTaskQueue(db_session)
    assert imports.get_task("remove-import") is None
    assert not imports.book_run_is_current("remove-import", execution_version=1)
    resource_id = db_session.scalar(sa.select(LibraryReadableResource.id).where(
        LibraryReadableResource.library_id == "remove",
    ))
    assert SqlAlchemyReaderResourceCatalogRepository(db_session).get_context(resource_id) is None
    assert SqlAlchemyMediaResourceRepository(db_session).first_resource_asset(resource_id) is None
    with pytest.raises(ValueError, match="书库不存在"):
        writeback_queue.load_metadata_writeback_projection(db_session, book_id="remove-book")
    assert source_file.read_bytes() == b"untouched source"
    assert db_session.get(User, admin.id).authz_version == (version or 1) + 1
    assert client.delete("/api/libraries/remove").status_code == 404
    db_session.commit()

    if failure_stage == "cleanup":
        removed_snapshot = graph_snapshot(db_session)
        db_session.commit()
        original_advance = SqlAlchemyLibraryCleanupStore.advance
        def fail_batch(self):
            original_advance(self)
            raise RuntimeError("injected after cleanup batch")
        with monkeypatch.context() as scoped:
            scoped.setattr(SqlAlchemyLibraryCleanupStore, "advance", fail_batch)
            with Session(db_session.get_bind()) as cleanup, pytest.raises(RuntimeError, match="injected"):
                build_library_cleanup(cleanup).execute()
        assert graph_snapshot(db_session) == removed_snapshot
        db_session.commit()

    # Fresh connections after every committed batch model restart recovery.
    for _ in range(80):
        with Session(db_session.get_bind()) as cleanup:
            if not build_library_cleanup(cleanup).execute():
                break
    else:
        pytest.fail("cleanup did not finish")
    db_session.expire_all()
    after = graph_snapshot(db_session)
    for table, rows in before.items():
        assert [r for r in after[table] if row_id(r).startswith(("keep", "source-keep"))] == [
            r for r in rows if row_id(r).startswith(("keep", "source-keep"))
        ]
        if table not in {"DownloadTask", "KindleSendTask"}:
            assert not any(row_id(r).startswith(("remove", "source-remove")) for r in after[table])
    assert db_session.get(DownloadTask, "remove-download").book_id is None
    kindle = db_session.get(KindleSendTask, "remove-kindle")
    assert (kindle.book_id, kindle.resource_id, kindle.asset_id) == (None, None, None)
    assert kindle.status == "sent"
    assert source_file.read_bytes() == b"untouched source"
    assert not db_session.connection().exec_driver_sql("PRAGMA foreign_key_check").all()


def test_removal_and_inflight_result_writes_are_serialized(db_session):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from dataclasses import replace
    from threading import Event

    from sqlalchemy.orm import Session

    from app.modules.imports.application.library_commands import DeleteLibrary
    from app.modules.imports.infrastructure.readable_resource.task_queue import (
        SqlAlchemyLibraryImportTaskQueue,
    )
    from tests.unit.modules.imports.test_delete_library import _prepared_delete

    seed_delete_graph(db_session, "race")
    assert lookup_queue.lock_book_metadata_write(db_session, "race-book")
    started = Event()
    engine = db_session.get_bind()

    def remove():
        with Session(engine) as db:
            started.set()
            return DeleteLibrary(SqlAlchemyLibraryWriteStore(db), db).execute(
                replace(_prepared_delete(), library_id="race"),
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(remove)
        assert started.wait(2)
        try:
            with pytest.raises(TimeoutError):
                future.result(timeout=0.05)
        finally:
            db_session.commit()
        assert future.result(timeout=5)
    db_session.expire_all()
    assert not lookup_queue.lock_book_metadata_write(db_session, "race-book")
    assert not lookup_queue.lock_active_lookup_task(db_session, "race-lookup")
    queue = SqlAlchemyLibraryImportTaskQueue(db_session)
    assert not queue.lock_task_if_current("race-import")
    assert not queue.book_run_is_current("race-import", execution_version=1)
    from app.modules.imports.application.readable_resource.ports import (
        MissingEntryPolicy,
    )

    with pytest.raises(LookupError):
        queue.request_library_scan("race", missing_entry_policy=MissingEntryPolicy.PRESERVE)
    db_session.rollback()
