from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.seed import seed_baseline_data
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    MetadataLookupTask,
)
from app.models.organize import OrganizeJob
from app.services.metadata_provider_registry import (
    enabled_metadata_provider_ids,
    update_metadata_provider_order,
)
from app.services.organize_scheduler import (
    create_organize_run,
    delete_organize_job,
    get_organize_policy,
    process_organize_schedule_tick,
    recognize_organize_job,
    update_organize_policy,
)


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1] or node_id,
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 1,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _seed_book(
    db_session,
    book_id: str,
    *,
    created_at: datetime | None = None,
    with_resource: bool = True,
) -> tuple[LibraryBook, LibraryReadableResource | None]:
    book_node = _node(f"{book_id}-node", f"{book_id}/", directory=True)
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=book_node.id,
        created_at=created_at or datetime.now(UTC),
    )
    db_session.add_all([book_node, book])
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book.id,
            title=f"Book {book_id}",
            normalized_title=f"book {book_id}",
            author=None,
            normalized_author=None,
            cover_path=None,
        )
    )
    if not with_resource:
        db_session.commit()
        return book, None

    resource_node = _node(f"{book_id}-resource-node", f"{book_id}.epub")
    resource = LibraryReadableResource(
        id=f"{book_id}-resource",
        library_id="test-library",
        book_id=book.id,
        source_node_id=resource_node.id,
        adapter_id="epub",
        adapter_version="1",
        format="EPUB",
        enablement_state="ENABLED",
        import_state="READY",
    )
    db_session.add_all([resource_node, resource])
    db_session.flush()
    db_session.add_all(
        [
            LibraryReadableResourceMetadata(
                resource_id=resource.id,
                title=f"Book {book_id}",
            ),
            LibraryResourceAsset(
                id=f"{book_id}-asset",
                library_id="test-library",
                resource_id=resource.id,
                source_node_id=resource_node.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            ),
        ]
    )
    db_session.flush()
    db_session.commit()
    return book, resource


def test_manual_organize_run_queues_book_resource_lookup_once(db_session) -> None:
    book, resource = _seed_book(db_session, "organize-book")
    assert resource is not None
    assert db_session.scalars(select(OrganizeJob)).all() == []

    run = create_organize_run(db_session, book_ids=[book.id])

    assert run["queuedCount"] == 1
    job = db_session.scalars(
        select(OrganizeJob).where(OrganizeJob.book_id == book.id)
    ).one()
    lookup = db_session.scalars(
        select(MetadataLookupTask).where(MetadataLookupTask.book_id == book.id)
    ).one()
    assert job.resource_id == resource.id
    assert lookup.resource_id == resource.id
    assert lookup.book_id == book.id


def test_empty_book_is_not_queued_until_it_has_a_readable_resource(db_session) -> None:
    book, resource = _seed_book(db_session, "empty-organize-book", with_resource=False)
    assert resource is None

    run = create_organize_run(db_session, book_ids=[book.id])

    assert run["queuedCount"] == 0
    assert (
        db_session.scalars(
            select(OrganizeJob).where(OrganizeJob.book_id == book.id)
        ).all()
        == []
    )


def test_recognition_replaces_unresolved_lookup_with_same_book_resource_scope(
    db_session,
) -> None:
    book, resource = _seed_book(db_session, "recognize-book")
    assert resource is not None
    run = create_organize_run(db_session, book_ids=[book.id])
    assert run["queuedCount"] == 1
    job = db_session.scalars(
        select(OrganizeJob).where(OrganizeJob.book_id == book.id)
    ).one()

    recognized = recognize_organize_job(db_session, job.id)

    assert recognized["bookId"] == book.id
    assert recognized["resourceId"] == resource.id
    assert (
        db_session.scalar(
            select(MetadataLookupTask.id).where(
                MetadataLookupTask.book_id == book.id,
                MetadataLookupTask.resource_id == resource.id,
            )
        )
        is not None
    )


def test_deleting_organize_job_does_not_delete_its_book_or_resource(db_session) -> None:
    book, resource = _seed_book(db_session, "delete-organize-book")
    assert resource is not None
    create_organize_run(db_session, book_ids=[book.id])
    job = db_session.scalars(
        select(OrganizeJob).where(OrganizeJob.book_id == book.id)
    ).one()

    result = delete_organize_job(db_session, job.id)

    assert result == {"id": job.id, "bookId": book.id, "deleted": True}
    assert db_session.get(LibraryBook, book.id) is not None
    assert db_session.get(LibraryReadableResource, resource.id) is not None


def test_metadata_provider_enablement_uses_global_order(db_session) -> None:
    _seed_book(db_session, "provider-book")
    seed_baseline_data(db_session)
    update_metadata_provider_order(
        db_session,
        [
            {"providerId": "douban", "enabled": True},
            {"providerId": "bangumi", "enabled": False},
            {"providerId": "ai", "enabled": False},
        ],
    )

    enabled = enabled_metadata_provider_ids(db_session)

    assert enabled == ["douban"]


def test_interval_schedule_respects_next_run_boundary(db_session) -> None:
    _seed_book(db_session, "scheduled-book")
    seed_baseline_data(db_session)
    update_metadata_provider_order(
        db_session,
        [
            {"providerId": "douban", "enabled": True},
            {"providerId": "bangumi", "enabled": False},
            {"providerId": "ai", "enabled": False},
        ],
    )
    policy = update_organize_policy(
        db_session,
        {
            "enabled": True,
            "scheduleMode": "INTERVAL",
            "intervalMinutes": 15,
        },
    )
    assert policy["scheduleMode"] == "INTERVAL"
    assert get_organize_policy(db_session)["enabled"] is True

    update_organize_policy(
        db_session,
        {"nextRunAt": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
    )
    assert process_organize_schedule_tick(db_session) == 1
    assert db_session.scalar(select(OrganizeJob.id)) is not None
