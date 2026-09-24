"""A pre-Book queue upgrades without losing failures, scans, or old links."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import build_readable_resource_pipeline
from app.core.authorization import AuthorizationContext
from app.core.config import Settings
from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportScanGap,
    LibraryReadableResource,
    LibraryResourceAsset,
)
from app.modules.imports.application.readable_resource.book_work import decode_book_work
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueImportTask,
)
from app.modules.imports.infrastructure.library_queries import (
    get_import_task,
    list_import_tasks_page,
)
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath

_NOW = datetime(2026, 9, 23, tzinfo=UTC)
_REVISION = "0030_book_import_task_shape"


def _insert_legacy_nodes(db: Session, node_ids: tuple[str, ...]) -> None:
    """Seed the columns present at 0030, before scanSeenGeneration existed."""
    db.flush()
    table = sa.Table("LibrarySourceNode", sa.MetaData(), autoload_with=db.get_bind())
    timestamp = int(_NOW.timestamp() * 1000)
    for offset in range(0, len(node_ids), 100):
        db.execute(
            table.insert(),
            [
                {
                    "id": node_id,
                    "libraryId": "library",
                    "relativePath": f"{node_id}.epub",
                    "pathKey": SourceNodeRelativePath(f"{node_id}.epub").path_key,
                    "name": f"{node_id}.epub",
                    "physicalKind": "REGULAR_FILE",
                    "observedSizeBytes": 1,
                    "observedMtimeNs": 1,
                    "observedAt": timestamp,
                    "createdAt": timestamp,
                    "updatedAt": timestamp,
                }
                for node_id in node_ids[offset : offset + 100]
            ],
        )


def _engine(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_sqlite_engine(settings.database_path)


def test_upgrade_merges_old_resource_and_identification_tasks_and_is_reentrant(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    config = alembic_config_for_engine(engine)
    try:
        command.upgrade(config, _REVISION)
        with Session(engine) as db:
            db.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                )
            )
            _insert_legacy_nodes(db, ("one", "two", "three", "orphan"))
            db.flush()
            db.add_all(
                (
                    LibraryBook(
                        id="book-one", library_id="library", source_node_id="one"
                    ),
                    LibraryBook(
                        id="book-two", library_id="library", source_node_id="two"
                    ),
                    LibraryBook(
                        id="book-three", library_id="library", source_node_id="three"
                    ),
                )
            )
            db.flush()
            db.add(
                LibraryResourceAsset(
                    id="asset-one",
                    library_id="library",
                    resource_id="resource-one",
                    source_node_id="one",
                    role="PRIMARY",
                    import_state="READY",
                    processed_source_version="old-version",
                )
            )
            db.add_all(
                (
                    LibraryBookMetadata(
                        book_id="book-one",
                        title="One",
                        normalized_title="one",
                        metadata_pending=True,
                    ),
                    LibraryBookMetadata(
                        book_id="book-two",
                        title="Two",
                        normalized_title="two",
                        metadata_pending=True,
                    ),
                    LibraryBookMetadata(
                        book_id="book-three",
                        title="Three",
                        normalized_title="three",
                        metadata_pending=True,
                    ),
                )
            )
            db.add_all(
                (
                    LibraryReadableResource(
                        id="resource-one",
                        library_id="library",
                        book_id="book-one",
                        source_node_id="one",
                        adapter_id="epub",
                        adapter_version="1",
                        format="EPUB",
                    ),
                    LibraryReadableResource(
                        id="resource-three",
                        library_id="library",
                        book_id="book-three",
                        source_node_id="three",
                        adapter_id="epub",
                        adapter_version="1",
                        format="EPUB",
                    ),
                )
            )
            db.flush()
            legacy_tasks = sa.Table("LibraryImportTask", sa.MetaData(), autoload_with=db.get_bind())
            timestamp = int(_NOW.timestamp() * 1000)
            for values in [
                {"id": "old-resource", "kind": "IMPORT_RESOURCE", "libraryId": "library", "sourceNodeId": "one", "resourceId": "resource-one", "resourceAnchorNodeId": "one", "state": "QUEUED", "createdAt": timestamp},
                {"id": "old-asset", "kind": "IMPORT_ASSET", "libraryId": "library", "sourceNodeId": "one", "resourceId": "resource-one", "role": "PAGE", "state": "FAILED", "errorSummary": "OLD_ASSET_FAILED", "createdAt": timestamp},
                {"id": "old-identify", "kind": "IDENTIFY_BOOK", "libraryId": "library", "sourceNodeId": "one", "state": "FAILED", "errorSummary": "OLD_IDENTIFY_FAILED", "createdAt": timestamp},
                {"id": "old-orphan", "kind": "IDENTIFY_BOOK", "libraryId": "library", "sourceNodeId": "orphan", "state": "QUEUED", "createdAt": timestamp},
                {"id": "old-failed-only", "kind": "IMPORT_RESOURCE", "libraryId": "library", "sourceNodeId": "three", "resourceId": "resource-three", "resourceAnchorNodeId": "three", "state": "FAILED", "errorSummary": "OLD_RESOURCE_FAILED", "createdAt": timestamp},
                {"id": "old-scan", "kind": "SCAN_LIBRARY", "libraryId": "library", "state": "FAILED", "errorSummary": "OLD_SCAN_FAILED", "createdAt": timestamp},
            ]:
                db.execute(legacy_tasks.insert().values(values))
            db.add(
                LibraryImportScanGap(
                    library_id="library",
                    scopes='[{"relativePath":"","recursive":true}]',
                )
            )
            db.commit()

        command.upgrade(config, "head")

        with Session(engine) as db:
            book_tasks = db.scalars(
                select(LibraryImportTask)
                .where(LibraryImportTask.kind == "IMPORT_BOOK")
                .order_by(LibraryImportTask.book_id)
            ).all()
            assert [task.book_id for task in book_tasks] == [
                "book-one",
                "book-three",
                "book-two",
            ]
            first, third, second = book_tasks
            assert first.state == "QUEUED"
            assert second.state == "QUEUED"
            assert third.state == "FAILED"
            assert third.error_summary == "LEGACY_IMPORT_FAILED"
            first_work = decode_book_work(first.book_work or "")
            assert first_work.resource_ids == ("resource-one",)
            assert first_work.identify
            assert decode_book_work(second.book_work or "").identify
            for old_id in ("old-resource", "old-asset", "old-identify"):
                old = db.get(LibraryImportTask, old_id)
                assert old is not None and old.superseded_by_task_id == first.id
            assert db.get(LibraryImportTask, "old-asset").state == "FAILED"  # type: ignore[union-attr]
            assert (
                db.get(LibraryImportTask, "old-identify").error_summary
                == "OLD_IDENTIFY_FAILED"
            )  # type: ignore[union-attr]
            orphan = db.get(LibraryImportTask, "old-orphan")
            assert orphan is not None and orphan.state == "FAILED"
            assert orphan.error_summary == "BOOK_IMPORT_UPGRADE_UNRESOLVED"
            scan = db.get(LibraryImportTask, "old-scan")
            assert scan is not None and scan.state == "FAILED"
            assert db.get(LibraryImportScanGap, "library") is not None
            # Migrated Book work is a first execution; old task links do not run.
            assert SqlAlchemyLibraryImportTaskQueue(db).next_queued() is not None
            context = AuthorizationContext(
                user_id="reader",
                is_admin=True,
                can_manage_system=True,
                can_view_manual_imports=True,
                library_ids=("library",),
                authz_version=1,
            )
            old_link = get_import_task(db, "old-resource", context)
            assert old_link is not None
            assert old_link["id"] == "old-resource"
            assert old_link["kind"] == "IMPORT_RESOURCE"
            assert old_link["bookTitle"] == "One"
            hidden = AuthorizationContext(
                user_id="outsider",
                is_admin=False,
                can_manage_system=False,
                can_view_manual_imports=True,
                library_ids=(),
                authz_version=1,
            )
            assert get_import_task(db, "old-resource", hidden) is None
            assert get_import_task(db, first.id, hidden) is None
            views, total, summary = list_import_tasks_page(
                db, context, page=1, page_size=20
            )
            assert total == 9
            assert "old-resource" in {view["id"] for view in views}
            assert summary == {"queued": 2, "running": 0, "completed": 0, "failed": 7}
            pipeline = build_readable_resource_pipeline(
                db, Settings(storage_root=str(tmp_path / "storage"))
            )
            continued = pipeline.continue_import.execute(
                ContinueImportTask("old-failed-only")
            )
            assert continued.task_id != third.id
            assert continued.enqueued is True
            assert db.get(LibraryImportTask, third.id).state == "FAILED"  # type: ignore[union-attr]
            original_version = db.get(LibraryResourceAsset, "asset-one").processed_source_version
            forced = pipeline.continue_import.execute(
                ContinueImportTask("old-resource", force=True)
            )
            assert forced.task_id != first.id
            assert (
                db.get(LibraryResourceAsset, "asset-one").processed_source_version
                == original_version
            )  # type: ignore[union-attr]
            assert (
                db.get(LibraryImportTask, "old-resource").superseded_by_task_id
                == first.id
            )  # type: ignore[union-attr]
            first_id = first.id
            db.refresh(first)
            first_version = first.request_version
            db.rollback()

        command.upgrade(config, "head")
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.kind == "IMPORT_BOOK")
                )
                == 5
            )
            assert db.get(LibraryImportTask, first_id).request_version == first_version  # type: ignore[union-attr]
    finally:
        engine.dispose()


def test_upgrade_pages_more_than_one_batch_of_pending_books(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    config = alembic_config_for_engine(engine)
    try:
        command.upgrade(config, _REVISION)
        with Session(engine) as db:
            db.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                )
            )
            _insert_legacy_nodes(
                db, tuple(f"node-{index:03d}" for index in range(205))
            )
            db.flush()
            db.add_all(
                LibraryBook(
                    id=f"book-{index:03d}",
                    library_id="library",
                    source_node_id=f"node-{index:03d}",
                )
                for index in range(205)
            )
            db.flush()
            legacy_tasks = sa.Table("LibraryImportTask", sa.MetaData(), autoload_with=db.get_bind())
            db.execute(legacy_tasks.insert(), [
                {"id": f"old-{index:03d}", "kind": "IDENTIFY_BOOK", "libraryId": "library", "sourceNodeId": f"node-{index:03d}", "state": "QUEUED", "createdAt": int(_NOW.timestamp() * 1000)}
                for index in range(205)
            ])
            db.commit()
        command.upgrade(config, "head")
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.kind == "IMPORT_BOOK")
                )
                == 205
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(
                        LibraryImportTask.kind == "IDENTIFY_BOOK",
                        LibraryImportTask.superseded_by_task_id.is_not(None),
                    )
                )
                == 205
            )
    finally:
        engine.dispose()
