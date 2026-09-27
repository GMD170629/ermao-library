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


def test_exact_candidate_selection_requires_one_title_match_and_can_use_author() -> (
    None
):
    candidates = [
        {"title": "黑暗坡食人树", "author": "岛田庄司", "source": "douban"},
        {"title": "黑暗坡食人树", "author": "其他作者", "source": "bangumi"},
    ]

    from app.services.organize_service import choose_metadata_candidate

    selected, exact = choose_metadata_candidate(
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
        monkeypatch.setattr(queue, "metadata_context_for_book", lambda *args: {"book": {"title": "fixture", "author": ""}})
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


@pytest.mark.parametrize(
    "protected,needs_review,conflicting_author", [(False, False, False), (True, False, False), (False, True, False), (False, False, True)]
)
def test_identity_controls_query_selection_and_unprotected_save(
    db_session, test_settings, monkeypatch, protected, needs_review, conflicting_author
):
    from app.contracts.metadata_identity import MetadataIdentity
    from app.models.organize import OrganizePolicy

    book, resource = _seed_lookup_graph(db_session)
    metadata = db_session.get(LibraryBookMetadata, book.id)
    metadata.title = "混杂错误标题"
    metadata.author = "错误作者"
    metadata.description = "保留的本地简介"
    metadata.protected_fields = '["title", "author"]' if protected else "[]"
    db_session.add(OrganizePolicy(id="identity-policy", prefer_local_metadata=True))
    db_session.commit()
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id, book_id, resource_id = task.id, book.id, resource.id

    def identify(db, **kwargs):
        assert kwargs["title"] == "混杂错误标题"
        assert kwargs["author"] == "错误作者"
        return MetadataIdentity("活着", "余华", needs_review, "test")

    queries = []

    def search(db, context, provider, query, gate):
        queries.append(query)
        assert (
            context["book"]["title"] == "活着" and context["book"]["author"] == "余华"
        )
        return {
            "enabled": True,
            "candidates": [
                {
                    "id": "site",
                    "title": "活着",
                    "author": "作者乙" if conflicting_author else "余华",
                    "description": "远程简介",
                }
            ],
        }

    monkeypatch.setattr(queue, "recognize_metadata_identity", identify)
    monkeypatch.setattr(queue, "_search_provider", search)
    status = queue.process_metadata_lookup_task(
        db_session,
        test_settings,
        {
            "id": task_id,
            "bookId": book_id,
            "resourceId": resource_id,
            "status": "RUNNING",
            "attempts": 0,
            "providerOrder": '["douban"]',
        },
    )
    assert status == ("NO_MATCH" if needs_review else "COMPLETED")
    assert queries == ["活着"]
    db_session.expire_all()
    saved = db_session.get(LibraryBookMetadata, book_id)
    assert (saved.title, saved.author) == (
        ("混杂错误标题", "错误作者") if protected or needs_review else ("活着", "余华")
    )
    assert saved.description == "保留的本地简介"
    if conflicting_author:
        assert db_session.get(MetadataLookupTask, task_id).result_source == "ai"


def test_identity_failure_is_diagnosed_and_retried_without_old_identity(
    db_session, test_settings, monkeypatch, caplog
):
    book, resource = _seed_lookup_graph(db_session)
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    values = {
        "id": task.id,
        "bookId": book.id,
        "resourceId": resource.id,
        "status": "RUNNING",
        "attempts": 0,
    }

    def failed(*args, **kwargs):
        raise ConnectionError("model unavailable")

    def forbidden(*args, **kwargs):
        pytest.fail("Old identity must not be used after model failure")

    monkeypatch.setattr(queue, "recognize_metadata_identity", failed)
    monkeypatch.setattr(queue, "_search_provider", forbidden)
    assert (
        queue.process_metadata_lookup_task(db_session, test_settings, values)
        == "PENDING"
    )
    assert "metadata.identity_failed" in caplog.text
    assert "ConnectionError" in caplog.text


@pytest.mark.parametrize("scenario", ["uncertain", "wrong-A", "review", "source-failure", "protected", "cancelled", "concurrent", "invalid-id"])
def test_queue_semantic_match_runs_after_websites_and_uses_final_identity(db_session, test_settings, monkeypatch, scenario, caplog):
    from io import BytesIO

    from app.models.import_pipeline import Source
    from app.models.organize import OrganizePolicy
    from app.modules.metadata.infrastructure import ai_client
    book, resource = _seed_lookup_graph(db_session)
    metadata = db_session.get(LibraryBookMetadata, book.id)
    metadata.title, metadata.author = "本地错误书名", "本地错误作者"
    metadata.description = None
    metadata.protected_fields = '["title", "author", "description"]' if scenario == "protected" else '[]'
    db_session.add(OrganizePolicy(id="match-policy", prefer_local_metadata=False))
    db_session.add(Source(id="match-ai", name="AI", kind="metadata", provider_type="ai", enabled=True,
                          config=json.dumps({"baseUrl": "http://model.test/v1", "model": "test"})))
    db_session.commit()
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id, book_id, resource_id = task.id, book.id, resource.id
    requests = []
    def search(db, context, provider, query, gate):
        requests.append(provider)
        if scenario == "source-failure" and provider == "douban":
            raise OSError("controlled site outage")
        return {"enabled": True, "candidates": [{"id": "1", "title": "海辺のカフカ", "author": "村上春樹",
                                                  "description": "实际网站简介", "tags": []}]}
    monkeypatch.setattr(queue, "_search_provider", search)
    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"])
        if "candidates" not in prompt:
            result = {"title": "挪威的森林" if scenario == "wrong-A" else "海边的卡夫卡", "author": None,
                      "needsReview": True, "reason": "A uncertain"}
        else:
            assert requests == ["douban", "bangumi"]
            assert all(item["author"] == "村上春樹" for item in prompt["candidates"])
            if scenario == "cancelled":
                db_session.get(MetadataLookupTask, task_id).status = "CANCELLED"
                db_session.commit()
            if scenario == "concurrent":
                current = db_session.get(LibraryBookMetadata, book_id)
                current.title = "用户并发修改"
                current.updated_at = datetime.now(UTC) + timedelta(seconds=1)
                db_session.commit()
            result = {"title": "海边的卡夫卡", "author": "村上春树", "needsReview": scenario == "review", "reason": "B final",
                      "primaryCandidateId": "douban:invented" if scenario == "invalid-id" else "bangumi:1" if scenario == "source-failure" else "douban:1", "relatedCandidateIds": []}
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())
    monkeypatch.setattr(ai_client, "urlopen", model)
    status = queue.process_metadata_lookup_task(db_session, test_settings, {
        "id": task_id, "bookId": book_id, "resourceId": resource_id, "status": "RUNNING", "attempts": 0,
        "providerOrder": '["ai", "douban", "bangumi"]',
    })
    assert requests == ["douban", "bangumi"]
    db_session.expire_all()
    saved = db_session.get(LibraryBookMetadata, book_id)
    if scenario == "invalid-id":
        assert status == "PENDING"
        assert "AI_MATCH_UNKNOWN_CANDIDATE" in caplog.text and "metadata.match_failed" in caplog.text
    if scenario == "source-failure":
        assert "controlled site outage" in caplog.text and "metadata.source_search_failed" in caplog.text
    if scenario in {"review", "cancelled", "concurrent", "invalid-id"}:
        assert status != "COMPLETED"
        assert saved.title == ("用户并发修改" if scenario == "concurrent" else "本地错误书名")
        assert saved.description is None
    elif scenario == "protected":
        assert saved.title == "本地错误书名" and saved.description is None
    else:
        assert status == "COMPLETED"
        assert (saved.title, saved.author, saved.description) == ("海边的卡夫卡", "村上春树", "实际网站简介")
        assert db_session.get(MetadataLookupTask, task_id).result_source == ("bangumi" if scenario == "source-failure" else "douban")


