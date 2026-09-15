"""Integration coverage for ADR 0018 single-consumer ContinueImport."""

from __future__ import annotations

import base64
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select
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
from app.models.library import Library, ReadableResourceNavigationUnit
from app.modules.imports.application.audio_types import (
    AudioChapterMetadata,
    AudioFileMetadata,
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
    adapter_identity,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
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
            assert outcomes.count("ok") >= 2
            tasks = db.scalars(
                select(LibraryImportTask)
                .where(LibraryImportTask.kind == "IMPORT_RESOURCE")
                .order_by(LibraryImportTask.created_at.asc())
            ).all()
            assert [t.state for t in tasks] == ["SUCCEEDED", "SUCCEEDED"]
            assert tasks[0].created_at <= tasks[1].created_at
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


def test_startup_marks_running_as_worker_interrupted(tmp_path: Path) -> None:
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
            assert worker.process_once() == "idle"
    finally:
        engine.dispose()


def test_failed_asset_is_requeued_by_the_shared_scan_not_the_request(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            pipeline, _ = _pipeline(db, adapters=StubFailOnceAdapter({"bad.epub"}))
            (root / "bad.epub").write_bytes(b"x")
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            _drain(pipeline)
            failed = db.scalars(
                select(LibraryImportTask).where(LibraryImportTask.state == "FAILED")
            ).all()
            assert len(failed) == 1
            assert _drain(pipeline) == []
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"
            requeued = db.scalars(
                select(LibraryImportTask).where(LibraryImportTask.state == "QUEUED")
            ).all()
            assert any(t.kind == "IMPORT_RESOURCE" for t in requeued)
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
            asset_tasks = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            ).all()
            assert len(asset_tasks) == 1
            assert asset_tasks[0].state == "SUCCEEDED"
    finally:
        engine.dispose()


def test_scan_requeues_existing_fb2_when_text_adapter_contract_upgrades(
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
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
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
            requeued = db.get(LibraryImportTask, original_task_id)
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
            assert requeued is not None
            assert requeued.state == "QUEUED"
            assert interpretation is not None
            assert interpretation.reason_code == "ADAPTER_CONTRACT_UPGRADED"

            assert _drain(pipeline) == ["ok", "identified"]
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
            assert _drain(pipeline) == ["scan", "ok", "identified"]

            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            assert resource.adapter_id == "mobi-family"
            assert resource.adapter_version == "2"
            assert resource.format == expected_format
            assert resource.import_state == "READY"
    finally:
        engine.dispose()


def test_changed_file_observation_invalidates_and_requeues_only_once(
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
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
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
            requeued = db.get(LibraryImportTask, original_task_id)
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
            assert requeued is not None
            assert requeued.state == "QUEUED"

            assert _drain(pipeline) == ["ok", "identified"]
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert _drain(pipeline) == ["scan", "identified"]
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
            assert states == {"01.mp3": "PENDING", "02.mp3": "READY"}
            assert db.get(LibraryReadableResource, resource.id).import_state == "READY"

            assert _drain(pipeline) == ["ok", "identified"]
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
                queue.ensure_import_asset_task(
                    library_id="lib-1",
                    resource_id=resource.id,
                    source_node_id=file_node.id,
                    role=audio_adapter.asset_role,
                )
            (album / "metadata.json").write_text("{}", encoding="utf-8")
            db.commit()

            pipeline, _ = _pipeline(db)
            pipeline.scan_library_source_tree.execute_source(
                directory_node.id,
                missing_entry_policy=missing_entry_policy,
            )
            assert _drain(pipeline, limit=500) == ["ok"] * 204 + ["identified"]

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
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.resource_id != resources[0].id)
                )
                == 0
            )
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

            # Simulate existing bad titles, then re-run the existing asset jobs.
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
                pipeline.queue.requeue_import_asset_task(
                    library_id="lib-1",
                    resource_id=resource.id,
                    source_node_id=asset.source_node_id,
                    role=AssetRole.TRACK,
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
                path = next(
                    item
                    for item in decode_observations(asset.local_metadata_candidates)
                    if item.source == "PATH"
                )
                assert path.metadata.volume_title == node.name
                assert path.metadata.authors == ()
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
            _drain(pipeline)
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
            summary = resource_import_summaries(db, (resource.book_id,))[
                resource.book_id
            ]
            assert (
                summary.ready == 1 and summary.failed == 0 and summary.failed_files == 1
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
            assert "error" in outcomes
            failed = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE",
                    LibraryImportTask.state == "FAILED",
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
                    LibraryImportTask.kind == "IMPORT_RESOURCE",
                    LibraryImportTask.state == "FAILED",
                )
            ).all()
            assert len(failed) == 1
            assert failed[0].error_summary == "PARSE_FAILED"
            assert failed[0].error_summary != "WORKER_ERROR"
    finally:
        engine.dispose()


