"""Integration coverage for ADR 0018 readable-resource pipeline (phase 7A)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, update
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
    AssetCandidate,
    LibraryImportTask,
    ResourceCandidate,
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
    """Exercises DB/candidate/publish without real media parsers."""

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


def _pipeline(db: Session) -> ReadableResourcePipeline:
    """Composition root with stub adapter for DB-path integration."""
    base = build_readable_resource_pipeline(db)
    libraries = SqlAlchemyLibraryConfigAdapter(db)
    filesystem = OsSourceTreeFilesystem()
    source_nodes = SqlAlchemySourceNodeRepository(db)
    books_resources = SqlAlchemyBookResourceRepository(db)
    import_runs = SqlAlchemyImportRunRepository(db)
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
        import_runs=import_runs,
        adapters=StubAlwaysOkAdapter(),
        queue=queue,
        uow=uow,
        clock=clock,
        log=log,
        sidecar=sidecar,
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


def test_single_file_txt_scan_claim_and_process(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "Novel.txt").write_text("hello world\n", encoding="utf-8")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            result = pipeline.scan_library_source_tree.execute("lib-1")
            assert result.nodes_inserted >= 1
            assert result.resources_created == 1
            assert result.tasks_enqueued == 1

            claim = pipeline.queue.claim_next("worker-a", lease_seconds=120)
            assert claim is not None
            assert claim.work_kind == "import"
            assert claim.lease_owner == "worker-a"
            assert claim.bridge_import_task_id is not None

            outcome = pipeline.process_import_task.execute(claim.target_id, claim)
            assert outcome.outcome == "ok"

            resource = db.scalar(select(LibraryReadableResource).limit(1))
            assert resource is not None
            assert resource.import_state == "READY"
            assert resource.published_run_id is not None
            assets = db.scalars(select(LibraryResourceAsset)).all()
            assert len(assets) == 1
            assert assets[0].import_state == "READY"
    finally:
        engine.dispose()


def test_late_lease_second_worker_does_not_overwrite(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "Story.txt").write_text("chapter\n", encoding="utf-8")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            pipeline.scan_library_source_tree.execute("lib-1")

            claim_a = pipeline.queue.claim_next("worker-a", lease_seconds=120)
            assert claim_a is not None
            work_id = claim_a.work_item_id

            past = db_timestamp() - timedelta(seconds=5)
            db.execute(
                update(ImportWorkItem)
                .where(ImportWorkItem.id == work_id)
                .values(lease_expires_at=past)
            )
            db.commit()

            claim_b = pipeline.queue.claim_next("worker-b", lease_seconds=120)
            assert claim_b is not None
            assert claim_b.work_item_id == work_id
            assert claim_b.lease_owner == "worker-b"

            stale = pipeline.process_import_task.execute(claim_a.target_id, claim_a)
            assert stale.outcome == "late_lease"
            assert db.scalar(select(LibraryResourceAsset).limit(1)) is None

            live = pipeline.process_import_task.execute(claim_b.target_id, claim_b)
            assert live.outcome == "ok"
            resource = db.scalar(select(LibraryReadableResource).limit(1))
            assert resource is not None
            assert resource.import_state == "READY"
    finally:
        engine.dispose()


def test_audiobook_directory_queues_track_candidates(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    audio_dir = root / "MyAudiobook"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            audio_dir.mkdir(parents=True)
            for name in ("01.mp3", "02.mp3", "03.mp3"):
                (audio_dir / name).write_bytes(b"")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            result = pipeline.scan_library_source_tree.execute("lib-1")
            assert result.resources_created >= 1

            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.adapter_id == "audiobook-directory"
                )
            )
            assert resource is not None
            assert resource.format == "AUDIOBOOK_DIR"

            tasks = db.scalars(select(LibraryImportTask)).all()
            assert len(tasks) >= 1
            assert all(task.role == "TRACK" for task in tasks)

            processed = 0
            while True:
                claim = pipeline.queue.claim_next(
                    f"worker-audio-{processed}", lease_seconds=120
                )
                if claim is None:
                    break
                if claim.work_kind != "import":
                    with pipeline.uow.transaction():
                        pipeline.queue.complete(claim)
                    continue
                outcome = pipeline.process_import_task.execute(claim.target_id, claim)
                assert outcome.outcome in {"ok", "failed", "deferred_active_run"}
                processed += 1
                if processed > 10:
                    break

            candidates = db.scalars(select(AssetCandidate)).all()
            published = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == resource.id
                )
            ).all()
            assert processed >= 1
            assert len(published) >= 1 or len(candidates) >= 1
            assert resource.import_state in {"READY", "PENDING"}
            if published:
                assert all(asset.role == "TRACK" for asset in published)
                assert all(
                    asset.published_run_id == resource.published_run_id
                    for asset in published
                )
    finally:
        engine.dispose()


def test_image_directory_queues_page_path(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    comic_dir = root / "ComicPages"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            comic_dir.mkdir(parents=True)
            for name in ("001.png", "002.jpg"):
                (comic_dir / name).write_bytes(b"")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            result = pipeline.scan_library_source_tree.execute("lib-1")
            assert result.resources_created >= 1

            resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.adapter_id == "image-directory"
                )
            )
            assert resource is not None
            assert resource.format == "IMAGE_DIR"

            nodes = db.scalars(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.physical_kind == "REGULAR_FILE"
                )
            ).all()
            assert len(nodes) >= 2

            tasks = db.scalars(select(LibraryImportTask)).all()
            assert len(tasks) >= 1
            assert all(task.role == "PAGE" for task in tasks)

            claim = pipeline.queue.claim_next("worker-page", lease_seconds=120)
            assert claim is not None
            assert claim.work_kind == "import"
            outcome = pipeline.process_import_task.execute(claim.target_id, claim)
            assert outcome.outcome == "ok"
            db.refresh(resource)
            assert resource.import_state == "READY"
            assert resource.published_run_id is not None
            pages = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == resource.id
                )
            ).all()
            assert len(pages) >= 1
            assert all(asset.role == "PAGE" for asset in pages)
    finally:
        engine.dispose()


def test_resource_candidate_exists_after_scan_before_process(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "Draft.txt").write_text("draft\n", encoding="utf-8")
            db.commit()

        with Session(engine) as db:
            pipeline = _pipeline(db)
            pipeline.scan_library_source_tree.execute("lib-1")
            candidates = db.scalars(select(ResourceCandidate)).all()
            assert len(candidates) == 1
            resource = db.scalar(select(LibraryReadableResource).limit(1))
            assert resource is not None
            assert resource.import_state == "PENDING"
            assert resource.active_import_run_id is not None
    finally:
        engine.dispose()