@pytest.mark.parametrize("interruption", [None, "cancelled", "concurrent"])
def test_queue_reads_selected_subject_detail_through_real_provider(db_session, test_settings, monkeypatch, interruption):
    from app.models.organize import OrganizePolicy
    from tests.contract.api.test_metadata_identity import _douban_detail_transport

    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    metadata = db_session.get(LibraryBookMetadata, book_id)
    metadata.title, metadata.author, metadata.description = "错误下载书名", "错误作者", None
    db_session.add(OrganizePolicy(id="detail-policy", prefer_local_metadata=False))
    db_session.commit()
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id = task.id
    def during_detail():
        if interruption == "cancelled":
            db_session.get(MetadataLookupTask, task_id).status = "CANCELLED"
        elif interruption == "concurrent":
            metadata = db_session.get(LibraryBookMetadata, book_id)
            metadata.title = "用户并发标题"
            metadata.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        db_session.commit()
    requests, prompts = _douban_detail_transport(db_session, monkeypatch, before_detail=during_detail)
    class Gate:
        def __init__(self):
            self.providers = []
        def wait(self, provider_id):
            self.providers.append(provider_id)
    gate = Gate()
    status = queue.process_metadata_lookup_task(db_session, test_settings, {
        "id": task_id, "bookId": book_id, "resourceId": resource_id, "status": "RUNNING", "attempts": 0,
        "providerOrder": '["ai", "douban"]',
    }, automatic_request_gate=gate)
    assert (status == "COMPLETED") is (interruption is None)
    assert len(prompts) == 2
    assert len(requests) == 2 and requests[-1] == "http://douban.test/subject/12345/"
    assert gate.providers == ["douban", "douban"]
    db_session.expire_all()
    saved = db_session.get(LibraryBookMetadata, book_id)
    if interruption:
        assert saved.title == ("用户并发标题" if interruption == "concurrent" else "错误下载书名")
        assert saved.description is None
    else:
        assert (saved.title, saved.author, saved.description) == ("海边的卡夫卡", "村上春树", "详情才有的简介")


