"""Composition root for the production ContinueImport pipeline.

The API and the dedicated import worker construct this graph for their own
short-lived SQLAlchemy session.  The graph contains the only import queue and
does not expose a legacy importer or queue-control runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.local_metadata_policy import SqlAlchemyLocalMetadataPriority
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueImport,
    ContinueImportResult,
    ContinueLibraryImport,
    ContinueSourceImport,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.imports.infrastructure.local_cover_publication import (
    FilesystemLocalCoverPublication,
)
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
)
from app.modules.imports.infrastructure.readable_resource.filesystem import (
    OsSourceTreeFilesystem,
)
from app.modules.imports.infrastructure.readable_resource.support import (
    BestEffortSidecarWriteback,
    SqlAlchemyUnitOfWork,
    StructuredPipelineLog,
    UtcClock,
)
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
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
    "build_readable_resource_worker",
    "continue_library_import",
    "continue_source_import",
]


@dataclass(frozen=True, slots=True)
class ReadableResourcePipeline:
    """Fully wired ContinueImport use cases and their target adapters."""

    continue_import: ContinueImport
    scan_library_source_tree: ScanLibrarySourceTree
    process_import_task: ProcessReadableResourceImportTask
    delete_source_node: DeleteSourceNode
    change_library_organization_mode: ChangeLibraryOrganizationMode
    relocate_library_root: RelocateLibraryRoot
    enable_readable_resource: EnableReadableResource
    disable_readable_resource: DisableReadableResource
    queue: SqlAlchemyLibraryImportTaskQueue
    filesystem: OsSourceTreeFilesystem
    adapters: RegistryResourceAdapterExecutor
    uow: SqlAlchemyUnitOfWork
    clock: UtcClock


def build_readable_resource_pipeline(session: Session) -> ReadableResourcePipeline:
    libraries = SqlAlchemyLibraryConfigAdapter(session)
    filesystem = OsSourceTreeFilesystem()
    source_nodes = SqlAlchemySourceNodeRepository(session)
    books_resources = SqlAlchemyBookResourceRepository(session)
    queue = SqlAlchemyLibraryImportTaskQueue(session)
    adapters = RegistryResourceAdapterExecutor()
    uow = SqlAlchemyUnitOfWork(session)
    clock = UtcClock()
    log = StructuredPipelineLog()
    # Best-effort sidecar: no durable fake queue; failures never roll back import.
    sidecar = BestEffortSidecarWriteback(None)

    scan = ScanLibrarySourceTree(
        libraries=libraries,
        filesystem=filesystem,
        source_nodes=source_nodes,
        books_resources=books_resources,
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
        adapters=adapters,
        queue=queue,
        uow=uow,
        clock=clock,
        log=log,
        sidecar=sidecar,
        metadata_priority=SqlAlchemyLocalMetadataPriority(session),
        covers=FilesystemLocalCoverPublication(get_settings().resolved_storage_root),
    )
    continue_import = ContinueImport(
        libraries=libraries,
        source_nodes=source_nodes,
        queue=queue,
        uow=uow,
        log=log,
    )

    return ReadableResourcePipeline(
        continue_import=continue_import,
        scan_library_source_tree=scan,
        process_import_task=process_import,
        delete_source_node=DeleteSourceNode(
            source_nodes=source_nodes,
            books_resources=books_resources,
            import_tasks=queue,
            uow=uow,
            log=log,
        ),
        change_library_organization_mode=ChangeLibraryOrganizationMode(
            libraries=libraries,
            books_resources=books_resources,
            import_tasks=queue,
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
        clock=clock,
    )


def continue_library_import(session: Session, library_id: str) -> ContinueImportResult:
    """Enqueue one library ContinueImport command in the caller session."""

    pipeline = build_readable_resource_pipeline(session)
    return pipeline.continue_import.execute(ContinueLibraryImport(library_id))


def continue_source_import(
    session: Session, source_node_id: str
) -> ContinueImportResult:
    """Enqueue one source-node ContinueImport command in the caller session."""

    pipeline = build_readable_resource_pipeline(session)
    return pipeline.continue_import.execute(ContinueSourceImport(source_node_id))


def build_readable_resource_worker(
    pipeline: ReadableResourcePipeline,
) -> ReadableResourceWorkerProcessor:
    return ReadableResourceWorkerProcessor(
        queue=pipeline.queue,
        scan=pipeline.scan_library_source_tree,
        process_import=pipeline.process_import_task,
        uow=pipeline.uow,
        clock=pipeline.clock,
    )
