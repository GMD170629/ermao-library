"""Integration coverage for ADR 0018 single-consumer ContinueImport."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import wave
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.contracts.local_metadata_snapshot import decode_observations
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import (
    Library,
    LibraryBookFacet,
    LibraryFacet,
    ReadableResourceNavigationUnit,
)
from app.modules.imports.application.audio_types import (
    AudioChapterMetadata,
    AudioFileMetadata,
)
from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    decode_book_work,
)
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
    ContinueSourceImport,
)
from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    FileParseResult,
    ObservedSourceEntry,
    ParsedAssetPayload,
    ResourceAdapterExecutorPort,
    UnreadableDirectoryEntry,
    adapter_identity,
)
from app.modules.imports.application.readable_resource.process_book_resources import (
    ProcessBookResources,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    SourceScanIncompleteError,
)
from app.modules.imports.domain.resource_adapters import (
    ResourceAdapterSpec,
    match_file_adapters,
    unique_adapter_or_none,
)
from app.modules.imports.domain.scan_policy import MissingEntryPolicy
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
)
from app.modules.imports.infrastructure.readable_resource.filesystem import (
    OsSourceTreeFilesystem,
)
from app.modules.imports.infrastructure.readable_resource.support import (
    InMemorySidecarWriteback,
    SqlAlchemyUnitOfWork,
    StructuredPipelineLog,
    UtcClock,
)
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.application.metadata_ownership import protect_fields
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.infrastructure.books import resource_import_summaries
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemyBookResourceRepository,
    SqlAlchemyLibraryConfigAdapter,
    SqlAlchemySourceNodeRepository,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibraryResourceAssetNavigation,
    LibrarySourceNode,
    LibrarySourceNodeInterpretation,
)
from app.modules.library.public import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
)


class StubAlwaysOkAdapter(ResourceAdapterExecutorPort):
    def inspect_resource_metadata(self, **kwargs):
        return RegistryResourceAdapterExecutor().inspect_resource_metadata(**kwargs)

    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        **_kwargs: object,
    ) -> FileParseResult:
        resource_path = _kwargs.get("resource_absolute_path")
        resource_title = (
            resource_path.name
            if isinstance(resource_path, Path) and resource_path.is_dir()
            else absolute_path.stem
        )
        return FileParseResult(
            ok=True,
            adapter=adapter,
            resource_title=resource_title,
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


class StubFailOnceAdapter(StubAlwaysOkAdapter):
    def __init__(self, fail_names: set[str]) -> None:
        self._fail_names = fail_names

    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        **_kwargs: object,
    ) -> FileParseResult:
        if absolute_path.name in self._fail_names:
            return FileParseResult(
                ok=False,
                adapter=adapter,
                resource_title=None,
                asset=None,
                error_code="PARSE_FAILED",
                error_summary="PARSE_FAILED",
            )
        return super().parse_file(
            absolute_path=absolute_path, adapter=adapter, role=role
        )


class StubPdfPageCountAdapter(StubAlwaysOkAdapter):
    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        **kwargs: object,
    ) -> FileParseResult:
        result = super().parse_file(
            absolute_path=absolute_path,
            adapter=adapter,
            role=role,
            **kwargs,
        )
        assert result.asset is not None
        return replace(
            result,
            asset=replace(
                result.asset,
                technical=AssetTechnicalMetadata(page_count=7),
            ),
        )


def _bootstrap(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return engine


def _add_library(db: Session, root: Path, library_id: str = "lib-1") -> None:
    root.mkdir(parents=True, exist_ok=True)
    db.add(
        Library(
            id=library_id,
            name="Lib",
            root_path=str(root),
            organization_mode="FLAT",
            min_file_size_bytes=0,
        )
    )


def _add_volumes_library(db: Session, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    db.add(
        Library(
            id="lib-1",
            name="Lib",
            root_path=str(root),
            organization_mode="VOLUMES",
            min_file_size_bytes=0,
        )
    )


def _pipeline(
    db: Session,
    *,
    adapters: ResourceAdapterExecutorPort | None = None,
) -> tuple[ReadableResourcePipeline, InMemorySidecarWriteback]:
    base = build_readable_resource_pipeline(db)
    libraries = SqlAlchemyLibraryConfigAdapter(db)
    filesystem = OsSourceTreeFilesystem()
    source_nodes = SqlAlchemySourceNodeRepository(db)
    books_resources = SqlAlchemyBookResourceRepository(db)
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    uow = SqlAlchemyUnitOfWork(db)
    clock = UtcClock()
    log = StructuredPipelineLog()
    sidecar = InMemorySidecarWriteback()
    process = ProcessReadableResourceImportTask(
        libraries=libraries,
        filesystem=filesystem,
        source_nodes=source_nodes,
        books_resources=books_resources,
        adapters=adapters or StubAlwaysOkAdapter(),
        queue=queue,
        uow=uow,
        clock=clock,
        log=log,
        sidecar=sidecar,
    )
    pipeline = ReadableResourcePipeline(
        continue_import=base.continue_import,
        scan_library_source_tree=base.scan_library_source_tree,
        process_import_task=process,
        identify_book=base.identify_book,
        delete_book_sources=base.delete_book_sources,
        delete_source_node=base.delete_source_node,
        change_library_organization_mode=base.change_library_organization_mode,
        relocate_library_root=base.relocate_library_root,
        enable_readable_resource=base.enable_readable_resource,
        disable_readable_resource=base.disable_readable_resource,
        request_library_scan=base.request_library_scan,
        queue=queue,
        books_resources=books_resources,
        filesystem=filesystem,
        adapters=base.adapters,
        uow=uow,
        clock=clock,
    )
    return pipeline, sidecar


def _drain(pipeline: ReadableResourcePipeline, *, limit: int = 200) -> list[str]:
    worker = build_readable_resource_worker(pipeline)
    outcomes: list[str] = []
    for _ in range(limit):
        outcome = worker.process_once()
        if outcome == "idle":
            break
        outcomes.append(outcome)
    return outcomes


def test_root_scan_keeps_missing_nodes_after_late_enumeration_failure(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "live.epub").write_bytes(b"epub")
            nodes = SqlAlchemySourceNodeRepository(db)
            stale, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=ObservedSourceEntry(
                    SourceNodeRelativePath("old.epub"),
                    SourceNodePhysicalKind.REGULAR_FILE,
                    1,
                    1,
                    datetime.now(UTC),
                ),
            )
            db.commit()
            pipeline, _ = _pipeline(db)

            class LateFailureFilesystem(OsSourceTreeFilesystem):
                def iter_directory_entries(self, absolute: Path):
                    if absolute != root:
                        yield from super().iter_directory_entries(absolute)
                        return
                    yield from super().iter_directory_entries(absolute)
                    for index in range(199):
                        yield (f"ignored-{index:03}.txt", SourceNodePhysicalKind.REGULAR_FILE, 1, 1)
                    yield UnreadableDirectoryEntry("broken", OSError("late failure"))

            pipeline.scan_library_source_tree._filesystem = LateFailureFilesystem()
            with pytest.raises(SourceScanIncompleteError):
                pipeline.scan_library_source_tree.execute_library(
                    "lib-1", missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING
                )
            assert nodes.get(stale.id) is not None
            assert nodes.get_by_path_key(
                "lib-1", SourceNodeRelativePath("live.epub").path_key
            ) is not None
    finally:
        engine.dispose()


def test_completed_root_scan_prunes_missing_nodes_across_pages(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "live.epub").write_bytes(b"epub")
            nodes = SqlAlchemySourceNodeRepository(db)
            for offset in range(0, 205, 200):
                entries = tuple(
                    ObservedSourceEntry(
                        SourceNodeRelativePath(f"old-{index:03}.epub"),
                        SourceNodePhysicalKind.REGULAR_FILE,
                        1,
                        1,
                        datetime.now(UTC),
                    )
                    for index in range(offset, min(offset + 200, 205))
                )
                nodes.reconcile_batch(
                    library_id="lib-1", parent_id=None, entries=entries
                )
            db.commit()
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library(
                "lib-1", missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING
            )
            remaining = nodes.list_direct_children(library_id="lib-1", parent_id=None)
            assert tuple(node.relative_path for node in remaining) == ("live.epub",)
    finally:
        engine.dispose()


def test_flat_category_reconciles_first_page_before_reading_later_entries(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            category = root / "category"
            category.mkdir()
            for index in range(205):
                (category / f"book-{index:03}").mkdir()
            pipeline, _ = _pipeline(db)

            class ObservedBatchFilesystem(OsSourceTreeFilesystem):
                category_reads = 0
                first_page_was_persisted = False

                def iter_directory_entries(self, absolute: Path):
                    if absolute != category:
                        yield from super().iter_directory_entries(absolute)
                        return
                    self.category_reads += 1
                    first_scan = self.category_reads == 1
                    for index, entry in enumerate(super().iter_directory_entries(absolute)):
                        if first_scan and index == 200:
                            self.first_page_was_persisted = (
                                db.scalar(
                                    select(func.count())
                                    .select_from(LibrarySourceNode)
                                    .where(LibrarySourceNode.parent_id.is_not(None))
                                )
                                >= 200
                            )
                        yield entry

            filesystem = ObservedBatchFilesystem()
            pipeline.scan_library_source_tree._filesystem = filesystem
            pipeline.scan_library_source_tree.execute_library("lib-1")
            assert filesystem.first_page_was_persisted
            assert db.scalar(select(func.count()).select_from(LibrarySourceNode)) == 206
    finally:
        engine.dispose()


def test_large_directory_resource_context_observes_late_sidecar(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            comic = root / "comic"
            comic.mkdir()
            for index in range(205):
                (comic / f"page-{index:03}.png").write_bytes(b"png")
            sidecar = comic / "zzz.opf"
            sidecar.write_bytes(b"old")
            pipeline, _ = _pipeline(db)

            class OrderedFilesystem(OsSourceTreeFilesystem):
                def iter_directory_entries(self, absolute: Path):
                    if absolute == comic:
                        yield from sorted(super().iter_directory_entries(absolute))
                    else:
                        yield from super().iter_directory_entries(absolute)

            pipeline.scan_library_source_tree._filesystem = OrderedFilesystem()
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.format == "IMAGE_DIR"
                )
            )
            assert resource is not None
            initial_version = resource.scan_context_version
            assert initial_version is not None

            pipeline.scan_library_source_tree.execute_library("lib-1")
            db.refresh(resource)
            assert resource.scan_context_version == initial_version

            sidecar.write_bytes(b"changed")
            pipeline.scan_library_source_tree.execute_library("lib-1")
            db.refresh(resource)
            assert resource.scan_context_version != initial_version
            assert (
                db.scalar(select(func.count()).select_from(LibrarySourceNode)) == 206
            )
    finally:
        engine.dispose()


class _RecordingResourceRun:
    def __init__(self) -> None:
        self.operation_id = "book-operation"
        self.current = True
        self.started = 0
        self.succeeded = 0
        self.failures: list[str] = []
        self.changed = 0

    @property
    def can_yield_directory(self) -> bool:
        return False

    @property
    def force_reimport(self) -> bool:
        return False

    def directory_cursor(self, resource_id: str) -> str | None:
        return None

    def advance_directory_cursor(self, resource_id: str, member_id: str) -> None:
        return None

    def directory_cover_cursor(self, resource_id: str) -> str | None:
        return None

    def advance_directory_cover_cursor(self, resource_id: str, asset_id: str) -> None:
        return None

    def is_current(self) -> bool:
        return self.current

    def start(self, *, started_at: datetime) -> None:
        self.started += 1

    def request_changed(
        self, *, library_id: str, resource_id: str, source_node_id: str
    ) -> None:
        self.changed += 1

    def succeed(self, *, finished_at: datetime) -> None:
        self.succeeded += 1

    def fail(
        self, *, error_summary: str, finished_at: datetime,
        result_persisted: bool = False,
    ) -> None:
        self.failures.append(error_summary)


def test_book_resource_step_keeps_good_result_when_sibling_fails(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            db.commit()
            folder = root / "book"
            folder.mkdir()
            (folder / "good.epub").write_bytes(b"good")
            (folder / "bad.epub").write_bytes(b"bad")
            adapter = StubFailOnceAdapter({"bad.epub"})
            pipeline, _ = _pipeline(db, adapters=adapter)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            book = db.scalar(select(LibraryBook))
            assert book is not None
            resources = db.scalars(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.book_id == book.id
                )
            ).all()
            assert len(resources) == 2
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind.in_(("IMPORT_RESOURCE", "IMPORT_BOOK"))
                )
            )
            requested = pipeline.queue.request_book_work(
                book_id=book.id,
                work=BookWork(resource_ids=tuple(resource.id for resource in resources)),
                requested_at=datetime.now(UTC),
            )
            db.commit()
            claimed = pipeline.queue.claim_next_book(started_at=datetime.now(UTC))
            assert claimed is not None and claimed.id == requested.id
            db.commit()

            step = ProcessBookResources(
                queue=pipeline.queue,
                resources=SqlAlchemyBookResourceRepository(db),
                process_resource=pipeline.process_import_task,
                uow=pipeline.uow,
                clock=pipeline.clock,
            )
            result = step.execute(claimed)
            assert result.outcome == "partial"
            assert result.error_summary == "PARSE_FAILED"
            assert db.scalar(
                select(func.count()).select_from(LibraryResourceAsset).where(
                    LibraryResourceAsset.import_state == "READY"
                )
            ) == 1
            assert db.scalar(
                select(func.count()).select_from(LibraryResourceAsset).where(
                    LibraryResourceAsset.import_state == "FAILED"
                )
            ) == 1
            assert db.get(LibraryImportTask, requested.id).state == "RUNNING"
            failed = pipeline.queue.fail_book_run(
                requested.id,
                execution_version=claimed.execution_version,
                error_summary=result.error_summary,
                failed_at=datetime.now(UTC),
            )
            assert failed is not None and failed.state == "FAILED"
    finally:
        engine.dispose()


def test_book_resource_step_keeps_request_added_during_parse(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "one.epub").write_bytes(b"book")
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind.in_(("IMPORT_RESOURCE", "IMPORT_BOOK"))
                )
            )
            requested = pipeline.queue.request_book_work(
                book_id=resource.book_id,
                work=BookWork(resource_ids=(resource.id,)),
                requested_at=datetime.now(UTC),
            )
            db.commit()
            claimed = pipeline.queue.claim_next_book(started_at=datetime.now(UTC))
            assert claimed is not None and claimed.id == requested.id
            assert claimed.execution_version is not None
            db.commit()

            class RequestDuringParse(StubAlwaysOkAdapter):
                def parse_file(self, *, absolute_path, adapter, role, **kwargs):
                    pipeline.queue.request_book_work(
                        book_id=resource.book_id,
                        work=BookWork(identify=True),
                        requested_at=datetime.now(UTC),
                    )
                    db.commit()
                    return super().parse_file(
                        absolute_path=absolute_path, adapter=adapter, role=role, **kwargs
                    )

            pipeline.process_import_task._adapters = RequestDuringParse()
            step = ProcessBookResources(
                queue=pipeline.queue,
                resources=SqlAlchemyBookResourceRepository(db),
                process_resource=pipeline.process_import_task,
                uow=pipeline.uow,
                clock=pipeline.clock,
            )
            assert step.execute(claimed).outcome == "ok"
            assert pipeline.queue.get_book_task(requested.id).state == "RUNNING"
            new_requests = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibraryImportTask.book_id == resource.book_id,
                    LibraryImportTask.id != requested.id,
                )
            ).all()
            assert len(new_requests) == 1
            assert new_requests[0].state == "QUEUED"
            assert pipeline.queue.get_book_task(new_requests[0].id).work.identify
    finally:
        engine.dispose()


def test_book_resource_step_discards_result_after_resource_removal(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "one.epub").write_bytes(b"book")
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind.in_(("IMPORT_RESOURCE", "IMPORT_BOOK"))
                )
            )
            requested = pipeline.queue.request_book_work(
                book_id=resource.book_id,
                work=BookWork(resource_ids=(resource.id,)),
                requested_at=datetime.now(UTC),
            )
            db.commit()
            claimed = pipeline.queue.claim_next_book(started_at=datetime.now(UTC))
            assert claimed is not None
            db.commit()

            class RemoveDuringParse(StubAlwaysOkAdapter):
                def parse_file(self, *, absolute_path, adapter, role, **kwargs):
                    parsed = super().parse_file(
                        absolute_path=absolute_path, adapter=adapter, role=role, **kwargs
                    )
                    db.execute(
                        delete(LibraryReadableResource).where(
                            LibraryReadableResource.id == resource.id
                        )
                    )
                    db.commit()
                    return parsed

            pipeline.process_import_task._adapters = RemoveDuringParse()
            step = ProcessBookResources(
                queue=pipeline.queue,
                resources=SqlAlchemyBookResourceRepository(db),
                process_resource=pipeline.process_import_task,
                uow=pipeline.uow,
                clock=pipeline.clock,
            )
            assert step.execute(claimed).outcome == "cancelled"
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 0
            assert db.get(LibraryImportTask, requested.id).state == "RUNNING"
    finally:
        engine.dispose()


def test_book_run_identifies_its_book_while_library_discovery_is_queued(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "one.epub").write_bytes(b"book")
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            book = db.scalar(select(LibraryBook))
            assert book is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
            pipeline.queue.enqueue(kind="SCAN_LIBRARY", library_id="lib-1")
            requested = pipeline.queue.request_book_work(
                book_id=book.id,
                work=BookWork(identify=True),
                requested_at=datetime.now(UTC),
            )
            db.commit()
            claimed = pipeline.queue.claim_next_book(started_at=datetime.now(UTC))
            assert claimed is not None and claimed.execution_version is not None
            db.commit()

            assert pipeline.identify_book.execute(book.source_node_id) == "identified"
            assert (
                pipeline.identify_book.execute(
                    book.source_node_id,
                    book_run_current=lambda: pipeline.queue.book_run_is_current(
                        requested.id,
                        execution_version=claimed.execution_version,
                        require_latest_request=True,
                    ),
                )
                == "stale"
            )
            metadata = db.get(LibraryBookMetadata, book.id)
            assert metadata is not None
            assert metadata.metadata_pending is False
            assert metadata.metadata_state == "COMPLETED"
            assert db.get(LibraryImportTask, requested.id).state == "QUEUED"
    finally:
        engine.dispose()


def test_claimed_book_processes_resource_then_identifies_and_finishes(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "one.epub").write_bytes(b"book")
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind.in_(("IMPORT_RESOURCE", "IMPORT_BOOK"))
                )
            )
            requested = pipeline.queue.request_book_work(
                book_id=resource.book_id,
                work=BookWork(resource_ids=(resource.id,)),
                requested_at=datetime.now(UTC),
            )
            db.commit()
            claimed = pipeline.queue.claim_next_book(started_at=datetime.now(UTC))
            assert claimed is not None and claimed.id == requested.id
            assert claimed.execution_version is not None
            db.commit()

            step = ProcessBookResources(
                queue=pipeline.queue,
                resources=SqlAlchemyBookResourceRepository(db),
                process_resource=pipeline.process_import_task,
                uow=pipeline.uow,
                clock=pipeline.clock,
            )
            assert step.execute(claimed).outcome == "ok"
            assert (
                pipeline.identify_book.execute(
                    claimed.source_node_id,
                    book_run_current=lambda: pipeline.queue.book_run_is_current(
                        requested.id,
                        execution_version=claimed.execution_version,
                        require_latest_request=True,
                    ),
                )
                == "identified"
            )
            finished = pipeline.queue.finish_book_run(
                requested.id,
                execution_version=claimed.execution_version,
                finished_at=datetime.now(UTC),
            )
            assert finished is not None and finished.state == "SUCCEEDED"
            metadata = db.get(LibraryBookMetadata, resource.book_id)
            assert metadata is not None and not metadata.metadata_pending
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 1
            assert db.scalar(
                select(func.count()).select_from(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            ) == 0
    finally:
        engine.dispose()


def test_book_with_many_resources_uses_pages_without_rescanning(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            db.commit()
            folder = root / "book"
            folder.mkdir()
            for index in range(129):
                (folder / f"volume-{index:03}.epub").write_bytes(b"book")
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            book_task = db.scalar(
                select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK")
            )
            assert book_task is not None
            assert db.scalar(
                select(func.count()).select_from(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            ) == 0
            db.commit()
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "book"
            db.expire_all()
            assert book_task.state == "SUCCEEDED"
            assert book_task.phase == "FINALIZE"
            assert book_task.resource_cursor is not None
            assert db.scalar(
                select(func.count()).select_from(LibraryResourceAsset).where(
                    LibraryResourceAsset.import_state == "READY"
                )
            ) == 129
            assert worker.process_once() == "idle"
    finally:
        engine.dispose()


def test_large_image_directory_finishes_before_next_book(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            large = root / "a-large"
            large.mkdir()
            image = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lZkAAAAASUVORK5CYII="
            )
            for index in range(250):
                (large / f"page-{index:03}.png").write_bytes(image)
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with (root / "z-small.pdf").open("wb") as small_file:
                writer.write(small_file)
            pipeline, _ = _pipeline(db, adapters=RegistryResourceAdapterExecutor())
            pipeline.scan_library_source_tree.execute_library("lib-1")
            directory = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.format == "IMAGE_DIR"
                )
            )
            small = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.format == "PDF"
                )
            )
            assert directory is not None and small is not None
            large_task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibraryImportTask.book_id == directory.book_id,
                )
            )
            assert large_task is not None
            large_task.created_at = datetime(2020, 1, 1, tzinfo=UTC)
            db.commit()

            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "book"
            assert db.scalar(
                select(func.count()).select_from(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == directory.id,
                    LibraryResourceAsset.import_state == "READY",
                )
            ) == 250
            assert worker.process_once() == "book"
            assert db.scalar(
                select(func.count()).select_from(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == small.id,
                    LibraryResourceAsset.import_state == "READY",
                )
            ) == 1
            book_task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.book_id == directory.book_id,
            ))
            assert book_task.state == "SUCCEEDED"
            (large / "late.png").write_bytes(image)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            earlier_node_id = db.scalar(select(LibrarySourceNode.id).where(
                LibrarySourceNode.relative_path == "a-large/late.png"
            ))
            assert earlier_node_id is not None
            outcomes = _drain(pipeline, limit=12)
            assert "book" in outcomes
            assert book_task.state == "SUCCEEDED"
            assert db.scalar(select(LibraryResourceAsset.id).where(
                LibraryResourceAsset.resource_id == directory.id,
                LibraryResourceAsset.source_node_id == earlier_node_id,
                LibraryResourceAsset.import_state == "READY",
            )) is not None
    finally:
        engine.dispose()


def test_earlier_resource_failure_survives_later_directory_pagination(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "library"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            book_path = root / "Series"
            pages = book_path / "z-pages"
            pages.mkdir(parents=True)
            (book_path / "a-bad.epub").write_bytes(b"bad")
            for index in range(205):
                (pages / f"page-{index:03}.png").write_bytes(b"image")
            db.commit()

            adapter = StubFailOnceAdapter({"a-bad.epub"})
            pipeline, _ = _pipeline(db, adapters=adapter)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert build_readable_resource_worker(pipeline).process_once() == "scan"
            resources_by_format = dict(db.execute(
                select(LibraryReadableResource.format, LibraryReadableResource.id)
            ).all())
            assert set(resources_by_format) == {"EPUB", "IMAGE_DIR"}
            db.execute(update(LibraryReadableResource).where(
                LibraryReadableResource.id == resources_by_format["EPUB"]
            ).values(id="a-failing-resource"))
            db.execute(update(LibraryReadableResource).where(
                LibraryReadableResource.id == resources_by_format["IMAGE_DIR"]
            ).values(id="z-paged-resource"))
            db.commit()
            resources = db.execute(
                select(LibraryReadableResource.id, LibraryReadableResource.format)
                .order_by(LibraryReadableResource.id)
            ).all()
            assert resources[0].format == "EPUB"
            assert resources[1].format == "IMAGE_DIR"

            assert build_readable_resource_worker(pipeline).process_once() == "failed"
            task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK"
            ))
            assert task is not None and task.state == "FAILED"
            assert task.error_summary == "PARSE_FAILED"
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset).where(
                LibraryResourceAsset.resource_id == resources[1].id,
                LibraryResourceAsset.import_state == "READY",
            )) == 205
            metadata = db.get(LibraryBookMetadata, task.book_id)
            assert metadata is not None and metadata.metadata_state == "COMPLETED"
            assert metadata.processed_revision == metadata.import_revision
    finally:
        engine.dispose()


@pytest.mark.parametrize("bad_index", [0, 128, 256])
def test_directory_failed_member_isolated_then_new_task_repairs_after_restart(
    tmp_path: Path, bad_index: int,
) -> None:
    class CountingAdapter(RegistryResourceAdapterExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.visited: Counter[str] = Counter()
            self.fail_name: str | None = None

        def parse_file(self, *, absolute_path: Path, **kwargs):
            self.visited[absolute_path.name] += 1
            if absolute_path.name == self.fail_name:
                return FileParseResult(
                    ok=False, adapter=kwargs["adapter"], resource_title=None,
                    asset=None, error_code="PARSE_FAILED", error_summary="PARSE_FAILED",
                )
            return super().parse_file(absolute_path=absolute_path, **kwargs)

    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lZkAAAAASUVORK5CYII="
    )
    adapter = CountingAdapter()
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            large = root / "album"
            large.mkdir()
            for index in range(257):
                (large / f"page-{index:03}.png").write_bytes(image)
            pipeline, _ = _pipeline(db, adapters=adapter)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource_id = db.scalar(select(LibraryReadableResource.id))
            resource = db.get(LibraryReadableResource, resource_id)
            db.execute(delete(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            pipeline.queue.request_book_work(
                book_id=resource.book_id,
                work=BookWork(resource_ids=(resource_id,)),
                requested_at=datetime.now(UTC),
            )
            directory_task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibraryImportTask.book_id == resource.book_id,
                )
            )
            assert directory_task is not None
            directory_task_id = directory_task.id
            book_id = resource.book_id
            ordered_nodes = db.scalars(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path.startswith("album/", autoescape=True),
                    LibrarySourceNode.physical_kind == "REGULAR_FILE",
                ).order_by(LibrarySourceNode.id)
            ).all()
            assert len(ordered_nodes) == 257
            page = SqlAlchemyBookResourceRepository(db).page_directory_members(
                resource_id, after_id=None, limit=128
            )
            assert len(page.members) == 128 and page.full
            bad_node = ordered_nodes[bad_index]
            bad_node_id = bad_node.id
            bad_name = bad_node.name
            adapter.fail_name = bad_name
            bad_path = root / bad_node.relative_path
            bad_path.write_bytes(b"not an image")
            observation = bad_path.stat()
            bad_node.observed_size_bytes = observation.st_size
            bad_node.observed_mtime_ns = observation.st_mtime_ns
            db.commit()

        with Session(engine) as db:
            pipeline, _ = _pipeline(db, adapters=adapter)
            assert build_readable_resource_worker(pipeline).process_once() == "failed"
            old_task = db.get(LibraryImportTask, directory_task_id)
            assert old_task is not None and old_task.state == "FAILED"
            assets = db.scalars(
                select(LibraryResourceAsset).where(LibraryResourceAsset.resource_id == resource_id)
            ).all()
            assert len(assets) == 257
            assert sum(asset.import_state == "FAILED" for asset in assets) == 1
            assert set(adapter.visited.values()) == {1}
            assert db.get(LibraryReadableResource, resource_id).import_state == "READY"
            original_ids = {asset.source_node_id: asset.id for asset in assets}
            bad_path.write_bytes(image)
            repaired = bad_path.stat()
            node = db.get(LibrarySourceNode, bad_node_id)
            node.observed_size_bytes = repaired.st_size
            node.observed_mtime_ns = repaired.st_mtime_ns
            adapter.fail_name = None
            new_task = pipeline.queue.request_book_work(
                book_id=book_id,
                work=BookWork(resource_ids=(resource_id,)),
                requested_at=datetime.now(UTC),
            )
            new_task_id = new_task.id
            assert new_task_id != directory_task_id
            db.commit()

        with Session(engine) as db:
            pipeline, _ = _pipeline(db, adapters=adapter)
            assert build_readable_resource_worker(pipeline).process_once() == "book"
            assert db.get(LibraryImportTask, directory_task_id).state == "FAILED"
            assert db.get(LibraryImportTask, new_task_id).state == "SUCCEEDED"
        assert adapter.visited[bad_name] == 2
        assert all(
            count == 1 for name, count in adapter.visited.items()
            if name != bad_name
        )
        with Session(engine) as db:
            repaired_assets = db.scalars(
                select(LibraryResourceAsset).where(LibraryResourceAsset.resource_id == resource_id)
            ).all()
            assert all(asset.import_state == "READY" for asset in repaired_assets)
            assert {asset.source_node_id: asset.id for asset in repaired_assets} == original_ids
    finally:
        engine.dispose()


def test_real_wav_directory_uses_same_member_yield_and_audio_aggregate(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            album = root / "album"
            album.mkdir()
            for index in range(129):
                with wave.open(str(album / f"{index:03}.wav"), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(8000)
                    output.writeframes(b"\x00\x00" * 800)
            pipeline, _ = _pipeline(db, adapters=RegistryResourceAdapterExecutor())
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource).where(
                LibraryReadableResource.format == "AUDIOBOOK_DIR"
            ))
            assert resource is not None
            resource_id = resource.id
            db.execute(delete(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            pipeline.queue.request_book_work(
                book_id=resource.book_id,
                work=BookWork(resource_ids=(resource_id,)),
                requested_at=datetime.now(UTC),
            )
            db.commit()
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "book"
            metadata = db.get(LibraryReadableResourceMetadata, resource_id)
            assert metadata.track_count == 129
            assert metadata.duration_ms == 129 * 100
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset).where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
            )) == 129
    finally:
        engine.dispose()


@pytest.mark.parametrize("member_count", [127, 128, 129])
def test_directory_member_budget_edges(tmp_path: Path, member_count: int) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lZkAAAAASUVORK5CYII="
    )
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            album = root / "album"
            album.mkdir()
            for index in range(member_count):
                (album / f"{index:03}.png").write_bytes(image)
            pipeline, _ = _pipeline(db, adapters=RegistryResourceAdapterExecutor())
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource).where(
                LibraryReadableResource.format == "IMAGE_DIR"
            ))
            assert resource is not None
            resource_id = resource.id
            db.execute(delete(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            pipeline.queue.request_book_work(
                book_id=resource.book_id,
                work=BookWork(resource_ids=(resource_id,)),
                requested_at=datetime.now(UTC),
            )
            db.commit()
            member_queries: list[str] = []

            def observe_member_query(conn, cursor, statement, parameters, context, executemany):
                if "processedSourceVersion" in statement and "LibrarySourceNode" in statement:
                    member_queries.append(statement)

            event.listen(engine, "before_cursor_execute", observe_member_query)
            try:
                outcomes = _drain(pipeline, limit=4)
            finally:
                event.remove(engine, "before_cursor_execute", observe_member_query)
            assert outcomes == ["book"]
            assert member_queries and all("LIMIT" in sql for sql in member_queries)
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset).where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
            )) == member_count
    finally:
        engine.dispose()


def test_directory_batch_rollback_does_not_advance_member_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            album = root / "album"
            album.mkdir()
            for index in range(129):
                (album / f"{index:03}.png").write_bytes(b"png")
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource).where(
                LibraryReadableResource.format == "IMAGE_DIR"
            ))
            assert resource is not None
            db.execute(delete(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            pipeline.queue.request_book_work(
                book_id=resource.book_id,
                work=BookWork(resource_ids=(resource.id,)),
                requested_at=datetime.now(UTC),
            )
            db.commit()
            save = SqlAlchemyBookResourceRepository.save_directory_assets

            def fail_after_write(self, **kwargs):
                save(self, **kwargs)
                raise RuntimeError("injected directory batch failure")

            monkeypatch.setattr(
                SqlAlchemyBookResourceRepository, "save_directory_assets", fail_after_write
            )
            assert build_readable_resource_worker(pipeline).process_once() == "failed"
            task = db.scalar(select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            assert task.directory_member_cursor is None
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset).where(
                LibraryResourceAsset.resource_id == resource.id
            )) == 0
    finally:
        engine.dispose()


def test_resource_step_processes_file_without_a_resource_task_row(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "one.epub").write_bytes(b"epub")
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
            db.commit()

            run = _RecordingResourceRun()
            result = pipeline.process_import_task.process_resource(
                library_id="lib-1",
                resource_id=resource.id,
                source_node_id=resource.source_node_id,
                run=run,
            )
            assert result.outcome == "ok"
            assert (run.started, run.succeeded, run.changed, run.failures) == (
                1,
                1,
                0,
                [],
            )
            assert db.scalar(
                select(func.count()).select_from(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            ) == 0
            asset = db.scalar(select(LibraryResourceAsset))
            assert asset is not None and asset.import_state == "READY"
    finally:
        engine.dispose()


def test_resource_step_processes_directory_without_a_resource_task_row(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            comic = root / "comic"
            comic.mkdir()
            (comic / "01.png").write_bytes(b"png")
            (comic / "02.png").write_bytes(b"png")
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.format == "IMAGE_DIR"
                )
            )
            assert resource is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
            db.commit()

            run = _RecordingResourceRun()
            result = pipeline.process_import_task.process_resource(
                library_id="lib-1",
                resource_id=resource.id,
                source_node_id=resource.source_node_id,
                run=run,
            )
            assert result.outcome == "ok"
            assert (run.started, run.succeeded, run.changed, run.failures) == (
                1,
                1,
                0,
                [],
            )
            assert db.scalar(
                select(func.count()).select_from(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            ) == 0
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryResourceAsset)
                    .where(
                        LibraryResourceAsset.resource_id == resource.id,
                        LibraryResourceAsset.import_state == "READY",
                    )
                )
                == 2
            )
    finally:
        engine.dispose()


def test_resource_step_records_directory_parse_failure_without_a_resource_task_row(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            comic = root / "comic"
            comic.mkdir()
            (comic / "01.png").write_bytes(b"png")
            (comic / "02.png").write_bytes(b"png")
            pipeline, _ = _pipeline(db, adapters=StubFailOnceAdapter({"02.png"}))
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.format == "IMAGE_DIR"
                )
            )
            assert resource is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
            db.commit()

            run = _RecordingResourceRun()
            result = pipeline.process_import_task.process_resource(
                library_id="lib-1",
                resource_id=resource.id,
                source_node_id=resource.source_node_id,
                run=run,
            )

            assert result.outcome == "failed"
            assert run.failures == ["IMAGE_ASSETS_FAILED"]
            assets = {
                asset.source_node_id: asset
                for asset in db.scalars(
                    select(LibraryResourceAsset).where(
                        LibraryResourceAsset.resource_id == resource.id
                    )
                ).all()
            }
            valid_node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "comic/01.png"
                )
            )
            failed_node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "comic/02.png"
                )
            )
            assert valid_node is not None and failed_node is not None
            assert assets[valid_node.id].import_state == "READY"
            assert assets[failed_node.id].import_state == "FAILED"
            assert assets[failed_node.id].failure_reason == "PARSE_FAILED"
            assert db.scalar(
                select(func.count()).select_from(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            ) == 0
    finally:
        engine.dispose()


def test_resource_step_discards_late_result_without_a_resource_task_row(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    run = _RecordingResourceRun()

    class CancelDuringParse(StubAlwaysOkAdapter):
        def parse_file(self, **kwargs: object) -> FileParseResult:
            result = super().parse_file(**kwargs)
            run.current = False
            return result

    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "one.epub").write_bytes(b"epub")
            pipeline, _ = _pipeline(db, adapters=CancelDuringParse())
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
            db.commit()

            result = pipeline.process_import_task.process_resource(
                library_id="lib-1",
                resource_id=resource.id,
                source_node_id=resource.source_node_id,
                run=run,
            )
            assert result.outcome == "cancelled"
            assert (run.started, run.succeeded, run.failures) == (1, 0, [])
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 0
    finally:
        engine.dispose()


def test_resource_step_rejects_changed_input_without_follow_up_task(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"

    class ChangeDuringParse(StubAlwaysOkAdapter):
        def parse_file(self, **kwargs: object) -> FileParseResult:
            result = super().parse_file(**kwargs)
            absolute = kwargs["absolute_path"]
            assert isinstance(absolute, Path)
            absolute.write_bytes(b"epub-changed-during-parse")
            return result

    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "one.epub").write_bytes(b"epub")
            pipeline, _ = _pipeline(db, adapters=ChangeDuringParse())
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            db.execute(
                delete(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
            db.commit()

            run = _RecordingResourceRun()
            result = pipeline.process_import_task.process_resource(
                library_id="lib-1",
                resource_id=resource.id,
                source_node_id=resource.source_node_id,
                run=run,
            )
            assert result.outcome == "failed"
            assert (run.started, run.changed, run.succeeded, run.failures) == (
                1,
                0,
                0,
                ["RESOURCE_INPUT_CHANGED"],
            )
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 0
            assert db.scalar(
                select(func.count()).select_from(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            ) == 0
    finally:
        engine.dispose()


def test_single_consumer_processes_by_created_at_order(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db)
            (root / "a.epub").write_bytes(b"epub")
            (root / "b.epub").write_bytes(b"epub")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            outcomes = _drain(pipeline)
            assert "scan" in outcomes
            assert outcomes.count("book") == 2
            tasks = db.scalars(
                select(LibraryImportTask)
                .where(LibraryImportTask.kind == "IMPORT_BOOK")
                .order_by(LibraryImportTask.created_at.asc())
            ).all()
            assert [t.state for t in tasks] == ["SUCCEEDED", "SUCCEEDED"]
            assert tasks[0].created_at <= tasks[1].created_at
    finally:
        engine.dispose()


def test_discovery_registers_books_without_running_them_mid_scan(
    tmp_path: Path, monkeypatch
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            for index in range(201):
                (root / f"book-{index:03}.epub").write_bytes(b"book")
            db.commit()
            pipeline, _ = _pipeline(db)
            original = pipeline.scan_library_source_tree._filesystem.iter_directory_entries
            root_enumerations = 0
            observed_early_completion = False

            def observing(path):
                nonlocal root_enumerations, observed_early_completion
                entries = original(path)
                if path != root:
                    return entries
                root_enumerations += 1
                if root_enumerations != 1:
                    return entries

                def checked_entries():
                    nonlocal observed_early_completion
                    try:
                        for index, entry in enumerate(entries):
                            if index == 200:
                                completed = db.scalar(
                                    select(func.count())
                                    .select_from(LibraryImportTask)
                                    .where(
                                        LibraryImportTask.kind == "IMPORT_BOOK",
                                        LibraryImportTask.state == "SUCCEEDED",
                                    )
                                )
                                observed_early_completion = bool(completed)
                            yield entry
                    finally:
                        close = getattr(entries, "close", None)
                        if close is not None:
                            close()

                return checked_entries()

            monkeypatch.setattr(
                pipeline.scan_library_source_tree._filesystem,
                "iter_directory_entries",
                observing,
            )
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            assert not observed_early_completion, (
                root_enumerations,
                db.execute(
                    select(LibraryImportTask.kind, LibraryImportTask.state)
                ).all()[:5],
            )
    finally:
        engine.dispose()


def test_flat_category_registers_books_without_running_them_mid_scan(
    tmp_path: Path, monkeypatch
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    shelf = root / "shelf"
    shelf.mkdir(parents=True)
    try:
        with Session(engine) as db:
            _add_library(db, root)
            for index in range(201):
                (shelf / f"book-{index:03}.epub").write_bytes(b"book")
            db.commit()
            pipeline, _ = _pipeline(db)
            scan = pipeline.scan_library_source_tree
            original = scan._directory_batches
            observed_early_completion = False

            def observing(absolute, **kwargs):
                nonlocal observed_early_completion
                batches = original(absolute, **kwargs)
                if absolute != shelf:
                    return batches

                def checked_batches():
                    nonlocal observed_early_completion
                    for index, batch in enumerate(batches):
                        if index == 1:
                            observed_early_completion = bool(
                                db.scalar(
                                    select(func.count())
                                    .select_from(LibraryImportTask)
                                    .where(
                                        LibraryImportTask.kind == "IMPORT_BOOK",
                                        LibraryImportTask.state == "SUCCEEDED",
                                    )
                                )
                            )
                        yield batch

                return checked_batches()

            monkeypatch.setattr(scan, "_directory_batches", observing)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert build_readable_resource_worker(pipeline).process_once() == "scan"
            assert not observed_early_completion
    finally:
        engine.dispose()


def test_discovery_does_not_claim_books_inside_scan(
    tmp_path: Path, monkeypatch
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            for index in range(201):
                (root / f"book-{index:03}.epub").write_bytes(b"book")
            db.commit()
            pipeline, _ = _pipeline(db)
            original = pipeline.queue.claim_next_book
            deferred = False

            def claim(*, started_at):
                nonlocal deferred
                if not deferred and db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.kind == "IMPORT_BOOK")
                ):
                    deferred = True
                    original_error = sqlite3.OperationalError("interrupted")
                    original_error.time_budget_exceeded = True
                    raise OperationalError("claim", (), original_error)
                return original(started_at=started_at)

            monkeypatch.setattr(pipeline.queue, "claim_next_book", claim)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            assert not deferred
            scan = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "SCAN_LIBRARY"
                )
            )
            assert scan is not None and scan.state == "SUCCEEDED"
            monkeypatch.setattr(pipeline.queue, "claim_next_book", original)
            assert worker.process_once() == "book"
    finally:
        engine.dispose()


def test_discovery_parent_stays_succeeded_after_child_terminal_failure(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            shelf = root / "shelf"
            shelf.mkdir()
            for index in range(201):
                (shelf / f"book-{index:03}.epub").write_bytes(b"book")
            db.commit()
            pipeline, _ = _pipeline(db)
            failed = False

            def fail_one_book_terminal(
                _connection, _cursor, statement, parameters, context, _executemany
            ) -> None:
                nonlocal failed
                if (
                    not failed
                    and context.isupdate
                    and context.compiled.statement.table.name == LibraryImportTask.__tablename__
                    and "SUCCEEDED" in parameters
                    and "executionVersion" in statement
                ):
                    failed = True
                    original = sqlite3.OperationalError("interrupted")
                    original.time_budget_exceeded = True
                    raise OperationalError(statement, parameters, original)

            event.listen(engine, "before_cursor_execute", fail_one_book_terminal)
            try:
                pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
                worker = build_readable_resource_worker(pipeline)
                assert worker.process_once() == "scan"
                assert not failed
                assert worker.process_once() == "failed"
            finally:
                event.remove(engine, "before_cursor_execute", fail_one_book_terminal)
            assert failed
            parent = db.scalar(
                select(LibraryImportTask).where(LibraryImportTask.kind == "SCAN_LIBRARY")
            )
            book = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state == "FAILED",
            ))
            assert parent is not None and parent.state == "SUCCEEDED"
            assert book is not None and book.error_summary == "BOOK_COMPLETION_WRITE_FAILED"
            db.commit()
            assert worker.process_once() == "book"
            db.refresh(parent)
            db.refresh(book)
            assert parent.state == "SUCCEEDED"
            assert book.state == "FAILED"
    finally:
        engine.dispose()


def test_pdf_import_persists_inspected_page_count(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db, adapters=StubPdfPageCountAdapter())
            (root / "book.pdf").write_bytes(b"%PDF-test")

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)

            metadata = db.scalar(select(LibraryReadableResourceMetadata))
            assert metadata is not None
            assert metadata.page_count == 7
    finally:
        engine.dispose()


def test_pdf_adapter_upgrade_replaces_persisted_unsplit_tags(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            path = root / "book.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.xmp_metadata = (
                '<x:xmpmeta xmlns:x="adobe:ns:meta/" '
                'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<rdf:RDF><rdf:Description rdf:about="">'
                '<dc:subject><rdf:Bag><rdf:li>儿童文学/奇幻/冒险'
                '</rdf:li></rdf:Bag></dc:subject>'
                '</rdf:Description></rdf:RDF></x:xmpmeta>'
            ).encode()
            writer.write(path)
            pipeline, _ = _pipeline(db, adapters=RegistryResourceAdapterExecutor())
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)

            resource = db.scalar(select(LibraryReadableResource))
            asset = db.scalar(select(LibraryResourceAsset))
            book = db.scalar(select(LibraryBook))
            assert resource is not None and asset is not None and book is not None
            assert resource.adapter_version == "2"
            assert asset.processed_source_version is not None
            old_candidates = json.loads(asset.local_metadata_candidates)
            for candidate in old_candidates:
                if candidate["source"] == "EMBEDDED":
                    candidate["metadata"]["subjects"] = ["儿童文学/奇幻/冒险"]
            asset.local_metadata_candidates = json.dumps(old_candidates, ensure_ascii=False)
            old_version = json.loads(asset.processed_source_version)
            old_version[3] = "1"
            asset.processed_source_version = json.dumps(old_version, separators=(",", ":"))
            resource.adapter_version = "1"
            db.execute(
                delete(LibraryBookFacet).where(LibraryBookFacet.book_id == book.id)
            )
            old_tag = LibraryFacet(
                kind="TAG", name="儿童文学/奇幻/冒险",
                normalized_name="儿童文学/奇幻/冒险",
            )
            db.add(old_tag)
            db.flush()
            db.add(LibraryBookFacet(book_id=book.id, facet_id=old_tag.id))
            db.commit()

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            db.expire_all()
            assert db.get(LibraryReadableResource, resource.id).adapter_version == "2"
            current_asset = db.get(LibraryResourceAsset, asset.id)
            assert current_asset is not None
            embedded = next(
                candidate for candidate in decode_observations(current_asset.local_metadata_candidates)
                if candidate.source == "EMBEDDED"
            )
            assert embedded.metadata.subjects == ("儿童文学", "奇幻", "冒险")
            tags = db.scalars(
                select(LibraryFacet.name)
                .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
                .where(LibraryBookFacet.book_id == book.id, LibraryFacet.kind == "TAG")
                .order_by(LibraryBookFacet.sort_order)
            ).all()
            assert tags == ["儿童文学", "奇幻", "冒险"]
    finally:
        engine.dispose()


def test_startup_marks_running_as_worker_interrupted(tmp_path: Path, caplog) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db)
            task = pipeline.queue.enqueue(kind="SCAN_LIBRARY", library_id="lib-1")
            pipeline.queue.mark_running(task.id, started_at=pipeline.clock.now())
            db.commit()
            worker = build_readable_resource_worker(pipeline)
            assert worker.startup() == 1
            db.refresh(db.get(LibraryImportTask, task.id))
            row = db.get(LibraryImportTask, task.id)
            assert row is not None
            assert row.state == "FAILED"
            assert row.error_summary == "WORKER_INTERRUPTED"
            record = next(record for record in caplog.records if "import.task_interrupted" in record.message)
            assert record.task_id == task.id
            assert record.library_id == "lib-1"
            assert record.task_kind == "SCAN_LIBRARY"
            assert "persisted RUNNING task" in record.message
            assert "without its executor" in record.message
            assert worker.process_once() == "idle"
    finally:
        engine.dispose()


def test_failed_book_stays_terminal_and_later_scan_creates_new_task(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            adapter = StubFailOnceAdapter({"bad.epub"})
            pipeline, _ = _pipeline(db, adapters=adapter)
            (root / "bad.epub").write_bytes(b"x")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            book_task = db.scalar(
                select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK")
            )
            assert book_task is not None
            assert book_task.state == "FAILED"
            assert _drain(pipeline) == []
            (root / "bad.epub").write_bytes(b"repaired")
            adapter._fail_names.clear()
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            assert pipeline.queue.get_book_task(book_task.id).state == "FAILED"
            new_tasks = db.scalars(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.id != book_task.id,
            )).all()
            assert len(new_tasks) == 1 and new_tasks[0].state == "QUEUED"
            assert worker.process_once() == "book"
            assert db.get(LibraryImportTask, book_task.id).state == "FAILED"
    finally:
        engine.dispose()


@pytest.mark.parametrize("scan_target", ("library", "source"))
def test_unchanged_scan_completes_failed_identification_without_reparsing(
    tmp_path: Path, scan_target: str,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "library"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            book_path = root / "Series"
            book_path.mkdir()
            (book_path / "one.epub").write_bytes(b"book")
            db.commit()

            class CountingAdapter(StubAlwaysOkAdapter):
                parse_count = 0

                def parse_file(self, **kwargs):
                    self.parse_count += 1
                    return super().parse_file(**kwargs)

            adapter = CountingAdapter()
            pipeline, _ = _pipeline(db, adapters=adapter)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            original_identify = pipeline.identify_book.execute

            def fail_identification(*_args, **_kwargs):
                raise RuntimeError("recognition failed")

            pipeline.identify_book.execute = fail_identification
            try:
                assert worker.process_once() == "failed"
            finally:
                pipeline.identify_book.execute = original_identify

            old_task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK"
            ))
            assert old_task is not None and old_task.state == "FAILED"
            assert adapter.parse_count == 1
            asset = db.scalar(select(LibraryResourceAsset))
            assert asset is not None and asset.import_state == "READY"
            metadata = db.get(LibraryBookMetadata, old_task.book_id)
            assert metadata is not None and metadata.metadata_state == "FAILED"

            if scan_target == "library":
                pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            else:
                book = db.get(LibraryBook, old_task.book_id)
                assert book is not None
                pipeline.continue_import.execute(
                    ContinueSourceImport(book.source_node_id)
                )
            assert worker.process_once() == (
                "scan" if scan_target == "library" else "continue_source"
            )
            new_tasks = db.scalars(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.id != old_task.id,
            )).all()
            assert len(new_tasks) == 1
            assert new_tasks[0].state == "QUEUED"
            assert worker.process_once() == "book"
            db.expire_all()
            assert old_task.state == "FAILED"
            assert new_tasks[0].state == "SUCCEEDED"
            assert adapter.parse_count == 1
            metadata = db.get(LibraryBookMetadata, old_task.book_id)
            assert metadata is not None and metadata.metadata_state == "COMPLETED"
            assert metadata.processed_revision == metadata.import_revision

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert worker.process_once() == "scan"
            assert worker.process_once() == "idle"
            assert db.scalar(select(func.count()).select_from(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK"
            )) == 2
    finally:
        engine.dispose()


def test_succeeded_not_reexecuted_and_no_duplicate_entities(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, sidecar = _pipeline(db)
            (root / "one.epub").write_bytes(b"epub")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            books1 = db.scalars(select(LibraryBook)).all()
            resources1 = db.scalars(select(LibraryReadableResource)).all()
            assets1 = db.scalars(select(LibraryResourceAsset)).all()
            assert len(books1) == 1
            assert len(resources1) == 1
            assert len(assets1) == 1
            assert assets1[0].import_state == "READY"
            assert resources1[0].import_state == "READY"
            assert sidecar.scheduled
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            assert len(db.scalars(select(LibraryBook)).all()) == 1
            assert len(db.scalars(select(LibraryReadableResource)).all()) == 1
            assert len(db.scalars(select(LibraryResourceAsset)).all()) == 1
            book_tasks = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            ).all()
            assert len(book_tasks) == 1
            assert book_tasks[0].state == "SUCCEEDED"
    finally:
        engine.dispose()


def test_scan_creates_new_fb2_task_when_text_adapter_contract_upgrades(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db)
            (root / "book.fb2").write_text(
                "<?xml version='1.0' encoding='utf-8'?><FictionBook/>",
                encoding="utf-8",
            )
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)

            resource = db.scalar(select(LibraryReadableResource))
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            )
            assert resource is not None
            assert task is not None
            assert resource.adapter_id == "txt"
            assert resource.adapter_version == "2"
            assert resource.format == "FB2"
            assert task.state == "SUCCEEDED"
            original_task_id = task.id

            # Reproduce the previously persisted v1 contract. A formal scan must migrate it;
            # tests and production both go through the public queue/repository boundaries.
            resource.adapter_version = "1"
            resource.format = "TXT"
            db.commit()

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            db.expire_all()

            upgraded = db.get(LibraryReadableResource, resource.id)
            old_task = db.get(LibraryImportTask, original_task_id)
            new_task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.id != original_task_id,
            ))
            interpretation = db.scalar(
                select(LibrarySourceNodeInterpretation).where(
                    LibrarySourceNodeInterpretation.source_node_id
                    == resource.source_node_id
                )
            )
            assert upgraded is not None
            assert upgraded.adapter_id == "txt"
            assert upgraded.adapter_version == "2"
            assert upgraded.format == "FB2"
            assert old_task is not None and old_task.state == "SUCCEEDED"
            assert new_task is not None and new_task.state == "QUEUED"
            assert interpretation is not None
            assert interpretation.reason_code == "ADAPTER_CONTRACT_UPGRADED"

            assert _drain(pipeline) == ["book"]
            db.expire_all()
            assert db.get(LibraryImportTask, original_task_id).state == "SUCCEEDED"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    (
        ("book.mobi", "MOBI"),
        ("book.azw", "AZW"),
        ("book.azw3", "AZW3"),
        ("book.prc", "PRC"),
    ),
)
def test_mobi_family_import_persists_exact_source_format(
    tmp_path: Path,
    filename: str,
    expected_format: str,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db)
            (root / filename).write_bytes(b"mobi-family")

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert _drain(pipeline) == ["scan", "book"]

            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            assert resource.adapter_id == "mobi-family"
            assert resource.adapter_version == "2"
            assert resource.format == expected_format
            assert resource.import_state == "READY"
    finally:
        engine.dispose()


def test_changed_file_observation_creates_new_task_only_once(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db)
            source = root / "one.epub"
            source.write_bytes(b"v1")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)

            node = db.scalar(select(LibrarySourceNode))
            resource = db.scalar(select(LibraryReadableResource))
            asset = db.scalar(select(LibraryResourceAsset))
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            )
            assert node is not None
            assert resource is not None
            assert asset is not None
            assert task is not None
            db.add(
                ReadableResourceNavigationUnit(
                    id="stale-chapter",
                    resource_id=resource.id,
                    asset_id=asset.id,
                    unit_type="chapter",
                    title="Stale chapter",
                    href="stale.xhtml",
                    media_type="application/xhtml+xml",
                    sort_order=0,
                    metadata_json="{}",
                )
            )
            resource_metadata = db.get(
                LibraryReadableResourceMetadata,
                resource.id,
            )
            assert resource_metadata is not None
            resource_metadata.chapter_count = 1
            db.add(
                LibraryResourceAssetNavigation(
                    asset_id=asset.id,
                    chapter_count=1,
                )
            )
            db.commit()
            original_task_id = task.id
            replacement_mtime_ns = source.stat().st_mtime_ns + 1_000_000_000
            source.write_bytes(b"replacement-content")
            os.utime(source, ns=(replacement_mtime_ns, replacement_mtime_ns))

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            db.expire_all()

            refreshed_node = db.get(LibrarySourceNode, node.id)
            refreshed_resource = db.get(LibraryReadableResource, resource.id)
            refreshed_asset = db.get(LibraryResourceAsset, asset.id)
            old_task = db.get(LibraryImportTask, original_task_id)
            new_task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.id != original_task_id,
            ))
            assert refreshed_node is not None
            assert refreshed_node.observed_size_bytes == len(b"replacement-content")
            assert refreshed_node.observed_mtime_ns == replacement_mtime_ns
            assert refreshed_resource is not None
            assert refreshed_resource.import_state == "PENDING"
            assert refreshed_asset is not None
            assert refreshed_asset.import_state == "PENDING"
            assert (
                db.scalar(
                    select(func.count(ReadableResourceNavigationUnit.id)).where(
                        ReadableResourceNavigationUnit.asset_id == asset.id
                    )
                )
                == 0
            )
            assert db.get(LibraryResourceAssetNavigation, asset.id) is None
            refreshed_metadata = db.get(
                LibraryReadableResourceMetadata,
                resource.id,
            )
            assert refreshed_metadata is not None
            assert refreshed_metadata.chapter_count is None
            assert old_task is not None and old_task.state == "SUCCEEDED"
            assert new_task is not None and new_task.state == "QUEUED"

            assert _drain(pipeline) == ["book"]
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert _drain(pipeline) == ["scan"]
            db.expire_all()
            assert db.get(LibraryImportTask, original_task_id).state == "SUCCEEDED"
    finally:
        engine.dispose()


def test_changed_directory_member_preserves_other_ready_assets(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            album = root / "album"
            album.mkdir()
            changed_source = album / "01.mp3"
            changed_source.write_bytes(b"one")
            (album / "02.mp3").write_bytes(b"two")
            pipeline, _ = _pipeline(db)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)

            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            changed_node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "album/01.mp3"
                )
            )
            assert changed_node is not None
            replacement_mtime_ns = changed_source.stat().st_mtime_ns + 1_000_000_000
            changed_source.write_bytes(b"one-replaced")
            os.utime(
                changed_source,
                ns=(replacement_mtime_ns, replacement_mtime_ns),
            )

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            db.expire_all()

            assets = db.execute(
                select(LibraryResourceAsset, LibrarySourceNode)
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
                )
                .where(LibraryResourceAsset.resource_id == resource.id)
            ).all()
            states = {node.name: asset.import_state for asset, node in assets}
            assert states == {"01.mp3": "READY", "02.mp3": "READY"}
            assert db.get(LibraryReadableResource, resource.id).import_state == "READY"

            assert _drain(pipeline) == ["book"]
            db.expire_all()
            assert db.get(LibraryReadableResource, resource.id).import_state == "READY"
            assert (
                db.scalar(
                    select(func.count(LibraryResourceAsset.id)).where(
                        LibraryResourceAsset.resource_id == resource.id,
                        LibraryResourceAsset.import_state == "READY",
                    )
                )
                == 2
            )
    finally:
        engine.dispose()


def test_node_only_then_compatible_files_become_resource(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db)
            empty = root / "mixed"
            empty.mkdir()
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            interp = db.scalar(
                select(LibrarySourceNodeInterpretation)
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id
                    == LibrarySourceNodeInterpretation.source_node_id,
                )
                .where(LibrarySourceNode.relative_path == "mixed")
            )
            assert interp is not None
            assert interp.result == "NODE_ONLY"
            (empty / "a.mp3").write_bytes(b"audio")
            (empty / "b.mp3").write_bytes(b"audio")
            node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "mixed"
                )
            )
            assert node is not None
            pipeline.continue_import.execute(ContinueSourceImport(node.id))
            _drain(pipeline)
            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.source_node_id == node.id
                )
            )
            assert resource is not None
            assert resource.adapter_id == "audiobook-directory"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "missing_entry_policy",
    [MissingEntryPolicy.PRESERVE, MissingEntryPolicy.PRUNE_MISSING],
)
def test_shared_scan_converges_existing_audio_file_resources_to_one_directory(
    tmp_path: Path,
    missing_entry_policy: MissingEntryPolicy,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            album = root / "album"
            album.mkdir()
            source_nodes = SqlAlchemySourceNodeRepository(db)
            books_resources = SqlAlchemyBookResourceRepository(db)
            queue = SqlAlchemyLibraryImportTaskQueue(db)
            observed_at = datetime(2026, 9, 2, tzinfo=UTC)
            directory_node, _ = source_nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=ObservedSourceEntry(
                    relative_path=SourceNodeRelativePath("album"),
                    physical_kind=SourceNodePhysicalKind.DIRECTORY,
                    observed_size_bytes=None,
                    observed_mtime_ns=1,
                    observed_at=observed_at,
                ),
            )
            book_id = books_resources.ensure_book(
                library_id="lib-1",
                source_node_id=directory_node.id,
                title="album",
            )
            audio_adapter = unique_adapter_or_none(match_file_adapters("001.m4a"))
            assert audio_adapter is not None
            for index in range(1, 205):
                name = f"{index:03}.m4a"
                (album / name).write_bytes(b"audio")
                relative = SourceNodeRelativePath(f"album/{name}")
                file_node, _ = source_nodes.insert_if_absent(
                    library_id="lib-1",
                    parent_id=directory_node.id,
                    entry=ObservedSourceEntry(
                        relative_path=relative,
                        physical_kind=SourceNodePhysicalKind.REGULAR_FILE,
                        observed_size_bytes=5,
                        observed_mtime_ns=index,
                        observed_at=observed_at,
                    ),
                )
                resource = books_resources.create_pending_resource(
                    library_id="lib-1",
                    book_id=book_id,
                    source_node_id=file_node.id,
                    adapter=adapter_identity(audio_adapter, source_name=name),
                )
                source_nodes.upsert_interpretation(
                    source_node_id=file_node.id,
                    result="RESOURCE",
                    source="AUTO",
                    adapter_id=audio_adapter.adapter_id.value,
                    adapter_version=audio_adapter.adapter_version,
                    reason_code="UNIQUE_ADAPTER",
                    sample_relative_paths=None,
                    sample_count=None,
                    max_entries_visited=None,
                    max_depth=None,
                    time_budget_ms=None,
                    termination_reason=None,
                    recognized_at=observed_at,
                )
                queue.request_import_resource(
                    library_id="lib-1",
                    resource_id=resource.id,
                    source_node_id=file_node.id,
                )
            (album / "metadata.json").write_text("{}", encoding="utf-8")
            db.commit()

            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_source(
                directory_node.id,
                missing_entry_policy=missing_entry_policy,
            )
            outcomes = _drain(pipeline, limit=500)
            assert outcomes.count("failed") == 204
            assert outcomes.count("book") == 1

            resources = db.scalars(select(LibraryReadableResource)).all()
            assert len(resources) == 1
            assert resources[0].source_node_id == directory_node.id
            assert resources[0].adapter_id == "audiobook-directory"
            assert (
                db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 204
            )
            assert set(
                db.scalars(
                    select(LibrarySourceNodeInterpretation.result)
                    .join(
                        LibrarySourceNode,
                        LibrarySourceNode.id
                        == LibrarySourceNodeInterpretation.source_node_id,
                    )
                    .where(LibrarySourceNode.physical_kind == "REGULAR_FILE")
                )
            ) == {"NODE_ONLY"}
            assert (
                db.scalar(
                    select(LibrarySourceNode.id).where(
                        LibrarySourceNode.relative_path == "album/metadata.json"
                    )
                )
                is None
            )
            book_task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibraryImportTask.book_id == resources[0].book_id,
                    LibraryImportTask.state == "SUCCEEDED",
                ).order_by(LibraryImportTask.created_at.desc())
            )
            assert book_task is not None and book_task.state == "SUCCEEDED"
            assert db.scalar(
                select(func.count())
                .select_from(LibraryImportTask)
                .where(LibraryImportTask.kind == "IMPORT_RESOURCE")
            ) == 0
    finally:
        engine.dispose()


def test_volumes_audiobook_creates_one_book_and_eight_bounded_resources(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    counts = (50, 42, 45, 42, 57, 58, 56, 78)
    names = (
        "鬼吹灯I-1-精绝古城",
        "鬼吹灯I-2-龙岭迷窟",
        "鬼吹灯I-3-云南虫谷",
        "鬼吹灯I-4-昆仑神宫",
        "鬼吹灯II-1-黄皮子坟",
        "鬼吹灯II-2-南海归墟",
        "鬼吹灯II-3-怒晴湘西",
        "鬼吹灯II-4-巫峡棺山",
    )
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            work = root / "鬼吹灯-全八册"
            for name, count in zip(names, counts, strict=True):
                volume = work / name
                volume.mkdir(parents=True)
                for index in range(1, count + 1):
                    (volume / f"{index:02d}.mp3").write_bytes(b"audio")
            db.commit()
            pipeline, _ = _pipeline(db)

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline, limit=1_000)

            assert db.query(LibraryBook).count() == 1
            resources = db.execute(
                select(LibraryReadableResource, LibrarySourceNode)
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryReadableResource.source_node_id,
                )
                .order_by(LibrarySourceNode.relative_path)
            ).all()
            assert len(resources) == 8
            actual_counts = {
                source.name: db.scalar(
                    select(func.count(LibraryResourceAsset.id)).where(
                        LibraryResourceAsset.resource_id == resource.id
                    )
                )
                for resource, source in resources
            }
            assert actual_counts == dict(zip(names, counts, strict=True))
            assert all(
                source.relative_path.startswith("鬼吹灯-全八册/")
                for _resource, source in resources
            )
    finally:
        engine.dispose()


def test_audiobook_reimport_compacts_gapped_chapter_order(tmp_path: Path) -> None:
    class AudioInspector:
        def inspect(self, path: Path) -> AudioFileMetadata:
            return AudioFileMetadata(
                path=path,
                title=path.stem,
                album=None,
                author=None,
                narrator=None,
                duration_ms=60_000,
                codec="mp3",
                bitrate=None,
                sample_rate=None,
                channels=None,
                disc_number=None,
                track_number=int(path.stem),
                chapters=(AudioChapterMetadata(path.stem, 0, 60_000),),
            )

    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            album = root / "album"
            album.mkdir()
            for index in range(1, 4):
                (album / f"{index}.mp3").write_bytes(b"audio")
            db.commit()
            pipeline, _ = _pipeline(
                db,
                adapters=RegistryResourceAdapterExecutor(
                    audio_metadata=AudioInspector()
                ),
            )
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            units = db.scalars(
                select(ReadableResourceNavigationUnit).order_by(
                    ReadableResourceNavigationUnit.sort_order
                )
            ).all()
            assert len(units) == 3
            # Make UPDATE order deterministic: after removing chapter zero,
            # moving chapter one to the remaining count (two) must collide.
            for unit in units:
                unit.id = f"chapter-{unit.sort_order}"
            db.commit()
            source = album / "1.mp3"
            changed = source.stat().st_mtime_ns + 1_000_000_000
            os.utime(source, ns=(changed, changed))
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            outcomes = _drain(pipeline)
            assert "error" not in outcomes
            db.expire_all()
            assert set(db.scalars(select(LibraryImportTask.state))) == {"SUCCEEDED"}
            assert list(
                db.scalars(
                    select(ReadableResourceNavigationUnit.sort_order).order_by(
                        ReadableResourceNavigationUnit.sort_order
                    )
                )
            ) == [0, 1, 2]
            metadata = db.scalar(select(LibraryReadableResourceMetadata))
            assert metadata is not None
            assert metadata.track_count == 3 and metadata.duration_ms == 180_000
            from app.modules.reader.infrastructure.resource_repository import (
                SqlAlchemyReaderResourceRepository,
            )

            reader = SqlAlchemyReaderResourceRepository(db)
            assert reader.get_context(metadata.resource_id) is not None
            reader_assets = reader.list_assets(metadata.resource_id)
            assert [
                db.get(LibrarySourceNode, asset.source_node_id).name
                for asset in reader_assets
            ] == ["1.mp3", "2.mp3", "3.mp3"]
            assert all(asset.mime_type == "audio/mpeg" for asset in reader_assets)
    finally:
        engine.dispose()


def test_audiobook_volume_titles_survive_import_and_reprocessing(
    tmp_path: Path,
) -> None:
    class AudioInspector:
        def inspect(self, path: Path) -> AudioFileMetadata:
            return AudioFileMetadata(
                path=path,
                title="第一集",
                album="音轨专辑",
                author=None,
                narrator=None,
                duration_ms=60_000,
                codec="mp3",
                bitrate=None,
                sample_rate=None,
                channels=None,
                disc_number=None,
                track_number=1,
            )

    names = (
        "鬼吹灯I-1-精绝古城 (全50集)",
        "鬼吹灯I-2-龙岭迷窟 (全42集)",
        "鬼吹灯I-3-云南虫谷 (全45集)",
        "鬼吹灯I-4-昆仑神宫 (全42集)",
        "鬼吹灯II-1-黄皮子坟 (全57集)",
        "鬼吹灯II-2-南海归墟 (全58集)",
        "鬼吹灯II-3-怒晴湘西 (全56集)",
        "鬼吹灯II-4-巫峡棺山 (全78集)",
    )
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            work = root / "鬼吹灯-全八册"
            for name in names:
                volume = work / name
                volume.mkdir(parents=True)
                (volume / "01.mp3").write_bytes(b"audio")
            opf = '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{}</dc:title><dc:creator>天下霸唱</dc:creator></metadata></package>'
            (work / "metadata.opf").write_text(
                opf.format("鬼吹灯全集"), encoding="utf-8"
            )
            db.commit()
            pipeline, _ = _pipeline(
                db,
                adapters=RegistryResourceAdapterExecutor(
                    audio_metadata=AudioInspector()
                ),
            )
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            rows = db.execute(
                select(
                    LibraryReadableResource,
                    LibrarySourceNode,
                    LibraryReadableResourceMetadata,
                )
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryReadableResource.source_node_id,
                )
                .join(LibraryReadableResourceMetadata)
                .order_by(LibrarySourceNode.relative_path)
            ).all()
            assert len(rows) == 8
            assert {metadata.title for _, _, metadata in rows} == set(names)
            book = db.scalar(select(LibraryBookMetadata))
            assert book is not None
            assert (book.title, book.author) == ("鬼吹灯全集", "天下霸唱")

            # Simulate existing bad titles, then re-run the resource job.
            for index, (resource, node, metadata) in enumerate(rows):
                metadata.title = "旧错误标题"
                if index == 0:
                    metadata.title = "手工卷标题"
                    metadata.protected_fields = protect_fields(
                        metadata.protected_fields, ("title",)
                    )
                if index == 1:
                    (work / node.name / "metadata.opf").write_text(
                        opf.format("卷册OPF标题"), encoding="utf-8"
                    )
                asset = db.scalar(
                    select(LibraryResourceAsset).where(
                        LibraryResourceAsset.resource_id == resource.id
                    )
                )
                assert asset is not None
                pipeline.queue.request_import_resource(
                    library_id="lib-1",
                    resource_id=resource.id,
                    source_node_id=resource.source_node_id,
                    changed=True,
                )
            db.commit()
            _drain(pipeline)
            db.expire_all()
            for index, (resource, node, _) in enumerate(rows):
                metadata = db.get(LibraryReadableResourceMetadata, resource.id)
                assert metadata is not None
                assert metadata.title == (
                    "手工卷标题"
                    if index == 0
                    else "卷册OPF标题"
                    if index == 1
                    else node.name
                )
                asset = db.scalar(
                    select(LibraryResourceAsset).where(
                        LibraryResourceAsset.resource_id == resource.id
                    )
                )
                assert asset is not None
                assert all(
                    item.source == "EMBEDDED"
                    for item in decode_observations(asset.local_metadata_candidates)
                )
            assert (book.title, book.author) == ("鬼吹灯全集", "天下霸唱")
    finally:
        engine.dispose()


def test_audiobook_direct_tracks_and_volume_children_form_separate_resources(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            work = root / "作品"
            (work / "CD1").mkdir(parents=True)
            (work / "CD1" / "01.mp3").write_bytes(b"audio")
            volume = work / "分卷一"
            volume.mkdir()
            (volume / "01.mp3").write_bytes(b"audio")
            db.commit()
            pipeline, _ = _pipeline(db)

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)

            resources = db.execute(
                select(LibraryReadableResource, LibrarySourceNode).join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryReadableResource.source_node_id,
                )
            ).all()
            assert {source.relative_path for _resource, source in resources} == {
                "作品",
                "作品/分卷一",
            }
            by_path = {source.relative_path: resource for resource, source in resources}
            direct_assets = db.scalars(
                select(LibrarySourceNode)
                .join(
                    LibraryResourceAsset,
                    LibraryResourceAsset.source_node_id == LibrarySourceNode.id,
                )
                .where(LibraryResourceAsset.resource_id == by_path["作品"].id)
            ).all()
            assert [asset.relative_path for asset in direct_assets] == [
                "作品/CD1/01.mp3"
            ]
            direct_metadata = db.get(
                LibraryReadableResourceMetadata, by_path["作品"].id
            )
            assert direct_metadata is not None
            assert direct_metadata.title == "作品"
    finally:
        engine.dispose()


def test_audiobook_directory_ignores_sidecar_nodes_but_reads_their_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            album = root / "album"
            album.mkdir()
            (album / "01.m4a").write_bytes(b"audio")
            (album / "metadata.json").write_text(
                '{"title": "must not participate in source discovery"}',
                encoding="utf-8",
            )
            (album / "metadata.cover.png").write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
            )
            (album / "metadata.opf").write_text(
                """<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
                <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                  <dc:title>Sidecar audiobook</dc:title>
                  <meta name="cover" content="cover-image" />
                </metadata>
                <manifest><item id="cover-image" href="metadata.cover.png" media-type="image/png" /></manifest>
                </package>""",
                encoding="utf-8",
            )
            (album / "01.opf").write_text(
                """<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
                <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                  <dc:title>单轨标题不得覆盖资源</dc:title>
                </metadata>
                </package>""",
                encoding="utf-8",
            )
            monkeypatch.setattr(
                "app.modules.imports.infrastructure.audio_metadata_inspector.parse_audio_metadata",
                lambda path: AudioFileMetadata(
                    path=path,
                    title="第一集",
                    album=None,
                    author=None,
                    narrator=None,
                    duration_ms=60_000,
                    codec="aac",
                    bitrate=128_000,
                    sample_rate=44_100,
                    channels=2,
                    disc_number=None,
                    track_number=1,
                ),
            )

            pipeline = build_readable_resource_pipeline(
                db,
                Settings(storage_root=str(tmp_path / "storage")),
            )
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)

            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            assert resource.adapter_id == "audiobook-directory"
            assets = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == resource.id
                )
            ).all()
            assert len(assets) == 1
            assert assets[0].sort_key == "01.m4a"
            assert {
                node.relative_path for node in db.scalars(select(LibrarySourceNode))
            } == {"album", "album/01.m4a"}
            metadata = db.get(LibraryReadableResourceMetadata, resource.id)
            assert metadata is not None
            assert metadata.title == "Sidecar audiobook"
            assert metadata.cover_path is not None
            assert metadata.track_count == 1
            assert metadata.duration_ms == 60_000
            assert metadata.chapter_count == 0
            asset_metadata = db.get(LibraryResourceAssetMetadata, assets[0].id)
            assert asset_metadata is not None
            assert asset_metadata.title == "第一集"
            assert asset_metadata.mime_type == "audio/mp4"
            assert asset_metadata.duration_ms == 60_000
            assert asset_metadata.codec == "aac"
            assert asset_metadata.bitrate == 128_000
            assert asset_metadata.sample_rate == 44_100
            assert asset_metadata.channels == 2
            assert asset_metadata.track_number == 1
            unit = db.scalar(
                select(ReadableResourceNavigationUnit).where(
                    ReadableResourceNavigationUnit.resource_id == resource.id
                )
            )
            assert unit is None  # A playable track does not invent an embedded chapter.
    finally:
        engine.dispose()


def test_directory_file_101_filled_on_continue(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db)
            album = root / "album"
            album.mkdir()
            for i in range(100):
                (album / f"t{i:03d}.mp3").write_bytes(b"a")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline, limit=500)
            (album / "t100.mp3").write_bytes(b"a")
            node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "album"
                )
            )
            assert node is not None
            pipeline.continue_import.execute(ContinueSourceImport(node.id))
            _drain(pipeline, limit=500)
            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.source_node_id == node.id
                )
            )
            assert resource is not None
            assets = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == resource.id,
                    LibraryResourceAsset.import_state == "READY",
                )
            ).all()
            assert len(assets) == 101
    finally:
        engine.dispose()


def test_partial_asset_failure_keeps_ready_resource(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            album = root / "album"
            album.mkdir()
            (album / "ok.mp3").write_bytes(b"a")
            (album / "bad.mp3").write_bytes(b"a")
            pipeline, _ = _pipeline(db, adapters=StubFailOnceAdapter({"bad.mp3"}))
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert _drain(pipeline) == ["scan", "failed"]
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            assert resource.import_state == "READY"
            ready = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.import_state == "READY"
                )
            ).all()
            failed = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.import_state == "FAILED"
                )
            ).all()
            assert len(ready) == 1
            assert len(failed) == 1
            ready_id = ready[0].id
            task = db.scalar(
                select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK")
            )
            assert task is not None
            assert task.error_summary == "AUDIO_ASSETS_FAILED"
            assert failed[0].failure_reason == "PARSE_FAILED"
            book_metadata = db.get(LibraryBookMetadata, resource.book_id)
            assert book_metadata is not None and book_metadata.metadata_state == "COMPLETED"
            summary = resource_import_summaries(db, (resource.book_id,))[
                resource.book_id
            ]
            assert (
                summary.ready == 1 and summary.failed == 0 and summary.failed_files == 1
            )

            class RecordingOkAdapter(StubAlwaysOkAdapter):
                def __init__(self) -> None:
                    self.visited: list[str] = []

                def parse_file(self, *, absolute_path: Path, **kwargs):
                    self.visited.append(absolute_path.name)
                    return super().parse_file(absolute_path=absolute_path, **kwargs)

            adapter = RecordingOkAdapter()
            pipeline, _ = _pipeline(db, adapters=adapter)
            new_task = pipeline.queue.request_book_work(
                book_id=resource.book_id,
                work=BookWork(resource_ids=(resource.id,), identify=True),
                requested_at=pipeline.clock.now(),
            )
            assert new_task.id != task.id
            db.commit()
            assert _drain(pipeline) == ["book"]
            assert adapter.visited == ["bad.mp3"]
            db.expire_all()
            assert db.get(LibraryImportTask, task.id).state == "FAILED"
            assert db.get(LibraryImportTask, new_task.id).state == "SUCCEEDED"
            assert db.get(LibraryResourceAsset, ready_id).import_state == "READY"
            assert all(
                asset.import_state == "READY"
                for asset in db.scalars(select(LibraryResourceAsset)).all()
            )
    finally:
        engine.dispose()


def test_no_db_transaction_during_file_parse(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()

            class AssertNoTxnAdapter(StubAlwaysOkAdapter):
                def __init__(self, session: Session) -> None:
                    self._session = session

                def parse_file(
                    self,
                    *,
                    absolute_path: Path,
                    adapter: ResourceAdapterSpec,
                    role: AssetRole,
                    **_kwargs: object,
                ) -> FileParseResult:
                    assert not self._session.in_transaction()
                    return super().parse_file(
                        absolute_path=absolute_path,
                        adapter=adapter,
                        role=role,
                    )

            pipeline, _ = _pipeline(db, adapters=AssertNoTxnAdapter(db))
            (root / "book.epub").write_bytes(b"epub")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            assert resource.import_state == "READY"
    finally:
        engine.dispose()


def test_epub_and_image_directory_adapters(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db)
            (root / "novel.epub").write_bytes(b"epub")
            comic = root / "comic"
            comic.mkdir()
            (comic / "01.png").write_bytes(b"png")
            (comic / "02.png").write_bytes(b"png")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            adapters = {
                r.adapter_id for r in db.scalars(select(LibraryReadableResource)).all()
            }
            assert "epub" in adapters
            assert "image-directory" in adapters
            interpretations = db.scalars(select(LibrarySourceNodeInterpretation)).all()
            assert interpretations
    finally:
        engine.dispose()


class StubBoomAdapter(StubAlwaysOkAdapter):
    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        **_kwargs: object,
    ) -> FileParseResult:
        del absolute_path, adapter, role
        raise RuntimeError("simulated adapter crash")


def test_unexpected_adapter_error_is_contained_as_worker_error(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db, adapters=StubBoomAdapter())
            (root / "crash.epub").write_bytes(b"epub")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            outcomes = _drain(pipeline)
            assert "failed" in outcomes
            failed = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                )
            ).all()
            assert len(failed) == 1
            assert failed[0].error_summary == "WORKER_ERROR"
            assert failed[0].error_summary != "UNHANDLED_ERROR"
            summaries = [
                task.error_summary
                for task in db.scalars(select(LibraryImportTask)).all()
            ]
            assert "UNHANDLED_ERROR" not in summaries
    finally:
        engine.dispose()


def test_modeled_parse_failure_keeps_parse_summary(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db, adapters=StubFailOnceAdapter({"bad.epub"}))
            (root / "bad.epub").write_bytes(b"x")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            outcomes = _drain(pipeline)
            assert "failed" in outcomes
            assert "error" not in outcomes
            failed = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                )
            ).all()
            assert len(failed) == 1
            assert failed[0].error_summary == "PARSE_FAILED"
            assert failed[0].error_summary != "WORKER_ERROR"
    finally:
        engine.dispose()


def test_pipeline_construction_reuses_clock_for_book_continue(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            pipeline = build_readable_resource_pipeline(db)
            assert not hasattr(pipeline, "worker_id")
            assert pipeline.continue_import._clock is pipeline.clock
            worker = build_readable_resource_worker(pipeline)
            assert not hasattr(worker, "_worker_id")
    finally:
        engine.dispose()


def test_reimport_clears_unknown_page_count_without_failing(tmp_path: Path) -> None:
    class ChangingPdfAdapter(StubPdfPageCountAdapter):
        known = True

        def parse_file(self, **kwargs):
            result = super().parse_file(**kwargs)
            if self.known:
                return result
            return replace(
                result, asset=replace(result.asset, technical=AssetTechnicalMetadata())
            )

    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            adapter = ChangingPdfAdapter()
            pipeline, _ = _pipeline(db, adapters=adapter)
            path = root / "book.pdf"
            path.write_bytes(b"%PDF-old")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            assert db.scalar(select(LibraryReadableResourceMetadata)).page_count == 7
            adapter.known = False
            path.write_bytes(b"%PDF-changed-no-page-count")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            db.expire_all()
            assert db.scalar(select(LibraryReadableResourceMetadata)).page_count is None
            assert db.scalar(select(LibraryReadableResource)).import_state == "READY"
    finally:
        engine.dispose()


def test_unknown_audio_duration_is_not_summed_as_zero(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            album = root / "album"
            album.mkdir()
            (album / "01.mp3").write_bytes(b"unknown audio")
            pipeline, _ = _pipeline(db, adapters=StubAlwaysOkAdapter())
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            metadata = db.scalar(select(LibraryReadableResourceMetadata))
            assert metadata.track_count == 1
            assert metadata.duration_ms is None
            assert db.scalar(select(LibraryReadableResource)).import_state == "READY"
    finally:
        engine.dispose()


def test_failed_source_scan_does_not_control_accepted_books_with_literal_names(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            root = tmp_path / "library"
            _add_volumes_library(db, root)
            for name in ("Book%_", "Book%_extra"):
                (root / name).mkdir()
                (root / name / "one.txt").write_text("readable", encoding="utf-8")
            db.commit()
            pipeline, _ = _pipeline(db)
            worker = build_readable_resource_worker(pipeline)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert worker.process_once() == "scan"
            books = db.execute(
                select(LibraryBook, LibrarySourceNode).join(
                    LibrarySourceNode, LibrarySourceNode.id == LibraryBook.source_node_id
                )
            ).all()
            assert {node.name for _, node in books} == {"Book%_", "Book%_extra"}
            first_node = next(node for _, node in books if node.name == "Book%_")
            failed_scan = pipeline.queue.enqueue(
                kind="CONTINUE_SOURCE", library_id="lib-1",
                source_node_id=first_node.id,
            )
            pipeline.queue.mark_running(failed_scan.id, started_at=datetime.now(UTC))
            pipeline.queue.mark_failed(
                failed_scan.id, error_summary="SCAN_FAILED",
                finished_at=datetime.now(UTC),
            )
            db.commit()
            assert _drain(pipeline) == ["book", "book"]
            assert db.get(LibraryImportTask, failed_scan.id).state == "FAILED"
            for book, _ in books:
                task = db.scalar(select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibraryImportTask.book_id == book.id,
                ))
                assert task is not None and task.state == "SUCCEEDED"
                metadata = db.get(LibraryBookMetadata, book.id)
                assert metadata is not None and metadata.metadata_state == "COMPLETED"
    finally:
        engine.dispose()


def test_failed_asset_finishes_book_and_new_import_identifies_new_revision(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    with Session(engine) as db:
        root = tmp_path / "library"
        _add_volumes_library(db, root)
        (root / "Series").mkdir()
        for name in ("one.txt", "two.txt"):
            (root / "Series" / name).write_text("readable", encoding="utf-8")
        db.commit()
        pipeline, _ = _pipeline(db, adapters=StubFailOnceAdapter({"two.txt"}))
        pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
        outcomes = _drain(pipeline)
        assert outcomes == ["scan", "failed"]
        metadata = db.scalar(select(LibraryBookMetadata))
        assert metadata is not None
        assert metadata.metadata_state == "COMPLETED"
        assert metadata.processed_revision == metadata.import_revision
        old_revision = metadata.processed_revision
        failed = db.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK"
            )
        )
        assert failed is not None
        assert failed.error_summary == "PARSE_FAILED"
        failed_asset = db.scalar(
            select(LibraryResourceAsset).where(LibraryResourceAsset.import_state == "FAILED")
        )
        assert failed_asset is not None and failed_asset.failure_reason == "PARSE_FAILED"
        new_task = pipeline.queue.request_book_work(
            book_id=failed.book_id,
            work=BookWork(resource_ids=None, identify=True),
            requested_at=pipeline.clock.now(),
        )
        assert new_task.id != failed.id
        db.commit()
        pipeline, _ = _pipeline(db, adapters=StubAlwaysOkAdapter())
        assert _drain(pipeline) == ["book"]
        db.expire_all()
        assert db.get(LibraryImportTask, failed.id).state == "FAILED"
        assert db.get(LibraryImportTask, new_task.id).state == "SUCCEEDED"
        metadata = db.get(LibraryBookMetadata, failed.book_id)
        assert metadata is not None and metadata.metadata_state == "COMPLETED"
        assert metadata.processed_revision > old_revision
    engine.dispose()


def test_new_volume_only_import_ignores_other_volumes_historical_failure(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            root = tmp_path / "library"
            _add_volumes_library(db, root)
            folder = root / "Series"
            folder.mkdir()
            (folder / "one.txt").write_text("bad", encoding="utf-8")
            (folder / "two.txt").write_text("good", encoding="utf-8")
            db.commit()
            pipeline, _ = _pipeline(db, adapters=StubFailOnceAdapter({"one.txt"}))
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert _drain(pipeline) == ["scan", "failed"]
            old = db.scalar(select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            assert old is not None and old.state == "FAILED"
            good = db.scalar(
                select(LibraryReadableResource)
                .join(LibrarySourceNode, LibrarySourceNode.id == LibraryReadableResource.source_node_id)
                .where(LibrarySourceNode.name == "two.txt")
            )
            assert good is not None
            good_asset = db.scalar(
                select(LibraryResourceAsset).where(LibraryResourceAsset.resource_id == good.id)
            )
            assert good_asset is not None and good_asset.import_state == "READY"
            successful_version = good_asset.processed_source_version
            new = pipeline.queue.request_book_work(
                book_id=good.book_id,
                work=BookWork(resource_ids=(good.id,), identify=True),
                requested_at=pipeline.clock.now(),
            )
            db.commit()
            assert build_readable_resource_worker(pipeline).process_once() == "book"
            db.expire_all()
            assert db.get(LibraryImportTask, new.id).state == "SUCCEEDED"
            assert db.get(LibraryImportTask, old.id).state == "FAILED"
            assert db.get(LibraryResourceAsset, good_asset.id).processed_source_version == successful_version
            assert db.scalar(
                select(LibraryResourceAsset.import_state).where(
                    LibraryResourceAsset.import_state == "FAILED"
                )
            ) == "FAILED"
    finally:
        engine.dispose()


def test_terminal_partial_failure_preserves_identification_until_new_import(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            root = tmp_path / "library"
            _add_volumes_library(db, root)
            folder = root / "Series"
            folder.mkdir()
            for name in ("one.txt", "two.txt"):
                (folder / name).write_text("readable", encoding="utf-8")
            db.commit()
            pipeline, _ = _pipeline(db, adapters=StubFailOnceAdapter({"two.txt"}))
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert _drain(pipeline) == ["scan", "failed"]
            task = db.scalar(
                select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK")
            )
            assert task is not None
            assert task.state == "FAILED"
            assert task.error_summary == "PARSE_FAILED"
            metadata = db.get(LibraryBookMetadata, task.book_id)
            assert metadata is not None and metadata.metadata_state == "COMPLETED"
            assert metadata.processed_revision == metadata.import_revision

            resumed = pipeline.queue.continue_book_task(
                task.id, continued_at=pipeline.clock.now()
            )
            assert resumed is not None and resumed[1]
            assert resumed[0].id != task.id
            assert resumed[0].phase == "RESOURCES"
            db.commit()
            pipeline, _ = _pipeline(db, adapters=StubAlwaysOkAdapter())
            assert _drain(pipeline) == ["book"]
            db.expire_all()
            assert task.state == "FAILED"
            assert db.get(LibraryImportTask, resumed[0].id).state == "SUCCEEDED"
            assert metadata.metadata_state == "COMPLETED"
            assert all(
                asset.import_state == "READY"
                for asset in db.scalars(select(LibraryResourceAsset)).all()
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "count,failed_indexes",
    [
        (127, (0,)),
        (128, (64,)),
        (129, (128,)),
        (200, (0,)),
        (200, (100,)),
        (200, (199,)),
        (260, (0, 129, 259)),
    ],
)
def test_book_resource_failure_does_not_starve_later_resources(
    tmp_path: Path, count: int, failed_indexes: tuple[int, ...],
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "library"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            folder = root / "Series"
            folder.mkdir()
            for index in range(count):
                (folder / f"part-{index:03}.txt").write_text("readable", encoding="utf-8")
            db.commit()

            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resources = db.execute(
                select(LibraryReadableResource.id, LibrarySourceNode.name)
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryReadableResource.source_node_id,
                )
                .order_by(LibraryReadableResource.id)
            ).all()
            assert len(resources) == count
            failed_names = {resources[index].name for index in failed_indexes}
            later_name = resources[-1].name

            class RecordingAdapter(StubFailOnceAdapter):
                def __init__(self) -> None:
                    super().__init__(set(failed_names))
                    self.visited: list[str] = []

                def parse_file(self, *, absolute_path: Path, **kwargs):
                    self.visited.append(absolute_path.name)
                    return super().parse_file(absolute_path=absolute_path, **kwargs)

            adapter = RecordingAdapter()
            pipeline.process_import_task._adapters = adapter
            book = db.scalar(select(LibraryBook))
            assert book is not None
            db.execute(
                delete(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK")
            )
            pipeline.queue.request_book_work(
                book_id=book.id,
                work=BookWork(resource_ids=None, identify=True),
                requested_at=pipeline.clock.now(),
            )
            db.commit()
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "failed"
            db.expire_all()
            task = db.scalar(
                select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK")
            )
            assert task is not None and task.state == "FAILED"
            assert task.resource_cursor == resources[-1].id
            assert set(adapter.visited) == {row.name for row in resources}
            assert len(adapter.visited) == count
            assert later_name in adapter.visited
            assert all(adapter.visited.count(name) == 1 for name in failed_names)
            assert task.error_summary == "PARSE_FAILED"
            metadata = db.get(LibraryBookMetadata, book.id)
            assert metadata is not None and metadata.metadata_state == "COMPLETED"
            assert metadata.processed_revision == metadata.import_revision
            assets = db.scalars(select(LibraryResourceAsset)).all()
            assert sum(asset.import_state == "READY" for asset in assets) == count - len(failed_names)
            assert sum(asset.import_state == "FAILED" for asset in assets) == len(failed_names)
            ready_ids = {asset.source_node_id: asset.id for asset in assets if asset.import_state == "READY"}
            old_task_id = task.id
            book_id = book.id

        # A new task in a new session uses durable asset results, not old task state.
        with Session(engine) as db:
            adapter._fail_names.clear()
            adapter.visited.clear()
            pipeline, _ = _pipeline(db, adapters=adapter)
            new_task = pipeline.queue.request_book_work(
                book_id=book_id,
                work=BookWork(resource_ids=None, identify=True),
                requested_at=pipeline.clock.now(),
            )
            assert new_task.id != old_task_id
            db.commit()
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "book"
            assert set(adapter.visited) == failed_names
            db.expire_all()
            assets = db.scalars(select(LibraryResourceAsset)).all()
            assert len(assets) == count
            assert all(asset.import_state == "READY" for asset in assets)
            assert all(
                db.scalar(
                    select(LibraryResourceAsset.id).where(
                        LibraryResourceAsset.source_node_id == node_id
                    )
                ) == asset_id
                for node_id, asset_id in ready_ids.items()
            )
            assert db.get(LibraryImportTask, old_task_id).state == "FAILED"
            assert db.get(LibraryImportTask, new_task.id).state == "SUCCEEDED"
    finally:
        engine.dispose()


def test_request_during_book_run_is_independent_of_current_cursor(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "library"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            folder = root / "Series"
            folder.mkdir()
            for index in range(129):
                (folder / f"part-{index:03}.txt").write_text("first", encoding="utf-8")
            db.commit()
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resources = db.execute(
                select(LibraryReadableResource.id, LibrarySourceNode.name)
                .join(LibrarySourceNode, LibrarySourceNode.id == LibraryReadableResource.source_node_id)
                .order_by(LibraryReadableResource.id)
            ).all()
            assert len(resources) == 129
            first_id, first_name = resources[0]
            trigger_name = resources[1].name
            book = db.scalar(select(LibraryBook))
            assert book is not None
            db.execute(delete(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            original = pipeline.queue.request_book_work(
                book_id=book.id,
                work=BookWork(resource_ids=None, identify=True),
                requested_at=pipeline.clock.now(),
            )
            db.commit()

            class RequestDuringParse(StubAlwaysOkAdapter):
                def __init__(self) -> None:
                    self.visited: list[str] = []
                    self.requested = False

                def parse_file(self, *, absolute_path: Path, **kwargs):
                    self.visited.append(absolute_path.name)
                    if absolute_path.name == trigger_name and not self.requested:
                        self.requested = True
                        (folder / first_name).write_text("changed revision", encoding="utf-8")
                        pipeline.queue.request_book_work(
                            book_id=book.id,
                            work=BookWork(resource_ids=(first_id,)),
                            requested_at=pipeline.clock.now(),
                        )
                        db.commit()
                    return super().parse_file(absolute_path=absolute_path, **kwargs)

            adapter = RequestDuringParse()
            pipeline.process_import_task._adapters = adapter
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "book"
            task = db.get(LibraryImportTask, original.id)
            assert task is not None and task.state == "SUCCEEDED"
            assert task.resource_cursor == resources[-1].id
            new_task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.id != original.id,
            ))
            assert new_task is not None and new_task.state == "QUEUED"
            assert decode_book_work(new_task.book_work).resource_ids == (first_id,)
            assert worker.process_once() == "book"
            assert adapter.visited.count(first_name) == 2
            assert len(adapter.visited) == 130
            db.expire_all()
            assert task.state == "SUCCEEDED"
            assert db.get(LibraryImportTask, new_task.id).state == "SUCCEEDED"
            assert db.scalar(
                select(func.count()).select_from(LibraryResourceAsset).where(
                    LibraryResourceAsset.import_state == "READY"
                )
            ) == 129
    finally:
        engine.dispose()


def test_new_request_survives_partial_failure_without_replaying_old_task(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "library"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            folder = root / "Series"
            folder.mkdir()
            for name in ("one.txt", "two.txt"):
                (folder / name).write_text("readable", encoding="utf-8")
            db.commit()
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            resources = db.execute(
                select(LibraryReadableResource.id, LibrarySourceNode.name)
                .join(LibrarySourceNode, LibrarySourceNode.id == LibraryReadableResource.source_node_id)
                .order_by(LibraryReadableResource.id)
            ).all()
            assert len(resources) == 2
            failed_name, later_id = resources[0].name, resources[1].id
            book = db.scalar(select(LibraryBook))
            assert book is not None
            db.execute(delete(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            original = pipeline.queue.request_book_work(
                book_id=book.id,
                work=BookWork(resource_ids=None, identify=True),
                requested_at=pipeline.clock.now(),
            )
            db.commit()

            class RequestAndFail(StubFailOnceAdapter):
                def __init__(self) -> None:
                    super().__init__({failed_name})
                    self.requested = False

                def parse_file(self, *, absolute_path: Path, **kwargs):
                    if absolute_path.name == failed_name and not self.requested:
                        self.requested = True
                        pipeline.queue.request_book_work(
                            book_id=book.id,
                            work=BookWork(resource_ids=(later_id,)),
                            requested_at=pipeline.clock.now(),
                        )
                        db.commit()
                    return super().parse_file(absolute_path=absolute_path, **kwargs)

            pipeline.process_import_task._adapters = RequestAndFail()
            assert build_readable_resource_worker(pipeline).process_once() == "failed"
            db.expire_all()
            task = db.get(LibraryImportTask, original.id)
            assert task is not None and task.error_summary == "PARSE_FAILED"
            new_task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.id != original.id,
            ))
            assert new_task is not None and new_task.state == "QUEUED"
            assert decode_book_work(new_task.book_work).resource_ids == (later_id,)
            db.commit()
            pipeline, _ = _pipeline(db, adapters=StubAlwaysOkAdapter())
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "book"
            db.expire_all()
            assert task.state == "FAILED"
            assert db.get(LibraryImportTask, new_task.id).state == "SUCCEEDED"
            assert db.get(LibraryBookMetadata, book.id).metadata_state == "COMPLETED"
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset).where(
                LibraryResourceAsset.import_state == "FAILED"
            )) == 1
    finally:
        engine.dispose()


def test_book_cursor_does_not_advance_when_asset_save_rolls_back(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "library"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            folder = root / "Series"
            folder.mkdir()
            (folder / "one.txt").write_text("readable", encoding="utf-8")
            db.commit()
            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_library("lib-1")
            book = db.scalar(select(LibraryBook))
            assert book is not None
            db.execute(delete(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
            original = pipeline.queue.request_book_work(
                book_id=book.id,
                work=BookWork(resource_ids=None, identify=True),
                requested_at=pipeline.clock.now(),
            )
            db.commit()

            injected = False

            def fail_asset_insert(_conn, _cursor, statement, _parameters, _context, _many):
                nonlocal injected
                if not injected and "LibraryResourceAsset" in statement and statement.lstrip().upper().startswith("INSERT"):
                    injected = True
                    raise sqlite3.OperationalError("injected asset save failure")

            event.listen(engine, "before_cursor_execute", fail_asset_insert)
            try:
                assert build_readable_resource_worker(pipeline).process_once() == "failed"
            finally:
                event.remove(engine, "before_cursor_execute", fail_asset_insert)
            assert injected
            db.expire_all()
            task = db.get(LibraryImportTask, original.id)
            assert task is not None and task.state == "FAILED"
            assert task.resource_cursor is None
            assert db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 0
            new_task = pipeline.queue.request_book_work(
                book_id=book.id,
                work=BookWork(resource_ids=None, identify=True),
                requested_at=pipeline.clock.now(),
            )
            db.commit()
            assert build_readable_resource_worker(pipeline).process_once() == "book"
            assert db.get(LibraryImportTask, original.id).state == "FAILED"
            assert db.get(LibraryImportTask, new_task.id).state == "SUCCEEDED"
            assert db.scalar(
                select(func.count()).select_from(LibraryResourceAsset).where(
                    LibraryResourceAsset.import_state == "READY"
                )
            ) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("retry_failed", [False, True])
def test_comic_import_finalizes_page_count_after_navigation(
    tmp_path: Path, retry_failed: bool
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            archive = root / "comic.zip"
            with ZipFile(archive, "w") as comic:
                comic.writestr("01.png", b"page payload is not read during inspection")
                comic.writestr("02.png", b"page payload is not read during inspection")
            db.commit()
            real_adapters = build_readable_resource_pipeline(db).adapters
            pipeline, _ = _pipeline(
                db,
                adapters=StubFailOnceAdapter({"comic.zip"})
                if retry_failed
                else real_adapters,
            )
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            outcomes = _drain(pipeline)
            if retry_failed:
                assert "failed" in outcomes
                failed = db.scalar(
                    select(LibraryImportTask).where(
                        LibraryImportTask.kind == "IMPORT_BOOK",
                    )
                )
                assert failed is not None
                assert db.scalar(select(LibraryReadableResourceMetadata)) is None
                failed.next_attempt_at = pipeline.clock.now()
                pipeline.queue.request_book_work(
                    book_id=failed.book_id,
                    work=BookWork(resource_ids=None, identify=True),
                    requested_at=pipeline.clock.now(),
                )
                db.commit()
                pipeline, _ = _pipeline(db, adapters=real_adapters)
                outcomes = _drain(pipeline)
            assert "book" in outcomes
            assert "failed" not in outcomes
            db.expire_all()
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None and resource.import_state == "READY"
            metadata = db.get(LibraryReadableResourceMetadata, resource.id)
            assert metadata is not None and metadata.page_count == 2
            units = db.scalars(
                select(ReadableResourceNavigationUnit).where(
                    ReadableResourceNavigationUnit.resource_id == resource.id
                )
            ).all()
            assert len(units) == 2
            assert all(unit.unit_type == "page" for unit in units)

            # A changed archive replaces navigation rather than duplicating pages.
            with ZipFile(archive, "w") as comic:
                comic.writestr("01.png", b"changed archive with one page")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            outcomes = _drain(pipeline)
            assert "book" in outcomes
            assert "failed" not in outcomes
            db.expire_all()
            assert metadata.page_count == 1
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ReadableResourceNavigationUnit)
                    .where(ReadableResourceNavigationUnit.resource_id == resource.id)
                )
                == 1
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "filename,role,unit_type",
    [
        ("book.epub", AssetRole.PRIMARY, "chapter"),
        ("book.zip", AssetRole.PRIMARY, "page"),
        ("album/02.mp3", AssetRole.TRACK, "audio_chapter"),
        ("images/02.png", AssetRole.PAGE, None),
    ],
)
@pytest.mark.parametrize("failed", [False, True])
def test_save_asset_result_has_no_resource_or_queue_side_effects(
    tmp_path: Path,
    monkeypatch,
    filename: str,
    role: AssetRole,
    unit_type: str | None,
    failed: bool,
) -> None:
    from app.contracts.publication_metadata import PublicationMetadata
    from app.modules.imports.infrastructure.local_cover_publication import (
        FilesystemLocalCoverPublication,
    )
    from app.modules.library.public import ResourceNavigationUnitInput
    from app.modules.metadata.public import (
        LocalMetadataCandidate,
        resolve_local_metadata,
    )

    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            source = root / filename
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"inspection supplied by fixture")
            db.commit()
            pipeline = build_readable_resource_pipeline(db)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert build_readable_resource_worker(pipeline).process_once() == "scan"
            node_id = db.scalar(
                select(LibrarySourceNode.id).where(
                    LibrarySourceNode.library_id == "lib-1",
                    LibrarySourceNode.relative_path == filename,
                )
            )
            assert node_id is not None
            resource_id = db.scalar(
                select(LibraryReadableResource.id).where(
                    LibraryReadableResource.source_node_id == node_id
                )
            )
            if resource_id is None:
                resource_id = db.scalar(
                    select(LibraryReadableResource.id).where(
                        LibraryReadableResource.source_node_id
                        == db.scalar(
                            select(LibrarySourceNode.parent_id).where(
                                LibrarySourceNode.id == node_id
                            )
                        )
                    )
                )
            assert resource_id is not None
            resource_row = db.get(LibraryReadableResource, resource_id)
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibraryImportTask.book_id == resource_row.book_id,
                )
            )
            assert task is not None
            task_id = task.id
            book_before = db.get(LibraryBookMetadata, task.book_id)
            assert book_before is not None
            book_state_before = (
                book_before.metadata_state,
                book_before.metadata_pending,
                book_before.processed_revision,
            )
            process = pipeline.process_import_task
            context = process.load_resource_context(
                resource_id=resource_id, source_node_id=node_id
            )
            assert context is not None and context.adapter is not None
            pipeline.uow.release_before_io()
            parsed = StubAlwaysOkAdapter().parse_file(
                absolute_path=source,
                adapter=context.adapter,
                role=role,
            )
            assert parsed.asset is not None
            local = resolve_local_metadata(
                (
                    LocalMetadataCandidate(
                        "EMBEDDED",
                        PublicationMetadata(title="Fixture title", language="en"),
                    ),
                )
            )
            parsed = replace(
                parsed,
                ok=not failed,
                local_metadata=local,
                error_code="FIXTURE_PARSE_FAILED" if failed else None,
                asset=None
                if failed
                else replace(
                    parsed.asset,
                    duration_ms=1200 if role is AssetRole.TRACK else None,
                    technical=AssetTechnicalMetadata(
                        track_number=2 if role is AssetRole.TRACK else None
                    ),
                    navigation_units=(
                        ResourceNavigationUnitInput(
                            unit_type=unit_type,
                            title="Chapter",
                            href="#1",
                            media_type=None,
                            sort_order=0,
                            start_ms=0 if role is AssetRole.TRACK else None,
                            end_ms=1200 if role is AssetRole.TRACK else None,
                        ),
                    )
                    if unit_type
                    else (),
                ),
            )

            def forbidden(*args, **kwargs):
                raise AssertionError("asset save invoked a resource/queue side effect")

            with monkeypatch.context() as patch:
                for method in (
                    "apply_local_metadata",
                    "refresh_resource_local_metadata",
                    "refresh_audio_resource_aggregates",
                    "mark_resource_ready",
                    "mark_resource_failed",
                    "set_resource_page_count",
                ):
                    patch.setattr(SqlAlchemyBookResourceRepository, method, forbidden)
                patch.setattr(FilesystemLocalCoverPublication, "publish", forbidden)
                patch.setattr(FilesystemLocalCoverPublication, "prepare", forbidden)
                patch.setattr(
                    SqlAlchemyLibraryImportTaskQueue, "mark_succeeded", forbidden
                )
                patch.setattr(
                    SqlAlchemyLibraryImportTaskQueue, "mark_failed", forbidden
                )
                with pipeline.uow.transaction():
                    asset_id = process.save_asset_result(
                        parsed=parsed,
                        library_id="lib-1",
                        resource_id=resource_id,
                        source_node_id=node_id,
                        role=role,
                        sort_key=filename,
                    )
            db.expire_all()
            asset = db.get(LibraryResourceAsset, asset_id)
            assert asset is not None and asset.import_state == (
                "FAILED" if failed else "READY"
            )
            assert asset.failure_reason == ("FIXTURE_PARSE_FAILED" if failed else None)
            assert db.get(LibraryImportTask, task_id).state == "QUEUED"
            book_after = db.get(LibraryBookMetadata, task.book_id)
            assert book_after is not None
            assert (
                book_after.metadata_state,
                book_after.metadata_pending,
                book_after.processed_revision,
            ) == book_state_before
            assert db.scalar(
                select(func.count())
                .select_from(LibraryResourceAsset)
                .where(LibraryResourceAsset.resource_id == resource_id)
            ) == 1
            assert (
                db.get(LibraryReadableResource, resource_id).import_state == "PENDING"
            )
            assert db.get(LibraryReadableResourceMetadata, resource_id) is None
            units = db.scalars(
                select(ReadableResourceNavigationUnit).where(
                    ReadableResourceNavigationUnit.asset_id == asset_id,
                )
            ).all()
            assert len(units) == (1 if unit_type and not failed else 0)
            if not failed:
                assert (
                    decode_observations(asset.local_metadata_candidates)[
                        0
                    ].metadata.title
                    == "Fixture title"
                )
                assert (
                    db.get(LibraryResourceAssetMetadata, asset_id).title == source.stem
                )
            pipeline.uow.release_before_io()
            with pipeline.uow.transaction():
                process.finalize_resource(
                    parsed=parsed,
                    local_metadata=local,
                    resource_id=resource_id,
                    role=role,
                )
            db.expire_all()
            assert db.get(LibraryImportTask, task_id).state == "QUEUED"
            assert db.get(LibraryReadableResource, resource_id).import_state == (
                "FAILED" if failed else "READY"
            )
            if not failed:
                metadata = db.get(LibraryReadableResourceMetadata, resource_id)
                assert metadata.title == "Fixture title" and metadata.language == "en"
                if unit_type == "page":
                    assert metadata.page_count == 1
                if role is AssetRole.TRACK:
                    assert (
                        metadata.track_count,
                        metadata.chapter_count,
                        metadata.duration_ms,
                    ) == (1, 1, 1200)
                    assert db.get(LibraryResourceAsset, asset_id).sequence_index == 0
            pipeline.uow.release_before_io()
            with pipeline.uow.transaction():
                assert (
                    process.save_asset_result(
                        parsed=parsed,
                        library_id="lib-1",
                        resource_id=resource_id,
                        source_node_id=node_id,
                        role=role,
                        sort_key=filename,
                    )
                    == asset_id
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "invalid_target,expected_code",
    [
        ("cross_library", "CROSS_LIBRARY"),
        ("outside", "ASSET_OUT_OF_RESOURCE_SCOPE"),
        ("directory", "ASSET_SOURCE_NOT_REGULAR_FILE"),
        ("missing", "SOURCE_NODE_NOT_FOUND"),
    ],
)
def test_save_asset_result_preserves_topology_validation(
    tmp_path: Path,
    invalid_target: str,
    expected_code: str,
) -> None:
    from app.modules.library.public import ReadableResourceTopologyError

    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "images").mkdir()
            (root / "images/1.png").write_bytes(b"image")
            (root / "outside.epub").write_bytes(b"book")
            db.commit()
            pipeline = build_readable_resource_pipeline(db)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert build_readable_resource_worker(pipeline).process_once() == "scan"
            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.format == "IMAGE_DIR"
                )
            )
            nodes = {
                node.relative_path: node.id
                for node in db.scalars(select(LibrarySourceNode))
            }
            context = pipeline.process_import_task.load_resource_context(
                resource_id=resource.id,
                source_node_id=nodes["images/1.png"],
            )
            assert context is not None and context.adapter is not None
            resource_id = resource.id
            pipeline.uow.release_before_io()
            parsed = StubAlwaysOkAdapter().parse_file(
                absolute_path=root / "images/1.png",
                adapter=context.adapter,
                role=AssetRole.PAGE,
            )
            source_id = {
                "cross_library": nodes["images/1.png"],
                "outside": nodes["outside.epub"],
                "directory": nodes["images"],
                "missing": "missing",
            }[invalid_target]
            with (
                pytest.raises(ReadableResourceTopologyError) as error,
                pipeline.uow.transaction(),
            ):
                pipeline.process_import_task.save_asset_result(
                    parsed=parsed,
                    library_id="other-library"
                    if invalid_target == "cross_library"
                    else "lib-1",
                    resource_id=resource_id,
                    source_node_id=source_id,
                    role=AssetRole.PAGE,
                    sort_key="ignored",
                )
            assert error.value.code.value == expected_code
            assert (
                db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 0
            )
            assert (
                db.get(LibraryReadableResource, resource_id).import_state == "PENDING"
            )
    finally:
        engine.dispose()


def test_book_requests_get_distinct_ids_and_reuse_valid_resources(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_volumes_library(db, root)
            book = root / "Book"
            book.mkdir()
            for name in ("a.epub", "b.epub"):
                (book / name).write_bytes(b"book")
            db.commit()
            pipeline, _ = _pipeline(db)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            tasks = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            ).all()
            assert len(tasks) == 1
            book_id = tasks[0].book_id
            task_id = tasks[0].id
            resources = db.scalars(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.book_id == book_id
                )
            ).all()
            assert len(resources) == 2
            request_ids = set()
            for _ in range(20):
                request = pipeline.queue.request_book_work(
                    book_id=book_id,
                    work=BookWork(identify=True),
                    requested_at=pipeline.clock.now(),
                )
                assert request.id != task_id
                request_ids.add(request.id)
            assert len(request_ids) == 20
            db.commit()
            assert worker.process_once() == "book"
            db.expire_all()
            assert [resource.import_state for resource in resources] == ["READY", "READY"]
            metadata = db.get(LibraryBookMetadata, book_id)
            assert metadata is not None and metadata.metadata_state == "COMPLETED"
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.kind == "IMPORT_BOOK")
                )
                == 21
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(
                        LibraryImportTask.kind.in_(
                            ("IMPORT_RESOURCE", "IDENTIFY_BOOK")
                        )
                    )
                )
                == 0
            )
            assert db.get(LibraryImportTask, task_id).state == "SUCCEEDED"
            assert _drain(pipeline) == ["book"] * 20
            assert all(db.get(LibraryImportTask, task_id).state == "SUCCEEDED"
                       for task_id in request_ids)
    finally:
        engine.dispose()


def test_resource_committed_asset_survives_interruption_before_completion(
    tmp_path: Path, monkeypatch
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    parsed_paths = []

    class CountAdapter(StubAlwaysOkAdapter):
        def parse_file(self, **kwargs):
            parsed_paths.append(kwargs["absolute_path"])
            return super().parse_file(**kwargs)

    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "book.epub").write_bytes(b"book")
            db.commit()
            pipeline, _ = _pipeline(db, adapters=CountAdapter())
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            task_id = db.scalar(
                select(LibraryImportTask.id).where(
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            )

            def interrupted(*args, **kwargs):
                raise KeyboardInterrupt("process interrupted after asset commit")

            with monkeypatch.context() as patch:
                patch.setattr(pipeline.queue, "finish_book_run", interrupted)
                with pytest.raises(KeyboardInterrupt):
                    worker.process_once()
            asset = db.scalar(select(LibraryResourceAsset))
            assert asset.processed_source_version is not None
            asset_id = asset.id
        with Session(engine) as db:
            pipeline, _ = _pipeline(db, adapters=CountAdapter())
            worker = build_readable_resource_worker(pipeline)
            assert worker.startup() == 1
            assert db.get(LibraryImportTask, task_id).state == "FAILED"
            new_task = pipeline.queue.continue_book_task(
                task_id, continued_at=pipeline.clock.now()
            )
            assert new_task is not None and new_task[0].id != task_id
            db.commit()
            assert worker.process_once() == "book"
            assert db.get(LibraryImportTask, task_id).state == "FAILED"
            assert db.get(LibraryImportTask, new_task[0].id).state == "SUCCEEDED"
            assert db.scalar(select(LibraryResourceAsset.id)) == asset_id
            assert len(parsed_paths) == 1
    finally:
        engine.dispose()


def test_terminal_timeout_fails_once_and_new_task_reuses_committed_asset(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    parsed_paths: list[Path] = []

    class CountAdapter(StubAlwaysOkAdapter):
        def parse_file(self, **kwargs):
            parsed_paths.append(kwargs["absolute_path"])
            return super().parse_file(**kwargs)

    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "book.epub").write_bytes(b"book")
            db.commit()
            pipeline, _ = _pipeline(db, adapters=CountAdapter())
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK"
            ))
            assert task is not None
            attempts = 0

            def timeout_terminal(_connection, _cursor, statement, parameters, context, _many):
                nonlocal attempts
                if (
                    context.isupdate
                    and context.compiled.statement.table.name == LibraryImportTask.__tablename__
                    and task.id in parameters and "SUCCEEDED" in parameters
                ):
                    attempts += 1
                    original = sqlite3.OperationalError("interrupted")
                    original.time_budget_exceeded = True
                    raise OperationalError(statement, parameters, original)

            event.listen(engine, "before_cursor_execute", timeout_terminal)
            try:
                assert worker.process_once() == "failed"
                assert len(parsed_paths) == 1
                asset = db.scalar(select(LibraryResourceAsset))
                assert asset is not None and asset.processed_source_version is not None
                asset_id = asset.id
                assert attempts == 1
                db.expire_all()
                assert db.get(LibraryImportTask, task.id).state == "FAILED"
            finally:
                event.remove(engine, "before_cursor_execute", timeout_terminal)
            new_task = pipeline.queue.continue_book_task(
                task.id, continued_at=pipeline.clock.now()
            )
            assert new_task is not None and new_task[0].id != task.id
            db.commit()
            assert worker.process_once() == "book"
            assert len(parsed_paths) == 1
            assert db.scalar(select(LibraryResourceAsset.id)) == asset_id
            assert db.get(LibraryImportTask, task.id).state == "FAILED"
            assert db.get(LibraryImportTask, new_task[0].id).state == "SUCCEEDED"
    finally:
        engine.dispose()


@pytest.mark.parametrize("scan_during_parse", [False, True])
def test_resource_changes_during_parse_fail_current_execution(
    tmp_path: Path, scan_during_parse: bool
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    calls = []

    class ChangeAdapter(StubAlwaysOkAdapter):
        def parse_file(self, **kwargs):
            result = super().parse_file(**kwargs)
            calls.append(kwargs["absolute_path"])
            if len(calls) == 1:
                kwargs["absolute_path"].write_bytes(b"new input version")
                if scan_during_parse:
                    with Session(engine) as other:
                        other_pipeline, _ = _pipeline(other)
                        other_pipeline.scan_library_source_tree.execute_library("lib-1")
            return result

    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "book.epub").write_bytes(b"old")
            db.commit()
            pipeline, _ = _pipeline(db, adapters=ChangeAdapter())
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            assert worker.process_once() == "failed"
            db.expire_all()
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            )
            assert task is not None and task.state == "FAILED"
            assert db.scalar(select(LibraryResourceAsset)) is None
            if not scan_during_parse:
                assert worker.process_once() == "idle"
                pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            outcomes = _drain(pipeline)
            assert "book" in outcomes
            db.expire_all()
            assert task.state == "FAILED"
            assert db.scalar(select(func.count()).select_from(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state == "SUCCEEDED",
            )) >= 1
            assert len(calls) == 2
            assert db.scalar(
                select(LibraryResourceAsset)
            ).processed_source_version.startswith("[17,")
    finally:
        engine.dispose()


@pytest.mark.parametrize("delete_resource", [False, True])
def test_resource_cancelled_during_parse_does_not_resurrect_data(
    tmp_path: Path, delete_resource: bool
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"

    class CancelAdapter(StubAlwaysOkAdapter):
        def parse_file(self, **kwargs):
            result = super().parse_file(**kwargs)
            with Session(engine) as other:
                task = other.scalar(
                    select(LibraryImportTask).where(
                        LibraryImportTask.kind == "IMPORT_BOOK"
                    )
                )
                assert task is not None
                if delete_resource:
                    resource = other.scalar(select(LibraryReadableResource))
                    assert resource is not None
                    other.delete(resource)
                else:
                    other.delete(task)
                other.commit()
            return result

    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "book.epub").write_bytes(b"book")
            db.commit()
            pipeline, _ = _pipeline(db, adapters=CancelAdapter())
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            assert worker.process_once() == ("failed" if delete_resource else "cancelled")
            db.expire_all()
            assert db.scalar(select(LibraryResourceAsset)) is None
            remaining = db.scalar(
                select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK")
            )
            assert (remaining is not None) is delete_resource
            if remaining is not None:
                assert remaining.state == "FAILED"
            if delete_resource:
                assert db.scalar(select(LibraryReadableResource)) is None
    finally:
        engine.dispose()


def test_resource_change_after_asset_commit_is_not_consumed_by_completion(
    tmp_path: Path, monkeypatch
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            source = root / "book.epub"
            source.write_bytes(b"old")
            db.commit()
            pipeline, _ = _pipeline(db)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            original = pipeline.queue.finish_book_run
            new_task_id: str | None = None

            def changed(task_id, *, execution_version, finished_at):
                nonlocal new_task_id
                task = pipeline.queue.get_book_task(task_id)
                assert task is not None
                resource = db.scalar(select(LibraryReadableResource))
                assert resource is not None
                source.write_bytes(b"updated")
                requested = pipeline.queue.request_import_resource(
                    library_id=task.library_id,
                    resource_id=resource.id,
                    source_node_id=resource.source_node_id,
                    changed=True,
                )
                assert requested is not None and requested.id != task_id
                new_task_id = requested.id
                return original(
                    task_id,
                    execution_version=execution_version,
                    finished_at=finished_at,
                )

            with monkeypatch.context() as patch:
                patch.setattr(pipeline.queue, "finish_book_run", changed)
                assert worker.process_once() == "book"
            db.expire_all()
            task = db.scalar(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.id != new_task_id,
            ))
            assert task is not None and task.state == "SUCCEEDED"
            assert new_task_id is not None
            assert db.get(LibraryImportTask, new_task_id).state == "QUEUED"
            first_version = db.scalar(
                select(LibraryResourceAsset)
            ).processed_source_version
            assert first_version.startswith("[3,")
            pipeline.scan_library_source_tree.execute_library("lib-1")
            assert "book" in _drain(pipeline)
            db.expire_all()
            assert task.state == "SUCCEEDED"
            assert db.get(LibraryImportTask, new_task_id).state == "SUCCEEDED"
            assert db.scalar(
                select(LibraryResourceAsset)
            ).processed_source_version.startswith("[7,")
    finally:
        engine.dispose()
