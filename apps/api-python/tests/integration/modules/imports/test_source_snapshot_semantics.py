"""ADR 0018 SourceNode first-observation snapshot and non-follow semantics."""

from __future__ import annotations

import os
import time
import unicodedata
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

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
from app.models.library import Library
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
)
from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    DirectoryEntry,
    FileParseResult,
    ParsedAssetPayload,
    ResourceAdapterExecutorPort,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    DirectoryProbeEvidence,
    ProbeInterpretationResult,
    ProbeTerminationReason,
)
from app.modules.imports.domain.resource_adapters import ResourceAdapterSpec
from app.modules.imports.infrastructure.readable_resource.support import (
    InMemorySidecarWriteback,
    StructuredPipelineLog,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind
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
)


def _bootstrap(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return engine


def _add_library(
    db: Session,
    root: Path,
    *,
    min_file_size_bytes: int = 0,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    db.add(
        Library(
            id="lib-1",
            name="Lib",
            root_path=str(root.resolve()),
            organization_mode="FLAT",
            min_file_size_bytes=min_file_size_bytes,
        )
    )


class StubOkAdapter(ResourceAdapterExecutorPort):
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


def _pipeline(db: Session) -> ReadableResourcePipeline:
    base = build_readable_resource_pipeline(db)
    process = ProcessReadableResourceImportTask(
        libraries=SqlAlchemyLibraryConfigAdapter(db),
        filesystem=base.filesystem,
        source_nodes=SqlAlchemySourceNodeRepository(db),
        books_resources=SqlAlchemyBookResourceRepository(db),
        adapters=StubOkAdapter(),
        queue=base.queue,
        uow=base.uow,
        clock=base.clock,
        log=StructuredPipelineLog(),
        sidecar=InMemorySidecarWriteback(),
    )
    return replace(base, process_import_task=process)


def _drain(pipeline: ReadableResourcePipeline, *, limit: int = 100) -> list[str]:
    worker = build_readable_resource_worker(pipeline)
    outcomes: list[str] = []
    for _ in range(limit):
        outcome = worker.process_once()
        if outcome == "idle":
            break
        outcomes.append(outcome)
    return outcomes


def _continue_and_drain(pipeline: ReadableResourcePipeline) -> list[str]:
    pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
    return _drain(pipeline)


def test_observed_snapshot_is_immutable_on_content_change(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            path = root / "novel.epub"
            path.write_bytes(b"v1")
            os.utime(path, ns=(1_000_000_000, 1_000_000_000))

            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()

            node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "novel.epub"
                )
            )
            assert node is not None
            snap = (
                node.id,
                node.observed_size_bytes,
                node.observed_mtime_ns,
                node.observed_at,
                node.physical_kind,
                node.path_key,
                node.name,
            )
            resource = db.scalar(select(LibraryReadableResource))
            asset = db.scalar(select(LibraryResourceAsset))
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_ASSET",
                    LibraryImportTask.state == "SUCCEEDED",
                )
            )
            assert resource is not None and asset is not None and task is not None
            ids = (resource.id, asset.id, task.id)

            time.sleep(0.01)
            path.write_bytes(b"v2-longer-content")
            later = time.time_ns()
            os.utime(path, ns=(later, later))

            _continue_and_drain(pipeline)
            db.commit()
            db.refresh(node)
            assert (
                node.id,
                node.observed_size_bytes,
                node.observed_mtime_ns,
                node.observed_at,
                node.physical_kind,
                node.path_key,
                node.name,
            ) == snap
            assert db.scalar(select(func.count()).select_from(LibraryBook)) == 1
            assert (
                db.scalar(select(func.count()).select_from(LibraryReadableResource))
                == 1
            )
            assert (
                db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 1
            )
            assert db.get(LibraryReadableResource, ids[0]) is not None
            assert db.get(LibraryResourceAsset, ids[1]) is not None
            assert db.get(LibraryImportTask, ids[2]) is not None
            assert db.get(LibraryImportTask, ids[2]).state == "SUCCEEDED"
    finally:
        engine.dispose()


def test_missing_disk_file_is_not_reconciled(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            path = root / "gone.epub"
            path.write_bytes(b"epub")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()
            node = db.scalar(select(LibrarySourceNode))
            resource = db.scalar(select(LibraryReadableResource))
            asset = db.scalar(select(LibraryResourceAsset))
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_ASSET"
                )
            )
            assert node and resource and asset and task
            assert resource.import_state == "READY"
            assert asset.import_state == "READY"
            assert task.state == "SUCCEEDED"
            path.unlink()

            outcomes = _continue_and_drain(pipeline)
            db.commit()
            assert db.get(LibrarySourceNode, node.id) is not None
            refreshed = db.get(LibraryReadableResource, resource.id)
            assert refreshed is not None
            assert refreshed.import_state == "READY"
            refreshed_asset = db.get(LibraryResourceAsset, asset.id)
            assert refreshed_asset is not None
            assert refreshed_asset.import_state == "READY"
            refreshed_task = db.get(LibraryImportTask, task.id)
            assert refreshed_task is not None
            assert refreshed_task.state == "SUCCEEDED"
            assert "failed" not in outcomes
            assert db.scalar(select(func.count()).select_from(LibrarySourceNode)) == 1
    finally:
        engine.dispose()


