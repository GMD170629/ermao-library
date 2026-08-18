from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import LibraryMediaVersion, LibraryWork
from app.models.organize import (
    MetadataWritebackOperation,
    MetadataWritebackPreparation,
    MetadataWritebackTarget,
)
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.infrastructure import writeback_queue
from sqlalchemy import update
from sqlalchemy.orm import Session


def _seed_claim_rows(engine, source: Path) -> None:
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        db.add(
            LibraryWork(
            library_id="test-library", 
                id="claim-work",
                title="Claim",
                normalized_title="claim",
                author="Author",
                normalized_author="author",
                tags="[]",
            )
        )
    with Session(engine) as db, db.begin():
        db.add(
            LibraryMediaVersion(
                id="claim-media",
                work_id="claim-work",
                media_kind="EBOOK",
            )
        )
    with Session(engine) as db, db.begin():
        db.add(
            MetadataWritebackOperation(
                id="claim-operation",
                work_id="claim-work",
                media_version_id="claim-media",
                source="TEST",
                status="PENDING",
                total_targets=1,
            )
        )
    with Session(engine) as db, db.begin():
        db.add_all(
            [
                MetadataWritebackPreparation(
                    id="claim-preparation",
                    operation_id="claim-operation",
                    work_id="claim-work",
                    media_version_id="claim-media",
                    source="TEST",
                    idempotency_key="claim-preparation-key",
                    source_revision="revision",
                    snapshot_json='{"volumes": []}',
                    status="PENDING",
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                ),
                MetadataWritebackTarget(
                    id="claim-target",
                    operation_id="claim-operation",
                    target_key="claim-target-key",
                    source_path=str(source),
                    format="EPUB",
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
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    source = tmp_path / "book.epub"
    source.write_bytes(b"book")
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
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    source = tmp_path / "book.epub"
    source.write_bytes(b"book")
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
                first = claim_next(
                    db, owner_id="worker-a", lease_seconds=60, now=now
                )
            assert first is not None

            now = datetime.now(UTC)
            with MetadataWriteTransaction(db):
                assert (
                    claim_next(
                        db, owner_id="worker-b", lease_seconds=60, now=now
                    )
                    is None
                )

            with MetadataWriteTransaction(db):
                db.execute(
                    update(model)
                    .where(model.id == str(first["id"]))
                    .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )

            now = datetime.now(UTC)
            with MetadataWriteTransaction(db):
                recovered = claim_next(
                    db, owner_id="worker-b", lease_seconds=60, now=now
                )

        assert recovered is not None
        assert recovered["id"] == first["id"]
        assert recovered["leaseOwnerId"] == "worker-b"
    finally:
        engine.dispose()
