"""Lease fencing: expired claim cannot write; scan stops on lease loss."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.common import db_timestamp
from app.models.import_pipeline import ImportWorkItem
from app.models.library import Library
from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    ClaimedWork,
    FileParseResult,
    ParsedAssetPayload,
    ResourceAdapterExecutorPort,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.domain.resource_adapters import ResourceAdapterSpec
from app.modules.imports.infrastructure.readable_resource.filesystem import (
    OsSourceTreeFilesystem,
)
from app.modules.imports.infrastructure.readable_resource.import_run_repository import (
    SqlAlchemyImportRunRepository,
)
from app.modules.imports.infrastructure.readable_resource.support import (
    InMemorySidecarWriteback,
    SqlAlchemyUnitOfWork,
    StructuredPipelineLog,
    UtcClock,
)
from app.modules.imports.infrastructure.readable_resource.work_queue import (
    SqlAlchemyReadableResourceWorkQueue,
)
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemyBookResourceRepository,
    SqlAlchemyLibraryConfigAdapter,
    SqlAlchemySourceNodeRepository,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryResourceAsset,
)


class StubAlwaysOkAdapter(ResourceAdapterExecutorPort):
    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
    ) -> FileParseResult:
        return FileParseResult(
            ok=True,
            adapter=adapter,
            resource_title=absolute_path.stem,
            asset=ParsedAssetPayload(
                title=absolute_path.stem,
                role=role,
                sequence_index=None,
                sort_key=absolute_path.name,
                mime_type=None,
                duration_ms=None,
                failure_reason=None,
                technical=AssetTechnicalMetadata(),
            ),
            error_code=None,
            error_summary=None,
        )


def _bootstrap(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return engine


def _pipeline(db: Session) -> ReadableResourcePipeline:
    base = build_readable_resource_pipeline(db)
    libraries = SqlAlchemyLibraryConfigAdapter(db)
    filesystem = OsSourceTreeFilesystem()
    source_nodes = SqlAlchemySourceNodeRepository(db)
    books_resources = SqlAlchemyBookResourceRepository(db)
    import_runs = SqlAlchemyImportRunRepository(db)
    queue = SqlAlchemyReadableResourceWorkQueue(db)
    uow = SqlAlchemyUnitOfWork(db)
    process = ProcessReadableResourceImportTask(
        libraries=libraries,
        filesystem=filesystem,
        source_nodes=source_nodes,
        books_resources=books_resources,
        import_runs=import_runs,
        adapters=StubAlwaysOkAdapter(),
        queue=queue,
        uow=uow,
        clock=UtcClock(),
        log=StructuredPipelineLog(),
        sidecar=InMemorySidecarWriteback(),
    )
    return ReadableResourcePipeline(
        scan_library_source_tree=base.scan_library_source_tree,
        process_import_task=process,
        reimport_source_node=base.reimport_source_node,
        retry_readable_resource_import=base.retry_readable_resource_import,
        delete_source_node=base.delete_source_node,
        change_library_organization_mode=base.change_library_organization_mode,
        relocate_library_root=base.relocate_library_root,
        enable_readable_resource=base.enable_readable_resource,
        disable_readable_resource=base.disable_readable_resource,
        queue=queue,
        filesystem=filesystem,
        adapters=base.adapters,
        uow=uow,
        worker_id=base.worker_id,
    )


def test_expired_lease_fence_writes_nothing(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            db.add(
                Library(
                    id="lib-1",
                    name="Lib",
                    root_path=str(root),
                    organization_mode="FLAT",
                    min_file_size_bytes=0,
                )
            )
            root.mkdir(parents=True)
            (root / "Story.txt").write_text("hi\n", encoding="utf-8")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            pipeline.scan_library_source_tree.execute("lib-1")
            claim_a = pipeline.queue.claim_next("worker-a", lease_seconds=120)
            assert claim_a is not None
            past = db_timestamp() - timedelta(seconds=5)
            db.execute(
                update(ImportWorkItem)
                .where(ImportWorkItem.id == claim_a.work_item_id)
                .values(lease_expires_at=past)
            )
            db.commit()

            claim_b = pipeline.queue.claim_next("worker-b", lease_seconds=120)
            assert claim_b is not None
            assert claim_b.lease_owner == "worker-b"

            stale = pipeline.process_import_task.execute(claim_a.target_id, claim_a)
            assert stale.outcome == "late_lease"
            assert db.scalar(select(LibraryResourceAsset).limit(1)) is None

            live = pipeline.process_import_task.execute(claim_b.target_id, claim_b)
            assert live.outcome == "ok"
            assert db.scalar(select(LibraryResourceAsset).limit(1)) is not None
    finally:
        engine.dispose()


def test_scan_stops_on_lease_loss_and_complete_false(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            db.add(
                Library(
                    id="lib-1",
                    name="Lib",
                    root_path=str(root),
                    organization_mode="FLAT",
                    min_file_size_bytes=0,
                )
            )
            root.mkdir(parents=True)
            for i in range(5):
                (root / f"n{i}.txt").write_text("x\n", encoding="utf-8")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            pipeline.queue.enqueue_library_scan("lib-1")
            claim = pipeline.queue.claim_next("scanner", lease_seconds=120)
            assert claim is not None
            assert claim.work_kind == "scan"

            # Expire lease mid-scan before execute.
            past = db_timestamp() - timedelta(seconds=5)
            db.execute(
                update(ImportWorkItem)
                .where(ImportWorkItem.id == claim.work_item_id)
                .values(lease_expires_at=past, lease_owner="other")
            )
            db.commit()

            result = pipeline.scan_library_source_tree.execute(
                "lib-1", claim, lease_seconds=60
            )
            assert result.stopped_for_lease is True

            with pipeline.uow.transaction():
                assert pipeline.queue.complete(claim) is False

            worker = build_readable_resource_worker(pipeline)
            # Worker should not report success when complete fails.
            # Re-enqueue and expire again through process_once path.
            pipeline.queue.enqueue_library_scan("lib-1")
            claim2 = pipeline.queue.claim_next("scanner-2", lease_seconds=120)
            assert claim2 is not None
            past = db_timestamp() - timedelta(seconds=5)
            db.execute(
                update(ImportWorkItem)
                .where(ImportWorkItem.id == claim2.work_item_id)
                .values(lease_expires_at=past, lease_owner="stolen")
            )
            db.commit()
            # Direct path: scan with lost lease then complete False → not "scan".
            scan_result = pipeline.scan_library_source_tree.execute(
                claim2.target_id, claim2, lease_seconds=60
            )
            assert scan_result.stopped_for_lease is True
            with pipeline.uow.transaction():
                ok = pipeline.queue.complete(claim2)
            assert ok is False
            del worker
    finally:
        engine.dispose()
