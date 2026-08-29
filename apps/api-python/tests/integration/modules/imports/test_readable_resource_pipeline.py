"""Integration coverage for ADR 0018 single-consumer ContinueImport."""

from __future__ import annotations

import base64
import os
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import Library, ReadableResourceNavigationUnit
from app.modules.imports.application.audio_types import AudioFileMetadata
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
    ContinueSourceImport,
)
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
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemyBookResourceRepository,
    SqlAlchemyLibraryConfigAdapter,
    SqlAlchemySourceNodeRepository,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeInterpretation,
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
        delete_book_sources=base.delete_book_sources,
        delete_source_node=base.delete_source_node,
        change_library_organization_mode=base.change_library_organization_mode,
        relocate_library_root=base.relocate_library_root,
        enable_readable_resource=base.enable_readable_resource,
        disable_readable_resource=base.disable_readable_resource,
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
                .where(LibraryImportTask.kind == "IMPORT_ASSET")
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


def test_failure_does_not_auto_retry_until_continue_import(tmp_path: Path) -> None:
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
            requeued = db.scalars(
                select(LibraryImportTask).where(LibraryImportTask.state == "QUEUED")
            ).all()
            assert any(t.kind == "IMPORT_ASSET" for t in requeued)
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
                    LibraryImportTask.kind == "IMPORT_ASSET"
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
                    LibraryImportTask.kind == "IMPORT_ASSET"
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

            assert _drain(pipeline) == ["ok"]
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
            assert _drain(pipeline) == ["scan", "ok"]

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
                    LibraryImportTask.kind == "IMPORT_ASSET"
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
            assert requeued is not None
            assert requeued.state == "QUEUED"

            assert _drain(pipeline) == ["ok"]
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
            assert states == {"01.mp3": "PENDING", "02.mp3": "READY"}
            assert db.get(LibraryReadableResource, resource.id).import_state == "READY"

            assert _drain(pipeline) == ["ok"]
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
            (album / "01.mp3").write_bytes(b"audio")
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
                    codec="mp3",
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
            assert assets[0].sort_key == "01.mp3"
            assert {
                node.relative_path for node in db.scalars(select(LibrarySourceNode))
            } == {"album", "album/01.mp3"}
            metadata = db.get(LibraryReadableResourceMetadata, resource.id)
            assert metadata is not None
            assert metadata.title == "Sidecar audiobook"
            assert metadata.cover_path is not None
            assert metadata.track_count == 1
            assert metadata.duration_ms == 60_000
            assert metadata.chapter_count == 1
            asset_metadata = db.get(LibraryResourceAssetMetadata, assets[0].id)
            assert asset_metadata is not None
            assert asset_metadata.title == "第一集"
            assert asset_metadata.mime_type == "audio/mpeg"
            assert asset_metadata.duration_ms == 60_000
            assert asset_metadata.codec == "mp3"
            assert asset_metadata.bitrate == 128_000
            assert asset_metadata.sample_rate == 44_100
            assert asset_metadata.channels == 2
            assert asset_metadata.track_number == 1
            unit = db.scalar(
                select(ReadableResourceNavigationUnit).where(
                    ReadableResourceNavigationUnit.resource_id == resource.id
                )
            )
            assert unit is not None
            assert (unit.start_ms, unit.end_ms, unit.duration_ms) == (
                0,
                60_000,
                60_000,
            )
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
                    LibraryImportTask.kind == "IMPORT_ASSET",
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
                    LibraryImportTask.kind == "IMPORT_ASSET",
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
