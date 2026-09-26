from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.common import db_timestamp
from app.models.organize import (
    MetadataOpfQueueState,
    MetadataWritebackOperation,
    MetadataWritebackTarget,
    OrganizePolicy,
)
from app.modules.metadata.application.opf import parse_opf_metadata
from app.modules.metadata.infrastructure.writeback_queue import (
    enqueue_writeback,
    load_metadata_writeback_projection,
    reconcile_queue_state,
)
from app.services import metadata_file_writeback
from app.services.metadata_file_writeback import (
    metadata_writeback_view,
    process_next_metadata_writeback,
)


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=Path(path).name or node_id,
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else Path(path).stat().st_size,
        observed_mtime_ns=Path(path).stat().st_mtime_ns if not directory else 0,
        observed_at=datetime.now(UTC),
    )


def _seed_book_resource(
    db_session,
    source: Path,
    *,
    resource_id: str = "resource-writeback",
    resource_index: float | None = None,
) -> tuple[LibraryBook, LibraryReadableResource, LibraryResourceAsset]:
    book_node = _node("book-writeback-node", "book-writeback", directory=True)
    resource_node = _node("resource-writeback-node", str(source))
    book = LibraryBook(
        id="book-writeback",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    resource = LibraryReadableResource(
        id=resource_id,
        library_id="test-library",
        book_id=book.id,
        source_node_id=resource_node.id,
        adapter_id="txt",
        adapter_version="1",
        format="TXT",
        enablement_state="ENABLED",
        import_state="READY",
    )
    asset = LibraryResourceAsset(
        id=f"asset-{resource_id}",
        library_id="test-library",
        resource_id=resource.id,
        source_node_id=resource_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
    )
    db_session.add_all([book_node, resource_node, book])
    db_session.flush()
    db_session.add_all(
        [
            LibraryBookMetadata(
                book_id=book.id,
                title="快照标题",
                normalized_title="快照标题",
                author="作者",
                normalized_author="作者",
                description="简介",
                # Keep the OPF title unambiguous: the canonical Book title is
                # also the resource title for this text fixture.  The
                # independent series-index field is still exercised below.
                series_name=None,
                series_index=23,
            ),
            resource,
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            LibraryReadableResourceMetadata(
                resource_id=resource.id,
                title="快照标题",
                resource_index=resource_index,
            ),
            asset,
            OrganizePolicy(id="default", write_metadata_to_files=True),
        ]
    )
    db_session.commit()
    return book, resource, asset


def test_writeback_uses_immutable_book_resource_snapshot_after_commit(
    db_session,
    test_settings,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("正文")
    original_source = source.read_bytes()
    original_mtime = source.stat().st_mtime_ns
    book, resource, _asset = _seed_book_resource(db_session, source)

    projection = load_metadata_writeback_projection(
        db_session, book_id=book.id, resource_id=resource.id
    )
    assert projection.resource_ids == (resource.id,)
    queued = enqueue_writeback(
        db_session,
        book_id=book.id,
        resource_id=resource.id,
        source="MANUAL",
    )
    assert queued.operation_id is not None
    db_session.commit()

    metadata = db_session.get(LibraryBookMetadata, book.id)
    assert metadata is not None
    metadata.title = "后续编辑标题"
    db_session.commit()

    assert process_next_metadata_writeback(db_session, test_settings) is True
    assert process_next_metadata_writeback(db_session, test_settings) is True
    opf = parse_opf_metadata(source.with_suffix(".opf").read_bytes())
    assert opf.title == "快照标题"
    assert opf.author == "作者"
    assert source.read_bytes() == original_source
    assert source.stat().st_mtime_ns == original_mtime
    assert metadata_writeback_view(db_session, queued.operation_id) is None


@pytest.mark.parametrize("stage", ["register", "publish", "complete"])
def test_uncertain_writeback_preserves_file_and_durable_ownership(
    db_session, test_settings, tmp_path, monkeypatch, stage
):
    source = tmp_path / "uncertain.txt"
    source.write_text("original")
    book, resource, _ = _seed_book_resource(db_session, source)
    enqueue_writeback(
        db_session, book_id=book.id, resource_id=resource.id, source="MANUAL"
    )
    db_session.commit()
    assert process_next_metadata_writeback(db_session, test_settings)

    def fail(*args, **kwargs):
        raise RuntimeError("injected publication boundary")

    if stage == "register":
        monkeypatch.setattr(metadata_file_writeback, "_mark_target_prepared_uow", fail)
    elif stage == "publish":
        monkeypatch.setattr(
            metadata_file_writeback.file_writeback, "publish_prepared", fail
        )
    else:
        monkeypatch.setattr(metadata_file_writeback, "_complete_target_uow", fail)
    with pytest.raises(RuntimeError, match="WRITEBACK_OUTCOME_REQUIRES_REVIEW"):
        process_next_metadata_writeback(
            db_session, test_settings, owner_id="uncertain-owner"
        )
    target = db_session.scalar(select(MetadataWritebackTarget))
    assert target.status in {"RUNNING", "PREPARED"}
    assert target.lease_owner_id == "uncertain-owner"
    assert source.read_text() == "original"
    if stage == "complete":
        assert source.with_suffix(".opf").exists()
    else:
        assert list(tmp_path.glob(".*.shuku-*.part"))


def test_external_asset_change_is_recorded_without_retry_or_source_rollback(
    db_session,
    test_settings,
    tmp_path: Path,
) -> None:
    source = tmp_path / "changed.txt"
    source.write_text("原正文")
    book, resource, _asset = _seed_book_resource(db_session, source)
    queued = enqueue_writeback(
        db_session,
        book_id=book.id,
        resource_id=resource.id,
        source="AUTOMATIC",
    )
    db_session.commit()

    assert process_next_metadata_writeback(db_session, test_settings) is True
    source.write_text("用户在识别后修改的正文")
    assert process_next_metadata_writeback(db_session, test_settings) is True

    assert metadata_writeback_view(db_session, queued.operation_id) is None
    assert db_session.scalar(select(MetadataWritebackTarget)) is None
    assert source.read_text() == "用户在识别后修改的正文"
    assert not source.with_suffix(".opf").exists()


def test_resource_index_is_serialized_from_the_canonical_resource_projection(
    db_session,
    test_settings,
    tmp_path: Path,
) -> None:
    source = tmp_path / "indexed.txt"
    source.write_text("正文")
    book, resource, _asset = _seed_book_resource(
        db_session, source, resource_id="resource-indexed", resource_index=2
    )
    queued = enqueue_writeback(
        db_session,
        book_id=book.id,
        resource_id=resource.id,
        source="MANUAL",
    )
    db_session.commit()

    assert process_next_metadata_writeback(db_session, test_settings) is True
    assert process_next_metadata_writeback(db_session, test_settings) is True
    opf = parse_opf_metadata(source.with_suffix(".opf").read_bytes())
    assert opf.title == "快照标题"
    assert opf.series_index == 23
    assert queued.operation_id is not None


def test_reconcile_queue_state_counts_durable_resource_targets(db_session) -> None:
    state = MetadataOpfQueueState(id="default", pending_targets=7)
    db_session.add(state)
    db_session.commit()

    assert reconcile_queue_state(db_session, now=db_timestamp()) == 0
    db_session.expire_all()
    reconciled = db_session.get(MetadataOpfQueueState, "default")
    assert reconciled is not None
    assert reconciled.pending_targets == 0
    assert db_session.scalar(select(MetadataWritebackOperation)) is None


def test_confirmed_isbn_google_to_automatic_edition_and_real_opf(client, db_session, test_settings, tmp_path, monkeypatch):
    import io
    import json

    from app.models.organize import MetadataLookupTask
    from app.modules.library.infrastructure import source_node_metadata_recognition
    from app.modules.metadata.domain.providers import BUILTIN_MANIFESTS
    from app.modules.metadata.infrastructure import bibliographic_providers
    from app.modules.metadata.infrastructure.sources import (
        prepare_builtin_provider_seed_rows,
        write_builtin_provider_seed_rows,
    )
    from app.services import metadata_lookup_queue as queue
    from app.services.metadata_provider_registry import (
        update_metadata_provider,
        update_metadata_provider_order,
    )
    from tests.contract.api.test_recognized_metadata_api import _login
    from tests.test_metadata_lookup_queue import _lookup_task

    _login(client, db_session, role="admin")
    original = tmp_path / "confirmed-edition.txt"
    original.write_text("Unchanged original", encoding="utf-8")
    before = (original.read_bytes(), original.stat().st_mtime_ns)
    book, resource, _asset = _seed_book_resource(db_session, original)
    book_id, resource_id = book.id, resource.id
    db_session.get(LibrarySourceNode, book.source_node_id).relative_path = tmp_path.as_posix()
    db_session.get(LibrarySourceNode, resource.source_node_id).relative_path = original.as_posix()
    metadata = db_session.get(LibraryBookMetadata, book_id)
    metadata.metadata_pending = False
    metadata.metadata_state = "COMPLETED"
    db_session.get(OrganizePolicy, "default").write_metadata_to_files = False
    write_builtin_provider_seed_rows(db_session, prepare_builtin_provider_seed_rows(BUILTIN_MANIFESTS))
    db_session.commit()
    update_metadata_provider(db_session, "google-books", {"config": {"apiKey": "fixture-key"}})
    update_metadata_provider_order(db_session, [{"providerId": item.id, "enabled": item.id == "google-books"} for item in BUILTIN_MANIFESTS])
    candidate = {"id": "confirmed-edition", "source": "google-books", "title": "快照标题", "author": "作者",
                 "isbn": "9780306406157", "isbnScope": "EDITION", "matchLevel": "EDITION"}
    with monkeypatch.context() as manual:
        manual.setattr(source_node_metadata_recognition, "search_with_metadata_provider", lambda *args: {"candidates": [candidate]})
        found = client.post(f"/api/books/{book_id}/source-nodes/{resource.source_node_id}/metadata/search",
                            json={"providerId": "google-books", "resourceId": resource_id})
    assert found.status_code == 200, found.text
    result = found.json()["data"]
    applied = client.post(f"/api/books/{book_id}/metadata/apply", json={"scope": "resource", "resourceId": resource_id,
        "recognitionId": result["recognitionId"], "candidate": {"id": candidate["id"], "source": "google-books"}, "fields": ["resource.isbn"]})
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["writebackStatus"] == "notRequested"
    db_session.get(OrganizePolicy, "default").write_metadata_to_files = True
    db_session.commit()
    task = _lookup_task(db_session, db_session.get(LibraryBook, book_id), db_session.get(LibraryReadableResource, resource_id), status="RUNNING")
    task.provider_order = '["google-books"]'
    task.candidate_raw_json = json.dumps({"recognition": {"targetType": "resource", "targetId": resource_id}})
    db_session.commit()
    task_id = task.id
    calls = []
    def google(request, **kwargs):
        assert not db_session.in_transaction()
        assert "isbn%3A9780306406157" in request.full_url
        calls.append(request.full_url)
        return io.BytesIO(json.dumps({"items": [{"id": "confirmed-edition", "volumeInfo": {"title": "快照标题", "authors": ["作者"],
            "industryIdentifiers": [{"type": "ISBN_10", "identifier": "0306406152"}], "publisher": "Verified Edition Press", "publishedDate": "1980-01-02", "language": "zh"}}]}).encode())
    monkeypatch.setattr(bibliographic_providers, "urlopen", google)
    task_input = queue.lookup_persist.lookup_task_to_dict(db_session.get(MetadataLookupTask, task_id))
    assert queue.process_metadata_lookup_task(db_session, test_settings, task_input) == "COMPLETED"
    db_session.expire_all()
    saved = db_session.get(LibraryReadableResourceMetadata, resource_id)
    assert saved.publisher == "Verified Edition Press" and saved.language == "zh"
    assert saved.isbn == "9780306406157" and "isbn" in saved.protected_fields
    assert len(calls) == 1
    stored = json.loads(db_session.get(MetadataLookupTask, task_id).candidate_raw_json)
    assert stored["recognition"]["httpAttempts"] == 1
    assert process_next_metadata_writeback(db_session, test_settings) is True
    assert process_next_metadata_writeback(db_session, test_settings) is True
    opf = parse_opf_metadata(original.with_suffix(".opf").read_bytes())
    assert opf.isbn == "9780306406157" and opf.publisher == "Verified Edition Press"
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before
