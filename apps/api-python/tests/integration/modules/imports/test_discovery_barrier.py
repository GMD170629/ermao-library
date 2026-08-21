"""Discovery barrier: finalize only after discovery_complete and no incomplete tasks."""

from __future__ import annotations

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
    LibraryImportRun,
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


def test_discovery_barrier_keeps_run_active_until_complete(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    audio = root / "BarrierBook"
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
            (audio / "02.mp3").write_bytes(b"")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            pipeline.scan_library_source_tree.execute("lib-1")
            resource = db.scalar(select(LibraryReadableResource).limit(1))
            assert resource is not None
            run_id = resource.active_import_run_id
            assert run_id is not None

            # Force discovery incomplete while tasks exist.
            run = db.get(LibraryImportRun, run_id)
            assert run is not None
            run.discovery_complete = False
            db.commit()

            claim = pipeline.queue.claim_next("worker-1", lease_seconds=120)
            assert claim is not None
            assert claim.work_kind == "import"
            outcome = pipeline.process_import_task.execute(claim.target_id, claim)
            assert outcome.outcome == "ok"

            db.refresh(resource)
            assert resource.import_state == "READY"
            assert resource.active_import_run_id == run_id
            run = db.get(LibraryImportRun, run_id)
            assert run is not None
            assert run.state == "RUNNING"
            assert run.discovery_complete is False

            remaining = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.owner_import_run_id == run_id,
                    LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
                )
            ).all()
            assert len(remaining) >= 1

            with pipeline.uow.transaction():
                SqlAlchemyImportRunRepository(db).mark_discovery_complete(run_id)

            for i, task in enumerate(remaining):
                claim = pipeline.queue.claim_next(f"worker-fin-{i}", lease_seconds=120)
                if claim is None:
                    break
                if claim.work_kind != "import":
                    with pipeline.uow.transaction():
                        pipeline.queue.complete(claim)
                    continue
                pipeline.process_import_task.execute(claim.target_id, claim)

            # Drain any leftover.
            for i in range(10):
                claim = pipeline.queue.claim_next(f"worker-end-{i}", lease_seconds=120)
                if claim is None:
                    break
                if claim.work_kind == "import":
                    pipeline.process_import_task.execute(claim.target_id, claim)
                else:
                    with pipeline.uow.transaction():
                        pipeline.queue.complete(claim)

            db.refresh(resource)
            assert resource.active_import_run_id is None
            run = db.get(LibraryImportRun, run_id)
            assert run is not None
            assert run.state in {"COMPLETED", "COMPLETED_WITH_ERRORS"}
            assert run.discovery_complete is True
    finally:
        engine.dispose()
