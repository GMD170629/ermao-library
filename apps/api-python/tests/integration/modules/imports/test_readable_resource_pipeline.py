"""Integration coverage for ADR 0018 single-consumer ContinueImport."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import Library
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
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
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


class StubFailOnceAdapter(StubAlwaysOkAdapter):
    def __init__(self, fail_names: set[str]) -> None:
        self._fail_names = fail_names

    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
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
    queue = SqlAlchemyReadableResourceWorkQueue(db)
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
        worker_id=base.worker_id,
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
                select(LibrarySourceNodeInterpretation).join(
                    LibrarySourceNode,
                    LibrarySourceNode.id
                    == LibrarySourceNodeInterpretation.source_node_id,
                ).where(LibrarySourceNode.relative_path == "mixed")
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
            pipeline, _ = _pipeline(
                db, adapters=StubFailOnceAdapter({"bad.mp3"})
            )
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

                def parse_file(self, **kwargs):  # type: ignore[no-untyped-def]
                    assert not self._session.in_transaction()
                    return super().parse_file(**kwargs)

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
