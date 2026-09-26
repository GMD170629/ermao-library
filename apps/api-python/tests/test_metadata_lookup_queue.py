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
from app.models.organize import OrganizeJob, OrganizePolicy
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
    attempts = payload["attempted"]
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


def test_conflicting_candidate_cannot_overwrite_title_when_remote_is_preferred(db_session, test_settings, monkeypatch):
    book, resource = _seed_lookup_graph(db_session)
    metadata = db_session.get(LibraryBookMetadata, book.id)
    metadata.title = "示例书 第1卷"
    metadata.normalized_title = "示例书第1卷"
    db_session.merge(OrganizePolicy(id="default", prefer_local_metadata=False))
    db_session.commit()
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id, book_id, resource_id = task.id, book.id, resource.id
    monkeypatch.setattr(queue, "_search_provider", lambda *_: {"enabled": True, "candidates": [{
        "id": "one", "title": "示例书 第2卷", "volume": "1", "author": "岛田庄司",
    }]})
    result = process_metadata_lookup_task(db_session, test_settings, {
        "id": task_id, "bookId": book_id, "resourceId": resource_id,
        "providerOrder": '["douban"]', "attempts": 0,
    })
    db_session.expire_all()
    assert db_session.get(LibraryBookMetadata, book_id).title == "示例书 第1卷"
    assert result == "NO_MATCH"
    attempted = json.loads(db_session.get(MetadataLookupTask, task_id).candidate_raw_json)["attempted"]
    assert attempted[0]["matches"][0]["outcome"] == "REJECTED"
    assert attempted[0]["matches"][0]["allowedFields"] == []


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
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id = task.id
    prepared = queue._prepare_candidate_application(
        db_session,
        test_settings,
        {"id": task_id, "bookId": book_id, "resourceId": resource_id},
        "test",
        {"id": "cover-candidate", "title": "黑暗坡食人树", "author": "岛田庄司", "matchLevel": "WORK", "coverUrl": "https://example.test/cover.png"},
    )
    assert prepared.changes[0].fields["cover_ref"] == "recognition:" + task_id
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


@pytest.mark.parametrize("writeback_fails", [False, True])
def test_explicit_volume_task_changes_only_selected_resource(db_session, test_settings, monkeypatch, writeback_fails):
    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    db_session.get(LibraryReadableResourceMetadata, resource_id).title = "黑暗坡食人树 第1卷"
    node = _node("volume-two", "lookup-book/volume2.txt")
    db_session.add(node)
    db_session.flush()
    second = LibraryReadableResource(id="volume-two", library_id="test-library", book_id=book_id,
        source_node_id=node.id, adapter_id="txt", adapter_version="1", format="TXT", import_state="READY")
    db_session.add(second)
    db_session.flush()
    db_session.add(LibraryReadableResourceMetadata(resource_id=second.id, title="黑暗坡食人树 第2卷"))
    db_session.commit()
    task = _lookup_task(db_session, book, second, status="RUNNING")
    task.candidate_raw_json = json.dumps({"recognition": {"targetType": "resource", "targetId": second.id}})
    db_session.commit()
    task_id = task.id
    candidate = {"id": "volume-2", "title": "黑暗坡食人树 第2卷", "author": "岛田庄司", "matchLevel": "VOLUME", "description": "Verified volume two"}
    monkeypatch.setattr(queue, "_search_provider", lambda *_: {"enabled": True, "candidates": [candidate]})
    if writeback_fails:
        def failed_writeback(*args, **kwargs):
            raise OSError("opf queue unavailable")
        monkeypatch.setattr(queue, "recognition_writeback", failed_writeback)
    task_input = queue.lookup_persist.lookup_task_to_dict(db_session.get(MetadataLookupTask, task_id))
    task_input["providerOrder"] = '["douban"]'
    result = process_metadata_lookup_task(db_session, test_settings, task_input)
    assert result == "COMPLETED"
    db_session.expire_all()
    changed = db_session.get(LibraryReadableResourceMetadata, "volume-two")
    assert changed.description == "Verified volume two"
    assert "description" not in json.loads(changed.protected_fields)
    assert db_session.get(LibraryReadableResourceMetadata, resource_id).description is None
    assert db_session.get(LibraryBookMetadata, book_id).description is None
    stored = db_session.get(MetadataLookupTask, task_id)
    assert stored.status == "COMPLETED"
    if writeback_fails:
        assert json.loads(stored.candidate_raw_json)["recognition"]["writebackStatus"] == "FAILED"