@pytest.mark.parametrize("scenario", ["normal", "source-failure", "review", "protected", "invalid", "cancelled", "concurrent", "resolved-B", "replace-generated"])
def test_queue_generated_fields_reach_storage_without_manual_locks(db_session, test_settings, monkeypatch, caplog, scenario):
    from io import BytesIO

    from app.models.import_pipeline import Source
    from app.models.organize import MetadataProviderExecution, OrganizePolicy
    from app.modules.metadata.infrastructure import ai_client
    from app.services import organize_service
    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    metadata = db_session.get(LibraryBookMetadata, book_id)
    metadata.title, metadata.author, metadata.description = "活着", "余华", None
    if scenario == "protected": metadata.protected_fields = '["description", "tags"]'
    if scenario == "replace-generated":
        metadata.description, metadata.generated_fields = "旧的生成简介", '["description"]'
    db_session.add(OrganizePolicy(id="generate-policy", prefer_local_metadata=True))
    db_session.add(Source(id="generate-ai", name="AI", kind="metadata", provider_type="ai", enabled=True,
                          config=json.dumps({"baseUrl": "http://model.test", "model": "test", "generateEnabled": True})))
    db_session.add(Source(id="generate-site", name="Bangumi", kind="metadata", provider_type="bangumi", enabled=True,
                          config='{"baseUrl":"http://site.test"}'))
    db_session.commit()
    task = _lookup_task(db_session, book, resource, status="RUNNING");task_id = task.id
    calls = []
    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"]);calls.append(prompt)
        if "missingFields" in prompt:
            if scenario == "cancelled": db_session.get(MetadataLookupTask, task_id).status = "CANCELLED"
            if scenario == "concurrent":
                row = db_session.get(LibraryBookMetadata, book_id);row.description = "用户并发介绍";row.updated_at = datetime.now(UTC) + timedelta(seconds=1)
            db_session.commit()
            result = {"description": "生成的介绍" if "description" in prompt["missingFields"] else None, "tags": ["生成主题"], "needsReview": scenario == "review", "reason": "test"}
            if scenario == "invalid": result["title"] = "禁止字段"
        elif "candidates" in prompt:
            result = {"title": "活着", "author": "余华", "primaryCandidateId": "bangumi:1", "relatedCandidateIds": [], "needsReview": False, "reason": "B resolved"}
        else:
            result = {"title": "活着", "author": None if scenario == "resolved-B" else "余华", "needsReview": scenario == "resolved-B", "reason": "A"}
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())
    def site(request, **kwargs):
        if scenario == "source-failure": raise OSError("controlled site failure")
        data = [{"id": "1", "name_cn": "活着", "infobox": [{"key": "作者", "value": "余华"}], "summary": "真实来源介绍"}] if scenario in {"resolved-B", "replace-generated"} else []
        return BytesIO(json.dumps({"data": data}).encode())
    monkeypatch.setattr(ai_client, "urlopen", model);monkeypatch.setattr(organize_service, "urlopen", site)
    status = queue.process_metadata_lookup_task(db_session, test_settings, {
        "id": task_id, "bookId": book_id, "resourceId": resource_id, "status": "RUNNING", "attempts": 0, "providerOrder": '["ai", "bangumi"]'})
    db_session.expire_all();saved = db_session.get(LibraryBookMetadata, book_id)
    if scenario in {"cancelled", "concurrent"}:
        assert status != "COMPLETED"
        assert saved.description == ("用户并发介绍" if scenario == "concurrent" else None)
        assert saved.generated_fields == '[]'
    elif scenario in {"review", "protected", "invalid"}:
        assert saved.description is None and saved.generated_fields == '[]'
        if scenario == "protected": assert not any("missingFields" in prompt for prompt in calls)
        if scenario == "invalid": assert "metadata.generate_failed" in caplog.text
    else:
        assert status == "COMPLETED"
        assert saved.description == ("真实来源介绍" if scenario in {"resolved-B", "replace-generated"} else "生成的介绍")
        assert json.loads(saved.generated_fields) == (["tags"] if scenario in {"resolved-B", "replace-generated"} else ["description", "tags"])
        assert not set(json.loads(saved.generated_fields)) & set(json.loads(saved.protected_fields))
    if scenario == "resolved-B": assert len(calls) == 3 and calls[-1]["missingFields"] == ["tags"]
    if scenario == "source-failure":
        assert "controlled site failure" in caplog.text
        executions = list(db_session.scalars(select(MetadataProviderExecution).where(MetadataProviderExecution.lookup_task_id == task_id)))
        assert any(row.provider_id == "bangumi" and row.status == "FAILED" for row in executions)
