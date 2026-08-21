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
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
)
from app.modules.imports.infrastructure.readable_resource.filesystem import (
    OsSourceTreeFilesystem,
)
from app.modules.imports.infrastructure.readable_resource.support import (
    DeferredSidecarWriteback,
    SqlAlchemyUnitOfWork,
    StructuredPipelineLog,
    UtcClock,
)
from app.modules.imports.infrastructure.readable_resource.work_queue import (
    SqlAlchemyReadableResourceWorkQueue,
)
from app.modules.library.application.commands.manage_source_tree import (
    ChangeLibraryOrganizationMode,
    DeleteSourceNode,
    DisableReadableResource,
    EnableReadableResource,
    RelocateLibraryRoot,
)
from app.modules.library.application.commands.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemyBookResourceRepository,
    SqlAlchemyImportRunRepository,
    SqlAlchemyLibraryConfigAdapter,
    SqlAlchemySourceNodeRepository,
)


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


def build_readable_resource_pipeline(session: Session) -> ReadableResourcePipeline:
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
    sidecar = DeferredSidecarWriteback()

    return ReadableResourcePipeline(
        scan_library_source_tree=ScanLibrarySourceTree(
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
        process_import_task=ProcessReadableResourceImportTask(
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
        ),
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
    )


class ReadableResourceWorkerProcessor:
    """Target worker loop body: claim overlay work and dispatch use cases."""

    def __init__(self, pipeline: ReadableResourcePipeline, *, worker_id: str) -> None:
        self._pipeline = pipeline
        self._worker_id = worker_id

    def process_once(self, *, lease_seconds: int = 120) -> str:
        claimed = self._pipeline.queue.claim_next(
            self._worker_id, lease_seconds=lease_seconds
        )
        if claimed is None:
            return "idle"
        kind, target_id = claimed
        try:
            if kind == "scan":
                self._pipeline.scan_library_source_tree.execute(target_id)
                self._pipeline.queue.complete("scan", target_id)
                return "scan"
            result = self._pipeline.process_import_task.execute(target_id)
            return result.outcome
        except Exception:
            # Containment boundary only.
            logger = __import__("logging").getLogger("ermao.readable_resource_pipeline")
            logger.exception(
                "readable_resource.worker.containment_failure",
                extra={"stage": "worker", "outcome": "error"},
            )
            return "error"