@pytest.mark.parametrize("failure,code", [
    ("429", "RATE_LIMITED"), ("401", "AUTHENTICATION"),
    ("403", "AUTHENTICATION"), ("restricted", "SOURCE_RESTRICTED"),
    ("parse", "PARSE_ERROR"), ("timeout", "TIMEOUT"),
])
def test_provider_errors_remain_retryable_errors_not_empty_matches(db_session, test_settings, monkeypatch, failure, code):
    from urllib.error import HTTPError

    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    task_id = _lookup_task(db_session, book, resource, status="RUNNING").id
    def source(db, context, provider, query, gate):
        gate.wait(provider)
        if failure.isdigit():
            raise HTTPError("https://provider.example", int(failure), "failure", {}, None)
        if failure == "timeout":
            raise TimeoutError("provider timeout")
        raise ValueError("SOURCE_RESTRICTED" if failure == "restricted" else "invalid source payload")
    monkeypatch.setattr(queue, "_search_provider", source)
    assert process_metadata_lookup_task(db_session, test_settings, {"id": task_id, "bookId": book_id,
        "resourceId": resource_id, "providerOrder": '["douban"]'}) == "PENDING"
    db_session.expire_all()
    stored = db_session.get(MetadataLookupTask, task_id)
    result = json.loads(stored.candidate_raw_json)
    assert result["recognition"]["outcome"] == "SOURCE_ERROR"
    assert result["attempted"][0]["errorCode"] == code
    assert result["recognition"]["httpAttempts"] == 1
    assert stored.next_attempt_at is not None
    assert db_session.get(LibraryBookMetadata, book_id).description is None


@pytest.mark.parametrize("changed", ["parent", "protected", "cancelled", "deleted"])
def test_prepared_recognition_rejects_changed_target(db_session, test_settings, monkeypatch, changed):
    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id = task.id
    db_session.get(LibraryReadableResourceMetadata, resource_id).title += " 第2卷"
    db_session.commit()
    prepared = queue._prepare_candidate_application(db_session, test_settings,
        {"id": task_id, "bookId": book_id, "resourceId": resource_id, "recognition": {"targetType": "resource"}},
        "douban", {"id": "two", "title": "黑暗坡食人树 第2卷", "author": "岛田庄司", "matchLevel": "VOLUME", "description": "New"})
    if changed == "parent":
        db_session.get(LibraryBookMetadata, book_id).author = "Other"
    elif changed == "protected":
        db_session.get(LibraryReadableResourceMetadata, resource_id).protected_fields = '["description"]'
    elif changed == "cancelled":
        db_session.get(MetadataLookupTask, task_id).status = "CANCELLED"
    else:
        db_session.delete(db_session.get(LibraryReadableResource, resource_id))
    db_session.commit()
    with pytest.raises(ValueError, match="RECOGNITION_"), queue.MetadataWriteTransaction(db_session):
        queue._persist_candidate_application(db_session, prepared)
    assert db_session.get(LibraryBookMetadata, book_id).description is None


