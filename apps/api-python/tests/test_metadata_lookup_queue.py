from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
    MetadataLookupTask,
)
from app.models.organize import OrganizeJob
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.services import metadata_lookup_queue as queue
from app.services.metadata_lookup_queue import (
    process_metadata_lookup_task,
    recover_stale_metadata_lookup_tasks,
)


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1] or node_id,
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 10,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _seed_lookup_graph(db_session) -> tuple[LibraryBook, LibraryReadableResource]:
    book_node = _node("lookup-book-node", "lookup-book", directory=True)
    resource_node = _node("lookup-resource-node", "lookup-book/book.txt")
    book = LibraryBook(
        id="lookup-book",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    resource = LibraryReadableResource(
        id="lookup-resource",
        library_id="test-library",
        book_id=book.id,
        source_node_id=resource_node.id,
        adapter_id="txt",
        adapter_version="1",
        media_kind="EBOOK",
        format="TXT",
        enablement_state="ENABLED",
        import_state="READY",
    )
    db_session.add_all([book_node, resource_node, book])
    db_session.flush()
    db_session.add_all(
        [
            LibraryBookMetadata(
                book_id=book.id,
                title="黑暗坡食人树",
                normalized_title="黑暗坡食人树",
                author="岛田庄司",
                normalized_author="岛田庄司",
            ),
            resource,
        ]
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResourceMetadata(
            resource_id=resource.id,
            title="黑暗坡食人树",
        )
    )
    db_session.commit()
    return book, resource


def _lookup_task(
    db_session,
    book: LibraryBook,
    resource: LibraryReadableResource,
    *,
    task_id: str = "lookup-task",
    status: str = "PENDING",
    import_task_id: str | None = None,
) -> MetadataLookupTask:
    task = MetadataLookupTask(
        id=task_id,
        book_id=book.id,
        resource_id=resource.id,
        import_task_id=import_task_id,
        status=status,
        provider_order=json.dumps(["douban", "bangumi"]),
        attempts=0,
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_lookup_claim_and_stale_recovery_preserve_book_resource_scope(db_session) -> None:
    book, resource = _seed_lookup_graph(db_session)
    task = _lookup_task(db_session, book, resource)

    claimed = queue.claim_next_metadata_lookup_task(db_session, owner_id="worker-a")

    assert claimed is not None
    assert claimed["id"] == task.id
    assert claimed["bookId"] == book.id
    assert claimed["resourceId"] == resource.id
    assert claimed["leaseOwnerId"] == "worker-a"

    db_session.execute(
        update(MetadataLookupTask)
        .where(MetadataLookupTask.id == task.id)
        .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db_session.commit()

    assert recover_stale_metadata_lookup_tasks(db_session) == 1
    recovered = db_session.get(MetadataLookupTask, task.id)
    assert recovered is not None
    assert recovered.status == "PENDING"
    assert recovered.lease_owner_id is None
    assert recovered.resource_id == resource.id


def test_lookup_waits_for_resource_import_and_schedules_retry(
    db_session,
    test_settings,
) -> None:
    book, resource = _seed_lookup_graph(db_session)
    import_task = LibraryImportTask(
        id="lookup-import",
        kind="IMPORT_ASSET",
        library_id="test-library",
        resource_id=resource.id,
        source_node_id=resource.source_node_id,
        role="PRIMARY",
        state="QUEUED",
    )
    db_session.add(import_task)
    db_session.commit()
    task = _lookup_task(
        db_session,
        book,
        resource,
        import_task_id=import_task.id,
        status="RUNNING",
    )

    result = process_metadata_lookup_task(
        db_session,
        test_settings,
        {
            "id": task.id,
            "bookId": book.id,
            "resourceId": resource.id,
            "importTaskId": import_task.id,
            "status": "RUNNING",
            "attempts": 0,
        },
    )

    assert result == "PENDING"
    db_session.expire_all()
    refreshed = db_session.get(MetadataLookupTask, task.id)
    assert refreshed is not None
    assert refreshed.status == "PENDING"
    assert refreshed.attempts == 1
    assert refreshed.next_attempt_at is not None


def test_exact_candidate_selection_requires_one_title_match_and_can_use_author() -> None:
    candidates = [
        {"title": "黑暗坡食人树", "author": "岛田庄司", "source": "douban"},
        {"title": "黑暗坡食人树", "author": "其他作者", "source": "bangumi"},
    ]

    selected, exact = queue._choose_exact_candidate(
        candidates, "黑暗坡食人树", "岛田庄司"
    )

    assert selected == candidates[0]
    assert exact == candidates


def test_cancelled_lookup_cannot_be_reopened_by_a_stale_worker(db_session) -> None:
    book, resource = _seed_lookup_graph(db_session)
    task = _lookup_task(db_session, book, resource, status="CANCELLED")
    task.lease_owner_id = "old-worker"
    task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert recover_stale_metadata_lookup_tasks(db_session) == 0
    assert db_session.scalar(
        select(MetadataLookupTask.status).where(MetadataLookupTask.id == task.id)
    ) == "CANCELLED"
    assert db_session.scalar(
        select(OrganizeJob.id).where(OrganizeJob.book_id == book.id)
    ) is None
