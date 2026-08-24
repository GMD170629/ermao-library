from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.organize import (
    MetadataWritebackOperation,
    MetadataWritebackPreparation,
    MetadataWritebackTarget,
)
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.infrastructure import writeback_queue


def _node(
    node_id: str, relative_path: str, *, directory: bool = False
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=relative_path,
        path_key="v1:" + (node_id + relative_path).encode().hex()[:64].ljust(64, "0"),
        name=Path(relative_path).name or node_id,
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 4,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _seed_claim_rows(engine, source: Path) -> None:
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        library = Library(
            id="test-library",
            name="Test Library",
            root_path=str(source.parent),
            organization_mode="FLAT",
        )
        book_node = _node("claim-book-node", "claim-book", directory=True)
        resource_node = _node("claim-resource-node", str(source))
        book = LibraryBook(
            id="claim-book",
            library_id=library.id,
            source_node_id=book_node.id,
        )
        resource = LibraryReadableResource(
            id="claim-resource",
            library_id=library.id,
            book_id=book.id,
            source_node_id=resource_node.id,
            adapter_id="txt",
            adapter_version="1",
            format="TXT",
            enablement_state="ENABLED",
            import_state="READY",
        )
        db.add_all([library, book_node, resource_node, book])
        db.flush()
        db.add_all(
            [
                LibraryBookMetadata(
                    book_id=book.id,
                    title="Claim",
                    normalized_title="claim",
                ),
                resource,
            ]
        )
        db.flush()
        db.add_all(
            [
                LibraryReadableResourceMetadata(
                    resource_id=resource.id,
                    title="Claim resource",
                ),
                LibraryResourceAsset(
                    id="claim-asset",
                    library_id=library.id,
                    resource_id=resource.id,
                    source_node_id=resource_node.id,
                    source_node_physical_kind="REGULAR_FILE",
                    role="PRIMARY",
                    import_state="READY",
                ),
                MetadataWritebackOperation(
                    id="claim-operation",
                    book_id=book.id,
                    source_node_id=resource_node.id,
                    resource_id=resource.id,
                    source="TEST",
                    status="PENDING",
                    total_targets=1,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                MetadataWritebackPreparation(
                    id="claim-preparation",
                    operation_id="claim-operation",
                    book_id=book.id,
                    source_node_id=resource_node.id,
                    resource_id=resource.id,
                    source="TEST",
                    idempotency_key="claim-preparation-key",
                    source_revision="revision",
                    snapshot_json='{"resources": []}',
                    status="PENDING",
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                ),
                MetadataWritebackTarget(
                    id="claim-target",
                    operation_id="claim-operation",
                    asset_id="claim-asset",
                    target_key="claim-target-key",
                    source_path=str(source),
                    format="TXT",
                    payload_json="{}",
                    status="PENDING",
                    attempts=0,
                    written_fields_json="[]",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )


@pytest.mark.parametrize("claim_kind", ["preparation", "target"])
def test_two_workers_atomically_claim_one_writeback_item(
    tmp_path: Path,
    claim_kind: str,
) -> None:
    settings = type("Settings", (), {"database_path": tmp_path / "db.sqlite"})()
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    source = tmp_path / "book.txt"
    source.write_text("book")
    _seed_claim_rows(engine, source)
    barrier = Barrier(2)

    def claim(owner_id: str) -> str | None:
        with Session(engine) as db:
            barrier.wait(timeout=5)
            with MetadataWriteTransaction(db):
                row = (
                    writeback_queue.claim_next_preparation(
                        db, owner_id=owner_id, now=datetime.now(UTC)
                    )
                    if claim_kind == "preparation"
                    else writeback_queue.claim_next_target(
                        db, owner_id=owner_id, now=datetime.now(UTC)
                    )
                )
            return str(row["id"]) if row is not None else None

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ("worker-a", "worker-b")))

        expected_id = (
            "claim-preparation" if claim_kind == "preparation" else "claim-target"
        )
        assert results.count(expected_id) == 1
        assert results.count(None) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("claim_kind", ["preparation", "target"])
def test_writeback_claim_respects_and_recovers_leases(
    tmp_path: Path,
    claim_kind: str,
) -> None:
    settings = type("Settings", (), {"database_path": tmp_path / "db.sqlite"})()
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    source = tmp_path / "book.txt"
    source.write_text("book")
    _seed_claim_rows(engine, source)
    model = (
        MetadataWritebackPreparation
        if claim_kind == "preparation"
        else MetadataWritebackTarget
    )
    claim_next = (
        writeback_queue.claim_next_preparation
        if claim_kind == "preparation"
        else writeback_queue.claim_next_target
    )
    try:
        with Session(engine) as db:
            now = datetime.now(UTC)
            with MetadataWriteTransaction(db):
                first = claim_next(db, owner_id="worker-a", lease_seconds=60, now=now)
            assert first is not None

            with MetadataWriteTransaction(db):
                assert (
                    claim_next(
                        db,
                        owner_id="worker-b",
                        lease_seconds=60,
                        now=datetime.now(UTC),
                    )
                    is None
                )

            with MetadataWriteTransaction(db):
                db.execute(
                    update(model)
                    .where(model.id == str(first["id"]))
                    .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )

            with MetadataWriteTransaction(db):
                recovered = claim_next(
                    db,
                    owner_id="worker-b",
                    lease_seconds=60,
                    now=datetime.now(UTC),
                )

        assert recovered is not None
        assert recovered["id"] == first["id"]
        assert recovered["leaseOwnerId"] == "worker-b"
    finally:
        engine.dispose()