@pytest.mark.parametrize("repair,prefer_local,known_path,expected", [(False, False, True, False), (True, True, True, False), (True, False, False, False), (True, False, True, True)])
def test_path_repair_requires_persisted_origin_and_both_settings(db_session, test_settings, repair, prefer_local, known_path, expected):
    from app.contracts.local_metadata_snapshot import (
        LocalMetadataObservation,
        encode_observations,
    )
    from app.contracts.publication_metadata import PublicationMetadata
    from app.models import LibraryResourceAsset
    from app.services.organize_scheduler import (
        get_organize_policy,
        update_organize_policy,
    )
    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id, node_id = book.id, resource.id, resource.source_node_id
    current_title = "黑暗坡食人树 第2卷"
    db_session.get(LibraryReadableResourceMetadata, resource_id).title = current_title
    if known_path:
        db_session.add(LibraryResourceAsset(id="path-asset", library_id="test-library", resource_id=resource_id,
            source_node_id=node_id, source_node_physical_kind="REGULAR_FILE", role="PRIMARY", import_state="READY",
            local_metadata_candidates=encode_observations((LocalMetadataObservation("PATH", PublicationMetadata(title=current_title, volume_title=current_title)),))))
    db_session.commit()
    update_organize_policy(db_session, {"allowRepairPathMetadata": repair, "preferLocalMetadata": prefer_local})
    update_organize_policy(db_session, {"enabled": False})
    assert get_organize_policy(db_session)["allowRepairPathMetadata"] == repair
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    prepared = queue._prepare_candidate_application(db_session, test_settings,
        {"id": task.id, "bookId": book_id, "resourceId": resource_id, "recognition": {"targetType": "resource"}},
        "douban", {"id": "v2", "title": "黑暗坡食人树 第02卷", "author": "岛田庄司", "matchLevel": "VOLUME"})
    with queue.MetadataWriteTransaction(db_session):
        queue._persist_candidate_application(db_session, prepared)
    actual = db_session.get(LibraryReadableResourceMetadata, resource_id).title
    assert actual == ("黑暗坡食人树 第02卷" if expected else current_title)


@pytest.mark.parametrize("sample,outcome,status", [
    ("unique-work", "APPLIED", "COMPLETED"),
    ("wrong-author", "NO_MATCH", "NO_MATCH"),
    ("wrong-volume", "NO_MATCH", "NO_MATCH"),
    ("unknown-author", "AMBIGUOUS", "NO_MATCH"),
    ("two-editions", "AMBIGUOUS", "NO_MATCH"),
    ("empty-source", "NO_MATCH", "NO_MATCH"),
])
def test_fixed_acceptance_sample_denominators(db_session, test_settings, monkeypatch, sample, outcome, status):
    # Fixed synthetic set: 6 evaluable targets; 3 contain a correct candidate;
    # 1 safe automatic application; 2 require confirmation. Never production accuracy.
    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    local = db_session.get(LibraryBookMetadata, book_id)
    candidate = {"id": "correct", "title": "黑暗坡食人树", "author": "岛田庄司", "matchLevel": "WORK", "description": "Verified fixture description"}
    if sample == "wrong-author":
        candidate.update(id="wrong", author="Other Author")
    elif sample == "wrong-volume":
        local.title += " 第1卷"
        candidate.update(id="wrong", title="黑暗坡食人树 第2卷", volume="1", matchLevel="VOLUME")
    elif sample == "unknown-author":
        local.author = None
    candidates = [] if sample == "empty-source" else [candidate]
    if sample == "two-editions":
        candidates.append({**candidate, "id": "another-edition"})
    db_session.commit()
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id = task.id
    calls = []
    def source(db, context, provider, query, gate):
        gate.wait(provider)
        calls.append(provider)
        return {"enabled": True, "candidates": candidates}
    monkeypatch.setattr(queue, "_search_provider", source)
    assert process_metadata_lookup_task(db_session, test_settings, {"id": task_id, "bookId": book_id, "resourceId": resource_id, "providerOrder": '["douban"]'}) == status
    db_session.expire_all()
    stored = json.loads(db_session.get(MetadataLookupTask, task_id).candidate_raw_json)
    assert stored["recognition"]["outcome"] == outcome
    assert stored["recognition"]["httpAttempts"] == 1
    assert calls == ["douban"]
    assert db_session.get(LibraryBookMetadata, book_id).description == ("Verified fixture description" if sample == "unique-work" else None)
    assert db_session.get(LibraryReadableResourceMetadata, resource_id).description is None