def test_pipeline_construction_omits_worker_id_and_continue_import_clock(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            pipeline = build_readable_resource_pipeline(db)
            assert not hasattr(pipeline, "worker_id")
            assert not hasattr(pipeline.continue_import, "_clock")
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


def test_book_completion_waits_for_overlapping_scan_and_cancellation_survives_restart(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
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
        first, first_node = next(row for row in books if row[1].name == "Book%_")
        scan = pipeline.queue.enqueue(
            kind="CONTINUE_SOURCE", library_id="lib-1", source_node_id=first_node.id
        )
        db.commit()
        tasks = db.scalars(
            select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_RESOURCE")
        ).all()
        for task in tasks:
            pipeline.queue.mark_running(task.id, started_at=datetime.now(UTC))
            db.commit()
            assert pipeline.process_import_task.execute(task.id).outcome == "ok"
        # Asset completion commits independently; a worker maintenance pass
        # prepares book identification outside the write transaction.
        prepared = pipeline.queue.prepare_book_identifications()
        pipeline.uow.release_before_io()
        with pipeline.uow.transaction():
            pipeline.queue.enqueue_book_identifications(prepared)
        active = db.scalars(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "IDENTIFY_BOOK",
                LibraryImportTask.state == "QUEUED",
            )
        ).all()
        assert len(active) == 1
        assert active[0].source_node_id != first_node.id
        pipeline.queue.mark_failed(
            scan.id, error_summary="SCAN_FAILED", finished_at=datetime.now(UTC)
        )
        db.commit()
        prepared = pipeline.queue.prepare_book_identifications()
        pipeline.uow.release_before_io()
        with pipeline.uow.transaction():
            pipeline.queue.enqueue_book_identifications(prepared)
        active = db.scalars(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "IDENTIFY_BOOK",
                LibraryImportTask.state == "QUEUED",
            )
        ).all()
        assert len(active) == 2
        pipeline.queue.delete_tasks_for_source_nodes((first_node.id,))
        db.commit()
        pipeline.queue.fail_interrupted_tasks_on_startup(finished_at=datetime.now(UTC))
        db.commit()
        assert _drain(pipeline) == ["identified"]
        db.expire_all()
        metadata = db.get(LibraryBookMetadata, first.id)
        assert metadata is not None and not metadata.metadata_pending
        assert metadata.processed_revision == -1
        assert metadata.metadata_state == "WAITING_IMPORT"
    engine.dispose()


