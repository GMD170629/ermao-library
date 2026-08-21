"""Directory reimport discovers full scope beyond probe sample limit."""

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


def _drain_imports(pipeline: ReadableResourcePipeline, limit: int = 200) -> None:
    for i in range(limit):
        claim = pipeline.queue.claim_next(f"w-{i}", lease_seconds=120)
        if claim is None:
            break
        if claim.work_kind != "import":
            with pipeline.uow.transaction():
                pipeline.queue.complete(claim)
            continue
        pipeline.process_import_task.execute(claim.target_id, claim)


def test_reimport_directory_full_scope_beyond_probe(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    audio_dir = root / "BigBook"
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
            audio_dir.mkdir(parents=True)
            for i in range(50):
                (audio_dir / f"{i:03d}.mp3").write_bytes(b"")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            pipeline.scan_library_source_tree.execute("lib-1")
            _drain_imports(pipeline)
            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.adapter_id == "audiobook-directory"
                )
            )
            assert resource is not None
            db.refresh(resource)
            # Clear active so reimport can start.
            if resource.active_import_run_id is not None:
                books = SqlAlchemyBookResourceRepository(db)
                with pipeline.uow.transaction():
                    books.clear_active_import_run(resource.id)
            source_node_id = resource.source_node_id

        # Add files beyond the first probe sample window (101+ mp3).
        for i in range(50, 110):
            (audio_dir / f"{i:03d}.mp3").write_bytes(b"")

        with Session(engine) as db:
            pipeline = _pipeline(db)
            result = pipeline.reimport_source_node.execute(source_node_id)
            assert result.ok is True
            assert result.run_id is not None

            run = db.get(LibraryImportRun, result.run_id)
            assert run is not None
            assert run.discovery_complete is True

            dir_node = db.get(LibrarySourceNode, source_node_id)
            assert dir_node is not None
            file_nodes = db.scalars(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.physical_kind == "REGULAR_FILE",
                    LibrarySourceNode.relative_path.like("BigBook/%"),
                )
            ).all()
            assert len(file_nodes) >= 110

            tasks = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.owner_import_run_id == result.run_id
                )
            ).all()
            assert len(tasks) >= 110
            assert all(task.role == "TRACK" for task in tasks)
            assert all(task.source_node_id != source_node_id for task in tasks)
            task_node_ids = {task.source_node_id for task in tasks}
            for node_id in task_node_ids:
                node = db.get(LibrarySourceNode, node_id)
                assert node is not None
                assert node.physical_kind == "REGULAR_FILE"
    finally:
        engine.dispose()
