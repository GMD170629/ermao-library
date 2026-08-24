from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

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
