"""Inactive target composition root for ADR 0018 readable-resource pipeline.

This module is intentionally not imported by production API/router/worker
startup. Phase 7 decides when to activate it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.reimport import (
    ReimportSourceNode,
    RetryReadableResourceImport,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
)
from app.modules.imports.infrastructure.readable_resource.filesystem import (
    OsSourceTreeFilesystem,
)
from app.modules.imports.infrastructure.readable_resource.import_run_repository import (
    SqlAlchemyImportRunRepository,
)
from app.modules.imports.infrastructure.readable_resource.support import (
    DurableSidecarWriteback,
    SqlAlchemyUnitOfWork,
    StructuredPipelineLog,
    UtcClock,
)
from app.modules.imports.infrastructure.readable_resource.work_queue import (
    SqlAlchemyReadableResourceWorkQueue,
)
from app.modules.imports.infrastructure.readable_resource.worker import (
    ReadableResourceWorkerProcessor,
)
from app.modules.library.application.commands.manage_source_tree import (
    ChangeLibraryOrganizationMode,
    DeleteSourceNode,
    DisableReadableResource,
    EnableReadableResource,
    RelocateLibraryRoot,
)
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemyBookResourceRepository,
    SqlAlchemyLibraryConfigAdapter,
    SqlAlchemySourceNodeRepository,
)
__all__ = [
    "ReadableResourcePipeline",
    "ReadableResourceWorkerProcessor",
    "build_readable_resource_pipeline",
]


@dataclass(frozen=True, slots=True)
class ReadableResourcePipeline:
    """Fully wired target use cases; not registered on production entrypoints."""

    scan_library_source_tree: ScanLibrarySourceTree
    process_import_task: ProcessReadableResourceImportTask
    reimport_source_node: ReimportSourceNode
    retry_readable_resource_import: RetryReadableResourceImport
    delete_source_node: DeleteSourceNode
    change_library_organization_mode: ChangeLibraryOrganizationMode
    relocate_library_root: RelocateLibraryRoot
    enable_readable_resource: EnableReadableResource
    disable_readable_resource: DisableReadableResource
    queue: SqlAlchemyReadableResourceWorkQueue
    filesystem: OsSourceTreeFilesystem
    adapters: RegistryResourceAdapterExecutor
    uow: SqlAlchemyUnitOfWork
    worker_id: str


def build_readable_resource_pipeline(
    session: Session, *, worker_id: str = "overlay-worker"
) -> ReadableResourcePipeline:
    libraries = SqlAlchemyLibraryConfigAdapter(session)
    filesystem = OsSourceTreeFilesystem()
    source_nodes = SqlAlchemySourceNodeRepository(session)
    books_resources = SqlAlchemyBookResourceRepository(session)
    import_runs = SqlAlchemyImportRunRepository(session)
    queue = SqlAlchemyReadableResourceWorkQueue(session)
    adapters = RegistryResourceAdapterExecutor()
    uow = SqlAlchemyUnitOfWork(session)
    clock = UtcClock()
    log = StructuredPipelineLog()

    def _persist_sidecar_intent(resource_id: str) -> None:
        # Recoverable marker after the import UoW committed; OPF priority unchanged.
        with uow.transaction():
            books_resources.touch_updated_at(resource_id)

    sidecar = DurableSidecarWriteback(_persist_sidecar_intent)

    scan = ScanLibrarySourceTree(
        libraries=libraries,
        filesystem=filesystem,
        source_nodes=source_nodes,
        books_resources=books_resources,
        import_runs=import_runs,
        queue=queue,
        uow=uow,
        clock=clock,
        log=log,
    )
    process_import = ProcessReadableResourceImportTask(
        libraries=libraries,
        filesystem=filesystem,
        source_nodes=source_nodes,
        books_resources=books_resources,
        import_runs=import_runs,
        adapters=adapters,
        queue=queue,
        uow=uow,
        clock=clock,
        log=log,
        sidecar=sidecar,
    )

    return ReadableResourcePipeline(
        scan_library_source_tree=scan,
        process_import_task=process_import,
        reimport_source_node=ReimportSourceNode(
            libraries=libraries,
            filesystem=filesystem,
            source_nodes=source_nodes,
            books_resources=books_resources,
            import_runs=import_runs,
            queue=queue,
            uow=uow,
            clock=clock,
            log=log,
        ),
        retry_readable_resource_import=RetryReadableResourceImport(
            books_resources=books_resources,
            import_runs=import_runs,
            source_nodes=source_nodes,
            queue=queue,
            uow=uow,
            log=log,
        ),
        delete_source_node=DeleteSourceNode(
            source_nodes=source_nodes,
            books_resources=books_resources,
            uow=uow,
            log=log,
        ),
        change_library_organization_mode=ChangeLibraryOrganizationMode(
            libraries=libraries,
            books_resources=books_resources,
            uow=uow,
            log=log,
        ),
        relocate_library_root=RelocateLibraryRoot(
            libraries=libraries,
            filesystem=filesystem,
            uow=uow,
            log=log,
        ),
        enable_readable_resource=EnableReadableResource(
            books_resources=books_resources,
            uow=uow,
            log=log,
        ),
        disable_readable_resource=DisableReadableResource(
            books_resources=books_resources,
            uow=uow,
            log=log,
        ),
        queue=queue,
        filesystem=filesystem,
        adapters=adapters,
        uow=uow,
        worker_id=worker_id,
    )


def build_readable_resource_worker(
    pipeline: ReadableResourcePipeline,
) -> ReadableResourceWorkerProcessor:
    return ReadableResourceWorkerProcessor(
        queue=pipeline.queue,
        scan=pipeline.scan_library_source_tree,
        process_import=pipeline.process_import_task,
        uow=pipeline.uow,
        worker_id=pipeline.worker_id,
    )
