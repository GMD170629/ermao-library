"""Incremental tasks during an active run are requeued, not completed as success."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.common import db_timestamp
from app.models.import_pipeline import ImportWorkItem
from app.models.library import Library
from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    FileParseResult,
    ParsedAssetPayload,
    ResourceAdapterExecutorPort,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.domain.import_run_policies import LibraryImportTaskState
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
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemyBookResourceRepository,
    SqlAlchemyLibraryConfigAdapter,
    SqlAlchemySourceNodeRepository,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
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


def test_incremental_during_active_run_requeues(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    audio = root / "LiveBook"
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
            audio.mkdir(parents=True)
            (audio / "01.mp3").write_bytes(b"")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            pipeline.scan_library_source_tree.execute("lib-1")
            resource = db.scalar(select(LibraryReadableResource).limit(1))
            assert resource is not None
            assert resource.active_import_run_id is not None

            # Create an incremental (no owner run) task against the same resource.
            file_node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "LiveBook/01.mp3"
                )
            )
            assert file_node is not None
            runs = SqlAlchemyImportRunRepository(db)
            with pipeline.uow.transaction():
                task = runs.create_task(
                    library_id="lib-1",
                    resource_id=resource.id,
                    source_node_id=file_node.id,
                    owner_import_run_id=None,
                    role=AssetRole.TRACK,
                )
                pipeline.queue.enqueue_library_import_task(task.id)
                task_id = task.id

            # Skip run-owned tasks; claim the incremental one.
            claimed_incremental = None
            for i in range(10):
                claim = pipeline.queue.claim_next(f"inc-{i}", lease_seconds=120)
                if claim is None:
                    break
                if claim.target_id == task_id:
                    claimed_incremental = claim
                    break
                # Put other work back without completing success writes.
                with pipeline.uow.transaction():
                    pipeline.queue.release_and_requeue(claim, delay_seconds=30)

            assert claimed_incremental is not None
            outcome = pipeline.process_import_task.execute(
                claimed_incremental.target_id, claimed_incremental
            )
            assert outcome.outcome == "deferred_active_run"

            task_row = db.get(LibraryImportTask, task_id)
            assert task_row is not None
            assert task_row.state == LibraryImportTaskState.QUEUED.value

            work = db.scalar(
                select(ImportWorkItem).where(
                    ImportWorkItem.status == "PENDING",
                )
            )
            # At least one PENDING item with future availableAt from requeue.
            pending = db.scalars(
                select(ImportWorkItem).where(ImportWorkItem.status == "PENDING")
            ).all()
            assert any(
                item.available_at is not None
                and item.available_at > db_timestamp() - timedelta(seconds=1)
                for item in pending
            )
            assert db.scalar(select(LibraryResourceAsset).limit(1)) is None
            del work
    finally:
        engine.dispose()