def test_failed_asset_finishes_book_and_retry_identifies_new_revision(
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
        assert outcomes.count("identified") == 1
        metadata = db.scalar(select(LibraryBookMetadata))
        assert metadata is not None and metadata.metadata_state == "COMPLETED"
        old_revision = metadata.processed_revision
        failed = db.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_RESOURCE",
                LibraryImportTask.state == "FAILED",
            )
        )
        assert failed is not None
        pipeline.queue.requeue_failed_task(failed.id)
        db.commit()
        pipeline, _ = _pipeline(db, adapters=StubAlwaysOkAdapter())
        assert _drain(pipeline) == ["ok", "identified"]
        db.expire_all()
        assert metadata.processed_revision > old_revision
        assert metadata.metadata_state == "COMPLETED"
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
                        LibraryImportTask.kind == "IMPORT_RESOURCE",
                        LibraryImportTask.state == "FAILED",
                    )
                )
                assert failed is not None
                assert db.scalar(select(LibraryReadableResourceMetadata)) is None
                pipeline.queue.requeue_failed_task(failed.id)
                db.commit()
                pipeline, _ = _pipeline(db, adapters=real_adapters)
                outcomes = _drain(pipeline)
            assert "ok" in outcomes
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
            assert "ok" in outcomes
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
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind.in_(("IMPORT_RESOURCE", "IMPORT_ASSET"))
                )
            )
            assert task is not None
            task_id, resource_id, node_id = (
                task.id,
                task.resource_id,
                task.source_node_id,
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


def test_resource_requests_coalesce_and_book_waits_for_both_resources(
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
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            ).all()
            assert len(tasks) == 2 and len({task.resource_id for task in tasks}) == 2
            for task in tasks:
                assert task.role is None
                assert (
                    task.source_node_id
                    == db.get(LibraryReadableResource, task.resource_id).source_node_id
                )
                for _ in range(20):
                    request = pipeline.queue.request_import_resource(
                        library_id="lib-1",
                        resource_id=task.resource_id,
                        source_node_id=task.source_node_id,
                    )
                    assert request.id == task.id
            db.commit()
            assert pipeline.queue.prepare_book_identifications() == ()
            assert worker.process_once() == "ok"
            assert pipeline.queue.prepare_book_identifications() == ()
            assert worker.process_once() == "ok"
            assert len(pipeline.queue.prepare_book_identifications()) == 1
            _drain(pipeline)
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.kind == "IMPORT_RESOURCE")
                )
                == 2
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.kind == "IDENTIFY_BOOK")
                )
                == 1
            )
    finally:
        engine.dispose()


def test_resource_committed_asset_survives_interruption_before_completion(
    tmp_path: Path, monkeypatch
) -> None:
    from app.modules.imports.application.readable_resource.continue_import import (
        ContinueImportTask,
    )

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
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )

            def interrupted(*args, **kwargs):
                raise KeyboardInterrupt("process interrupted after asset commit")

            with monkeypatch.context() as patch:
                patch.setattr(pipeline.queue, "mark_succeeded", interrupted)
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
            pipeline.continue_import.execute(ContinueImportTask(task_id))
            assert worker.process_once() == "ok"
            assert db.get(LibraryImportTask, task_id).state == "SUCCEEDED"
            assert db.scalar(select(LibraryResourceAsset.id)) == asset_id
            assert len(parsed_paths) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("scan_during_parse", [False, True])
def test_resource_changes_during_parse_remain_pending(
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
            assert worker.process_once() == "changed"
            db.expire_all()
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
            assert task.state == "QUEUED" and not task.rerun_requested
            assert db.scalar(select(LibraryResourceAsset)) is None
            assert pipeline.queue.prepare_book_identifications() == ()
            assert worker.process_once() == "ok"
            db.expire_all()
            assert task.state == "SUCCEEDED"
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
                        LibraryImportTask.kind == "IMPORT_RESOURCE"
                    )
                )
                if delete_resource:
                    other.delete(other.get(LibraryReadableResource, task.resource_id))
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
            assert worker.process_once() == "cancelled"
            db.expire_all()
            assert db.scalar(select(LibraryResourceAsset)) is None
            assert (
                db.scalar(
                    select(LibraryImportTask).where(
                        LibraryImportTask.kind == "IMPORT_RESOURCE"
                    )
                )
                is None
            )
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
            original = pipeline.queue.mark_succeeded

            def changed(task_id, *, finished_at):
                task = pipeline.queue.get_task(task_id)
                source.write_bytes(b"updated")
                for _ in range(20):
                    pipeline.queue.request_import_resource(
                        library_id=task.library_id,
                        resource_id=task.resource_id,
                        source_node_id=task.source_node_id,
                        changed=True,
                    )
                original(task_id, finished_at=finished_at)

            with monkeypatch.context() as patch:
                patch.setattr(pipeline.queue, "mark_succeeded", changed)
                assert worker.process_once() == "ok"
            db.expire_all()
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
            assert task.state == "QUEUED"
            first_version = db.scalar(
                select(LibraryResourceAsset)
            ).processed_source_version
            assert first_version.startswith("[3,")
            assert pipeline.queue.prepare_book_identifications() == ()
            assert worker.process_once() == "ok"
            db.expire_all()
            assert task.state == "SUCCEEDED"
            assert db.scalar(
                select(LibraryResourceAsset)
            ).processed_source_version.startswith("[7,")
    finally:
        engine.dispose()