def test_rename_creates_new_node_without_merging_old(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            old_path = root / "old.epub"
            old_path.write_bytes(b"epub")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()
            old_node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "old.epub"
                )
            )
            old_resource = db.scalar(select(LibraryReadableResource))
            old_asset = db.scalar(select(LibraryResourceAsset))
            assert old_node and old_resource and old_asset
            old_ids = (old_node.id, old_resource.id, old_asset.id)

            old_path.rename(root / "new.epub")
            _continue_and_drain(pipeline)
            db.commit()

            assert db.get(LibrarySourceNode, old_ids[0]) is not None
            assert db.get(LibraryReadableResource, old_ids[1]) is not None
            assert db.get(LibraryResourceAsset, old_ids[2]) is not None
            new_node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "new.epub"
                )
            )
            assert new_node is not None
            assert new_node.id != old_ids[0]
            assert new_node.path_key != old_node.path_key
            new_resource = db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.source_node_id == new_node.id
                )
            )
            assert new_resource is not None
            assert new_resource.id != old_ids[1]
            new_asset = db.scalar(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == new_resource.id
                )
            )
            assert new_asset is not None
            assert new_asset.id != old_ids[2]
            assert db.scalar(select(func.count()).select_from(LibrarySourceNode)) == 2
            assert db.scalar(select(func.count()).select_from(LibraryBook)) == 2
    finally:
        engine.dispose()


def test_symlink_is_recorded_but_not_followed_or_imported(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    outside = tmp_path / "outside"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            outside.mkdir()
            target = outside / "secret.epub"
            target.write_bytes(b"secret")
            (root / "link.epub").symlink_to(target)
            nested = root / "nested"
            nested.mkdir()
            (nested / "loop").symlink_to(root)
            (root / "dirlink").symlink_to(outside)

            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()

            kinds = {
                row.relative_path: row.physical_kind
                for row in db.scalars(select(LibrarySourceNode)).all()
            }
            assert kinds.get("link.epub") == "SYMLINK"
            assert kinds.get("dirlink") == "SYMLINK"
            assert kinds.get("nested/loop") == "SYMLINK"
            assert "secret.epub" not in kinds
            assert all(
                not path.startswith("dirlink/") for path in kinds
            )
            assert db.scalar(select(func.count()).select_from(LibraryBook)) == 0
            assert (
                db.scalar(select(func.count()).select_from(LibraryReadableResource))
                == 0
            )
            assert (
                db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 0
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.kind == "IMPORT_ASSET")
                )
                == 0
            )
    finally:
        engine.dispose()


def test_other_special_file_is_not_imported(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            fifo = root / "pipe.fifo"
            os.mkfifo(fifo)

            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()

            node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "pipe.fifo"
                )
            )
            assert node is not None
            assert node.physical_kind == "OTHER"
            assert db.scalar(select(func.count()).select_from(LibraryBook)) == 0
            assert (
                db.scalar(select(func.count()).select_from(LibraryReadableResource))
                == 0
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(LibraryImportTask.kind == "IMPORT_ASSET")
                )
                == 0
            )
    finally:
        engine.dispose()


class _LiteralNameFilesystem:
    """Yields exact directory entry names without OS Unicode normalization."""

    def __init__(self, entries: dict[str, list[DirectoryEntry]]) -> None:
        self._entries = entries

    def resolve_under_root(self, root: Path, relative_path: str) -> Path:
        return root / relative_path

    def iter_directory_entries(
        self, absolute_directory: Path
    ) -> Iterator[DirectoryEntry]:
        key = str(absolute_directory)
        yield from self._entries.get(key, ())

    def probe_directory(
        self,
        **kwargs: object,
    ) -> tuple[DirectoryProbeDecision, ProbeTerminationReason]:
        del kwargs
        evidence = DirectoryProbeEvidence(
            sample_relative_paths=(),
            sample_count=0,
            entries_visited=0,
            max_depth_reached=0,
            termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
        )
        return (
            DirectoryProbeDecision(
                result=ProbeInterpretationResult.NODE_ONLY,
                adapter=None,
                reason_code="NO_SAMPLES",
                evidence=evidence,
            ),
            ProbeTerminationReason.COMPLETE_SUBTREE,
        )

    def path_is_readable_directory(self, path: Path) -> bool:
        del path
        return True


def test_exact_path_spellings_create_distinct_source_nodes(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "Case.epub").write_bytes(b"a")
            (root / "case.epub").write_bytes(b"b")
            slash_name = "slash\\name.epub"
            (root / slash_name).write_bytes(b"c")

            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()
            paths = {
                row.relative_path
                for row in db.scalars(select(LibrarySourceNode)).all()
            }
            assert "Case.epub" in paths
            assert "case.epub" in paths
            assert slash_name in paths
    finally:
        engine.dispose()


