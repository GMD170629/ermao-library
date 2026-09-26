from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
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
        format="TXT",
        enablement_state="ENABLED",
        import_state="READY",
    )
    db_session.add_all([book_node, resource_node, book])
    db_session.flush()
    db_session.add_all(
        [
            LibraryBookMetadata(
                metadata_pending=False,
                metadata_state="COMPLETED",
                processed_revision=0,
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


def test_lookup_claim_and_stale_recovery_preserve_book_resource_scope(
    db_session,
) -> None:
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


@pytest.mark.parametrize("author,expected", [("其他作者", "REJECTED"), (None, "AMBIGUOUS"), ("岛田庄司", "MATCHED")])
def test_automatic_lookup_uses_identity_decision_without_resource_writes(
    db_session, test_settings, monkeypatch, author, expected
):
    book, resource = _seed_lookup_graph(db_session)
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id, book_id, resource_id = task.id, book.id, resource.id
    calls = []

    def search(db, context, provider, query, gate):
        assert not db.in_transaction()
        calls.append(provider)
        return {"enabled": True, "candidates": [{
            "id": "one", "source": provider, "title": "黑暗坡食人树", "author": author,
            "publisher": "Must not write", "isbn": "9780306406157",
        }]}

    monkeypatch.setattr(queue, "_search_provider", search)
    result = process_metadata_lookup_task(db_session, test_settings, {
        "id": task_id, "bookId": book_id, "resourceId": resource_id,
        "providerOrder": '["douban"]', "status": "RUNNING", "attempts": 0,
    })
    assert result == ("COMPLETED" if expected == "MATCHED" else "NO_MATCH")
    assert calls == ["douban"]
    db_session.expire_all()
    saved = db_session.get(MetadataLookupTask, task_id)
    payload = json.loads(saved.candidate_raw_json)
    attempts = payload["attempted"] if expected == "MATCHED" else payload
    assert attempts[0]["matches"][0]["outcome"] == expected
    assert db_session.get(LibraryReadableResourceMetadata, resource_id).isbn is None
    assert db_session.get(LibraryBookMetadata, book_id).author == "岛田庄司"


def test_aggregate_book_does_not_borrow_representative_resource_isbn(db_session, test_settings, monkeypatch):
    book, resource = _seed_lookup_graph(db_session)
    node = _node("second-node", "lookup-book/volume2.txt")
    db_session.add(node)
    db_session.flush()
    db_session.add(LibraryReadableResource(id="second-resource", library_id="test-library", book_id=book.id, source_node_id=node.id, adapter_id="txt", adapter_version="1", format="TXT", import_state="READY"))
    db_session.get(LibraryReadableResourceMetadata, resource.id).isbn = "9780306406157"
    db_session.commit()
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    monkeypatch.setattr(queue, "_search_provider", lambda *_: {"enabled": True, "candidates": [{"id": "one", "title": "黑暗坡食人树", "author": "岛田庄司", "isbn": "9780306406157"}]})
    monkeypatch.setattr(queue, "_prepare_candidate_application", lambda *_: pytest.fail("aggregate must not apply a single-volume result"))
    assert process_metadata_lookup_task(db_session, test_settings, {"id": task.id, "bookId": book.id, "resourceId": resource.id, "providerOrder": '["douban"]', "attempts": 0}) == "NO_MATCH"


def test_cancelled_lookup_cannot_be_reopened_by_a_stale_worker(db_session) -> None:
    book, resource = _seed_lookup_graph(db_session)
    task = _lookup_task(db_session, book, resource, status="CANCELLED")
    task.lease_owner_id = "old-worker"
    task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert recover_stale_metadata_lookup_tasks(db_session) == 0
    assert (
        db_session.scalar(
            select(MetadataLookupTask.status).where(MetadataLookupTask.id == task.id)
        )
        == "CANCELLED"
    )
    assert (
        db_session.scalar(select(OrganizeJob.id).where(OrganizeJob.book_id == book.id))
        is None
    )


@pytest.mark.parametrize("publish_fails", [False, True])
def test_resource_cover_does_not_block_recognition_of_book_cover(
    db_session, test_settings, monkeypatch, publish_fails
):
    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    metadata = db_session.get(LibraryReadableResourceMetadata, resource_id)
    metadata.cover_path = "covers/resource.png"
    metadata.cover_status = "READY"
    db_session.commit()
    monkeypatch.setattr(
        queue.lookup_persist, "prefer_local_metadata_enabled", lambda db: True
    )
    target = test_settings.resolved_storage_root / "covers" / "recognized.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".part")
    temporary.write_bytes(b"recognized-image")
    remote = queue._PreparedRemoteCover(temporary, target, "covers/recognized.png")
    monkeypatch.setattr(queue, "_download_remote_cover", lambda *args: remote)
    prepared = queue._prepare_candidate_application(
        db_session,
        test_settings,
        {"bookId": book_id, "resourceId": resource_id},
        "test",
        {"coverUrl": "https://example.test/cover.png"},
    )
    assert prepared.book_patch["coverPath"] == "covers/recognized.png"
    assert not any(
        field in prepared.applied
        for field in ("publisher", "language", "isbn", "publishedAt")
    )
    with queue.MetadataWriteTransaction(db_session):
        queue._persist_candidate_application(db_session, prepared)
    if publish_fails:

        def fail_publish(*args):
            raise OSError("test publish failure")

        monkeypatch.setattr(queue.os, "replace", fail_publish)
        with pytest.raises(OSError):
            queue._publish_remote_cover(remote)
        queue._compensate_remote_cover_publish_failure(db_session, prepared)
        assert not target.exists()
        assert not temporary.exists()
        assert db_session.get(LibraryBookMetadata, book_id).cover_path is None
    else:
        queue._publish_remote_cover(remote)
        assert target.read_bytes() == b"recognized-image"
        assert (
            db_session.get(LibraryBookMetadata, book_id).cover_path
            == "covers/recognized.png"
        )
    assert (
        db_session.get(LibraryReadableResourceMetadata, resource_id).cover_path
        == "covers/resource.png"
    )


@pytest.mark.parametrize("reason", ["missing_book", "local_identification", "missing_context", "no_provider"])
def test_observed_lookup_rejection_logs_facts_before_failed_state(db_session, test_settings, monkeypatch, caplog, reason):
    book, resource = _seed_lookup_graph(db_session)
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id, book_id, resource_id = task.id, book.id, resource.id
    if reason == "missing_book":
        monkeypatch.setattr(queue.lookup_persist, "get_book", lambda *args: None)
    elif reason == "local_identification":
        monkeypatch.setattr(queue.lookup_persist, "local_identification_failed", lambda *args: True)
    elif reason == "missing_context":
        monkeypatch.setattr(queue, "metadata_context_for_book", lambda *args: None)
    else:
        monkeypatch.setattr(queue, "metadata_context_for_book", lambda *args: {"title": "fixture"})
        monkeypatch.setattr(queue, "_provider_order", lambda *args: [])
    result = queue.process_metadata_lookup_task(db_session, test_settings, {
        "id": task_id, "bookId": book_id, "resourceId": resource_id,
        "status": "RUNNING", "attempts": 0,
    })
    assert result == ("NO_PROVIDER" if reason == "no_provider" else "FAILED")
    row = db_session.get(MetadataLookupTask, task_id)
    assert row.status == result
    record = next(record for record in caplog.records if "metadata.lookup_rule_failed" in record.message)
    assert record.task_id == task_id
    assert record.book_id == book_id
    assert record.resource_id == resource_id
    assert row.error_summary in record.message
    assert "MetadataLookupRuleFailure" in record.message


def test_import_wait_exhaustion_logs_observed_upstream_state_and_returns_failed(db_session, test_settings, monkeypatch, caplog):
    book, resource = _seed_lookup_graph(db_session)
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id, book_id, resource_id = task.id, book.id, resource.id
    monkeypatch.setattr(queue.lookup_persist, "get_import_task_status", lambda *args: "QUEUED")
    result = queue.process_metadata_lookup_task(db_session, test_settings, {
        "id": task_id, "bookId": book_id, "resourceId": resource_id,
        "importTaskId": "import-task-1", "status": "RUNNING",
        "attempts": len(queue.RETRY_DELAYS_SECONDS),
    })
    assert result == "FAILED"
    assert db_session.get(MetadataLookupTask, task_id).status == "FAILED"
    record = next(record for record in caplog.records if "metadata.lookup_retry_limit_reached" in record.message)
    assert record.task_id == task_id
    assert record.import_task_id == "import-task-1"
    assert "upstream import state=QUEUED" in record.message
    assert "Attempt 4 exhausted 3" in record.message