def test_scanner_preserves_distinct_unicode_path_spellings(tmp_path: Path) -> None:
    """Scanner must keep NFC/NFD as distinct slots even if the host FS collapses them."""
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            nfc = unicodedata.normalize("NFC", "café.epub")
            nfd = unicodedata.normalize("NFD", "café.epub")
            assert nfc != nfd
            # Prefer real files when the host keeps both spellings.
            created_both = False
            try:
                (root / nfc).write_bytes(b"d")
                (root / nfd).write_bytes(b"e")
                created_both = (root / nfc).exists() and (root / nfd).exists()
                if created_both:
                    # Same inode / collapsed content means the FS did not keep two names.
                    created_both = (root / nfc).stat().st_ino != (root / nfd).stat().st_ino
            except OSError:
                created_both = False

            if created_both:
                pipeline = _pipeline(db)
                _continue_and_drain(pipeline)
                db.commit()
                scanned = {
                    row.relative_path
                    for row in db.scalars(select(LibrarySourceNode)).all()
                }
                assert nfc in scanned and nfd in scanned
            else:
                fs = _LiteralNameFilesystem(
                    {
                        str(root.resolve()): [
                            (nfc, SourceNodePhysicalKind.REGULAR_FILE, 1, 1),
                            (nfd, SourceNodePhysicalKind.REGULAR_FILE, 1, 2),
                        ],
                        str(root): [
                            (nfc, SourceNodePhysicalKind.REGULAR_FILE, 1, 1),
                            (nfd, SourceNodePhysicalKind.REGULAR_FILE, 1, 2),
                        ],
                    }
                )
                base = build_readable_resource_pipeline(db)
                scan = ScanLibrarySourceTree(
                    libraries=SqlAlchemyLibraryConfigAdapter(db),
                    filesystem=fs,
                    source_nodes=SqlAlchemySourceNodeRepository(db),
                    books_resources=SqlAlchemyBookResourceRepository(db),
                    queue=base.queue,
                    uow=base.uow,
                    clock=base.clock,
                    log=StructuredPipelineLog(),
                )
                scan.execute_library("lib-1")
                db.commit()
                scanned = {
                    row.relative_path
                    for row in db.scalars(select(LibrarySourceNode)).all()
                }
                assert nfc in scanned and nfd in scanned
                assert len(scanned) == 2
    finally:
        engine.dispose()


def test_legacy_min_file_size_does_not_gate_target_recognition(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root, min_file_size_bytes=10_000_000)
            db.commit()
            tiny = root / "tiny.epub"
            tiny.write_bytes(b"x")
            assert tiny.stat().st_size < 10_000_000
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()
            node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "tiny.epub"
                )
            )
            assert node is not None
            resource = db.scalar(select(LibraryReadableResource))
            assert resource is not None
            assert resource.import_state == "READY"
            assert db.scalar(select(func.count()).select_from(LibraryBook)) == 1
    finally:
        engine.dispose()


def test_other_entries_from_filesystem_port_are_node_only(tmp_path: Path) -> None:
    """Behavior proof when the host cannot create a special file: OTHER stays node-only."""
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            fs = _LiteralNameFilesystem(
                {
                    str(root.resolve()): [
                        ("device.node", SourceNodePhysicalKind.OTHER, 0, 1),
                        ("ok.epub", SourceNodePhysicalKind.REGULAR_FILE, 1, 2),
                    ],
                    str(root): [
                        ("device.node", SourceNodePhysicalKind.OTHER, 0, 1),
                        ("ok.epub", SourceNodePhysicalKind.REGULAR_FILE, 1, 2),
                    ],
                }
            )
            base = build_readable_resource_pipeline(db)
            scan = ScanLibrarySourceTree(
                libraries=SqlAlchemyLibraryConfigAdapter(db),
                filesystem=fs,
                source_nodes=SqlAlchemySourceNodeRepository(db),
                books_resources=SqlAlchemyBookResourceRepository(db),
                queue=base.queue,
                uow=base.uow,
                clock=base.clock,
                log=StructuredPipelineLog(),
            )
            scan.execute_library("lib-1")
            db.commit()
            by_path = {
                row.relative_path: row.physical_kind
                for row in db.scalars(select(LibrarySourceNode)).all()
            }
            assert by_path["device.node"] == "OTHER"
            assert by_path["ok.epub"] == "REGULAR_FILE"
            assert (
                db.scalar(
                    select(LibraryReadableResource).where(
                        LibraryReadableResource.source_node_id.in_(
                            select(LibrarySourceNode.id).where(
                                LibrarySourceNode.relative_path == "device.node"
                            )
                        )
                    )
                )
                is None
            )
    finally:
        engine.dispose()
