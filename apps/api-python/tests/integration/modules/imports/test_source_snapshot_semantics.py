"""ADR 0018 SourceNode first-observation snapshot and non-follow semantics."""

from __future__ import annotations

import os
import time
import unicodedata
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
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
from app.models import LibraryImportScanGap
from app.models.library import Library
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
    ContinueSourceImport,
)
from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    DirectoryEntry,
    FileParseResult,
    ParsedAssetPayload,
    ResourceAdapterExecutorPort,
    UnreadableDirectoryEntry,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.request_library_scan import (
    RequestLibraryScanCommand,
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
from app.modules.imports.domain.scan_policy import (
    MissingEntryPolicy,
    ScanScope,
    decode_scan_scopes,
)
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
)
from app.modules.imports.infrastructure.readable_resource.support import (
    InMemorySidecarWriteback,
    StructuredPipelineLog,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.application.source_tree_ports import ObservedSourceEntry
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
)
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


def _automatic_scan_and_drain(pipeline: ReadableResourcePipeline) -> list[str]:
    pipeline.request_library_scan.execute(
        RequestLibraryScanCommand(library_id="lib-1", trigger="WATCHER")
    )
    return _drain(pipeline)


def test_local_scan_reconciles_changes_without_visiting_sibling_trees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            for name in ["changed", *[f"sibling-{i}" for i in range(40)]]:
                (root / name).mkdir()
                (root / name / "book.epub").write_bytes(b"v1")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            (root / "changed/book.epub").unlink()
            (root / "changed/new.epub").write_bytes(b"new")
            visited: list[Path] = []
            original = pipeline.filesystem.iter_directory_entries

            def observe(path: Path):
                visited.append(path)
                yield from original(path)

            monkeypatch.setattr(pipeline.filesystem, "iter_directory_entries", observe)
            request = pipeline.request_library_scan.execute(
                RequestLibraryScanCommand("lib-1", "WATCHER", (ScanScope("changed"),))
            )
            _drain(pipeline)
            db.expire_all()
            task = db.get(LibraryImportTask, request.task_id)
            assert task is not None and task.state == "SUCCEEDED"
            paths = set(db.scalars(select(LibrarySourceNode.relative_path)).all())
            assert "changed/new.epub" in paths
            assert "changed/book.epub" not in paths
            assert "sibling-39/book.epub" in paths
            assert all("sibling-" not in str(path) for path in visited)
    finally:
        engine.dispose()


@pytest.mark.parametrize("allow_cleanup", [False, True])
@pytest.mark.parametrize("local", [False, True])
def test_empty_root_policy_is_shared_by_full_and_local_scans(
    tmp_path: Path,
    allow_cleanup: bool,
    local: bool,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "book.epub").write_bytes(b"v1")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            library = db.get(Library, "lib-1")
            assert library is not None
            library.allow_empty_library_cleanup = allow_cleanup
            db.commit()
            (root / "book.epub").unlink()
            result = pipeline.request_library_scan.execute(
                RequestLibraryScanCommand(
                    "lib-1", "WATCHER", (ScanScope(""),) if local else None
                )
            )
            _drain(pipeline)
            db.expire_all()
            task = db.get(LibraryImportTask, result.task_id)
            assert task is not None
            assert task.state == ("SUCCEEDED" if allow_cleanup else "FAILED")
            assert task.error_summary == (
                None if allow_cleanup else "EMPTY_LIBRARY_PROTECTED"
            )
            assert db.scalar(select(func.count()).select_from(LibrarySourceNode)) == (
                0 if allow_cleanup else 1
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure_mode", ["iteration", "stat", "probe"])
def test_failed_directory_preserves_data_while_other_scope_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            for name in ("good", "bad"):
                (root / name).mkdir()
                (root / name / "book.epub").write_bytes(b"v1")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            (root / "good/book.epub").rename(root / "good/new.epub")
            (root / "bad/book.epub").rename(root / "bad/new.epub")
            original = pipeline.filesystem.iter_directory_entries

            def failing(path: Path):
                if path.name == "bad" and failure_mode == "stat":
                    yield UnreadableDirectoryEntry("new.epub")
                    return
                yield from original(path)
                if path.name == "bad" and failure_mode == "iteration":
                    raise OSError("interrupted directory enumeration")

            monkeypatch.setattr(pipeline.filesystem, "iter_directory_entries", failing)
            original_probe = pipeline.filesystem.probe_directory

            def failing_probe(**kwargs):
                decision = original_probe(**kwargs)
                if (
                    kwargs["directory_relative_path"] == "bad"
                    and failure_mode == "probe"
                ):
                    return replace(
                        decision,
                        evidence=replace(
                            decision.evidence,
                            termination_reason=ProbeTerminationReason.LOCAL_IO_ERROR,
                        ),
                    )
                return decision

            monkeypatch.setattr(pipeline.filesystem, "probe_directory", failing_probe)
            result = pipeline.request_library_scan.execute(
                RequestLibraryScanCommand(
                    "lib-1", "WATCHER", (ScanScope("bad"), ScanScope("good"))
                )
            )
            _drain(pipeline)
            db.expire_all()
            task = db.get(LibraryImportTask, result.task_id)
            assert task is not None and task.state == "FAILED"
            assert task.error_summary == "SOURCE_SCAN_INCOMPLETE"
            # The request scope is immutable; only the unfinished scope stays
            # in the diagnostic gap record after the good sibling completes.
            assert {scope.relative_path for scope in decode_scan_scopes(task.scan_scopes) or ()} == {"bad", "good"}
            gap = db.get(LibraryImportScanGap, "lib-1")
            assert gap is not None
            recorded = decode_scan_scopes(gap.scopes)
            assert recorded is not None
            assert {scope.relative_path for scope in recorded} == {"bad"}
            paths = set(db.scalars(select(LibrarySourceNode.relative_path)).all())
            assert "bad/book.epub" in paths and "bad/new.epub" not in paths
            assert "good/new.epub" in paths and "good/book.epub" not in paths
            pending = db.scalars(
                select(LibraryImportTask)
                .join(
                    LibrarySourceNode,
                    LibraryImportTask.source_node_id == LibrarySourceNode.id,
                )
                .where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibrarySourceNode.relative_path == "good/new.epub",
                )
            ).all()
            assert len(pending) == 1 and pending[0].state == "SUCCEEDED"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "scopes",
    [
        (ScanScope("gone/nested"),),
        (ScanScope(""), ScanScope("gone"), ScanScope("gone/nested")),
    ],
)
def test_queued_scope_deleted_before_execution_reconciles_parent(
    tmp_path: Path,
    scopes: tuple[ScanScope, ...],
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "keep.epub").write_bytes(b"keep")
            (root / "gone/nested").mkdir(parents=True)
            (root / "gone/nested/book.epub").write_bytes(b"book")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            result = pipeline.request_library_scan.execute(
                RequestLibraryScanCommand("lib-1", "WATCHER", scopes)
            )
            (root / "gone/nested/book.epub").unlink()
            (root / "gone/nested").rmdir()
            (root / "gone").rmdir()
            _drain(pipeline)
            db.expire_all()
            task = db.get(LibraryImportTask, result.task_id)
            assert task is not None and task.state == "SUCCEEDED"
            assert set(db.scalars(select(LibrarySourceNode.relative_path))) == {
                "keep.epub"
            }
    finally:
        engine.dispose()


def test_nested_image_change_scans_owning_resource_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "comic/chapter").mkdir(parents=True)
            (root / "comic/chapter/1.png").write_bytes(b"image")
            (root / "other").mkdir()
            (root / "other/book.epub").write_bytes(b"book")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            owner = SqlAlchemyBookResourceRepository(
                db
            ).find_outermost_directory_resource("lib-1", "comic/chapter/1.png")
            assert owner is not None
            owner_id = owner.id
            (root / "comic/chapter/2.png").write_bytes(b"new image")
            visited: list[Path] = []
            original = pipeline.filesystem.iter_directory_entries

            def observe(path: Path):
                visited.append(path)
                yield from original(path)

            monkeypatch.setattr(pipeline.filesystem, "iter_directory_entries", observe)
            result = pipeline.request_library_scan.execute(
                RequestLibraryScanCommand(
                    "lib-1", "WATCHER", (ScanScope("comic/chapter"),)
                )
            )
            _drain(pipeline)
            db.expire_all()
            task = db.get(LibraryImportTask, result.task_id)
            assert task is not None and task.state == "SUCCEEDED"
            assert root / "comic" in visited and root / "other" not in visited
            node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "comic/chapter/2.png"
                )
            )
            assert node is not None
            asset = db.scalar(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.source_node_id == node.id
                )
            )
            assert asset is not None and asset.resource_id == owner_id
    finally:
        engine.dispose()


def test_scope_discovers_new_nested_directory(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "new/nested").mkdir(parents=True)
            (root / "new/nested/book.epub").write_bytes(b"book")
            pipeline = _pipeline(db)
            result = pipeline.request_library_scan.execute(
                RequestLibraryScanCommand("lib-1", "WATCHER", (ScanScope("new", True),))
            )
            _drain(pipeline)
            task = db.get(LibraryImportTask, result.task_id)
            assert task is not None and task.state == "SUCCEEDED"
            assert (
                db.scalar(
                    select(LibrarySourceNode).where(
                        LibrarySourceNode.relative_path == "new/nested/book.epub"
                    )
                )
                is not None
            )
    finally:
        engine.dispose()


def test_observed_snapshot_refreshes_on_content_change(tmp_path: Path) -> None:
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
            _automatic_scan_and_drain(pipeline)
            db.commit()

            node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "novel.epub"
                )
            )
            assert node is not None
            identity = (
                node.id,
                node.physical_kind,
                node.path_key,
                node.name,
            )
            first_observed_at = node.observed_at
            resource = db.scalar(select(LibraryReadableResource))
            asset = db.scalar(select(LibraryResourceAsset))
            task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
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
                node.physical_kind,
                node.path_key,
                node.name,
            ) == identity
            assert node.observed_size_bytes == len(b"v2-longer-content")
            assert node.observed_mtime_ns == later
            assert node.observed_at > first_observed_at
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


def test_direct_file_rescan_refreshes_observation_and_reimports_asset(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            source = root / "book.epub"
            source.write_bytes(b"v1")
            os.utime(source, ns=(1_000_000_000, 1_000_000_000))
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            node = db.scalar(select(LibrarySourceNode))
            asset = db.scalar(select(LibraryResourceAsset))
            asset_task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            )
            assert node is not None and asset is not None and asset_task is not None
            original_ids = (node.id, asset.id, asset_task.id)

            source.write_bytes(b"v2-longer")
            os.utime(source, ns=(2_000_000_000, 2_000_000_000))
            result = pipeline.continue_import.execute(
                ContinueSourceImport(
                    node.id,
                    missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                )
            )
            assert result.enqueued is True
            coalesced = pipeline.continue_import.execute(
                ContinueSourceImport(
                    node.id,
                    missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                )
            )
            assert coalesced.enqueued is True
            assert coalesced.task_id != result.task_id
            outcomes = _drain(pipeline)
            db.commit()
            db.refresh(node)
            db.refresh(asset_task)

            assert outcomes == ["continue_source", "continue_source", "book", "book"]
            assert (node.id, asset.id, asset_task.id) == original_ids
            assert node.observed_size_bytes == len(b"v2-longer")
            assert node.observed_mtime_ns == 2_000_000_000
            assert asset_task.state == "SUCCEEDED"
    finally:
        engine.dispose()


def test_automatic_scan_preserves_missing_disk_file(tmp_path: Path) -> None:
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
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            )
            assert node and resource and asset and task
            assert resource.import_state == "READY"
            assert asset.import_state == "READY"
            assert task.state == "SUCCEEDED"
            path.unlink()

            outcomes = _automatic_scan_and_drain(pipeline)
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
            assert outcomes == ["failed"]
            assert db.scalar(select(func.count()).select_from(LibrarySourceNode)) == 1
    finally:
        engine.dispose()


def test_automatic_scan_reconciles_renamed_node_and_removes_old(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            old_path = root / "old.epub"
            old_path.write_bytes(b"epub")
            pipeline = _pipeline(db)
            _automatic_scan_and_drain(pipeline)
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
            _automatic_scan_and_drain(pipeline)
            db.commit()

            assert db.get(LibrarySourceNode, old_ids[0]) is None
            assert db.get(LibraryReadableResource, old_ids[1]) is None
            assert db.get(LibraryResourceAsset, old_ids[2]) is None
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
            assert db.scalar(select(func.count()).select_from(LibrarySourceNode)) == 1
            assert db.scalar(select(func.count()).select_from(LibraryBook)) == 1
    finally:
        engine.dispose()


def test_manual_library_scan_prunes_missing_source_topology(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            source = root / "gone.epub"
            source.write_bytes(b"epub")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()
            node = db.scalar(select(LibrarySourceNode))
            resource = db.scalar(select(LibraryReadableResource))
            asset = db.scalar(select(LibraryResourceAsset))
            assert node is not None and resource is not None and asset is not None
            node_id, resource_id, asset_id = node.id, resource.id, asset.id

            library = db.get(Library, "lib-1")
            assert library is not None
            library.allow_empty_library_cleanup = True
            db.commit()
            source.unlink()
            outcomes = _continue_and_drain(pipeline)
            db.commit()

            assert "scan" in outcomes
            assert db.get(LibrarySourceNode, node_id) is None
            assert db.get(LibraryReadableResource, resource_id) is None
            assert db.get(LibraryResourceAsset, asset_id) is None
            assert db.scalar(select(func.count()).select_from(LibraryBook)) == 0
    finally:
        engine.dispose()


def test_direct_rescan_of_missing_file_fails_without_deleting_data(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            source = root / "gone.epub"
            source.write_bytes(b"epub")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            node = db.scalar(select(LibrarySourceNode))
            resource = db.scalar(select(LibraryReadableResource))
            asset = db.scalar(select(LibraryResourceAsset))
            assert node is not None and resource is not None and asset is not None
            source.unlink()

            result = pipeline.continue_import.execute(
                ContinueSourceImport(
                    node.id,
                    missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                )
            )
            assert result.enqueued is True
            assert _drain(pipeline) == ["failed"]
            db.commit()

            assert db.get(LibrarySourceNode, node.id) is not None
            assert db.get(LibraryReadableResource, resource.id) is not None
            assert db.get(LibraryResourceAsset, asset.id) is not None
            failed = db.get(LibraryImportTask, result.task_id)
            assert failed is not None
            assert failed.state == "FAILED"
            assert failed.error_summary == "SOURCE_SCAN_START_UNAVAILABLE"
    finally:
        engine.dispose()


def test_direct_rescan_of_missing_directory_fails_without_deleting_subtree(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            folder = root / "collection"
            folder.mkdir()
            publication = folder / "book.epub"
            publication.write_bytes(b"epub")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            directory_node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "collection"
                )
            )
            child_node = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "collection/book.epub"
                )
            )
            assert directory_node is not None and child_node is not None
            publication.unlink()
            folder.rmdir()

            result = pipeline.continue_import.execute(
                ContinueSourceImport(
                    directory_node.id,
                    missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                )
            )
            assert result.enqueued is True
            assert _drain(pipeline) == ["failed"]
            db.commit()

            assert db.get(LibrarySourceNode, directory_node.id) is not None
            assert db.get(LibrarySourceNode, child_node.id) is not None
            failed = db.get(LibraryImportTask, result.task_id)
            assert failed is not None
            assert failed.state == "FAILED"
            assert failed.error_summary == "SOURCE_SCAN_START_UNAVAILABLE"
    finally:
        engine.dispose()


def test_manual_scan_of_missing_library_root_fails_without_deleting_data(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            publication = root / "book.epub"
            publication.write_bytes(b"epub")
            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            node = db.scalar(select(LibrarySourceNode))
            resource = db.scalar(select(LibraryReadableResource))
            assert node is not None and resource is not None
            publication.unlink()
            root.rmdir()

            result = pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            assert result.enqueued is True
            assert _drain(pipeline) == ["failed"]
            db.commit()

            assert db.get(LibrarySourceNode, node.id) is not None
            assert db.get(LibraryReadableResource, resource.id) is not None
            failed = db.get(LibraryImportTask, result.task_id)
            assert failed is not None
            assert failed.state == "FAILED"
            assert failed.error_summary == "SOURCE_SCAN_START_UNAVAILABLE"
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
            assert all(not path.startswith("dirlink/") for path in kinds)
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
                    .where(
                        LibraryImportTask.kind.in_(("IMPORT_ASSET", "IMPORT_RESOURCE"))
                    )
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
                    .where(
                        LibraryImportTask.kind.in_(("IMPORT_ASSET", "IMPORT_RESOURCE"))
                    )
                )
                == 0
            )
    finally:
        engine.dispose()


class _LiteralNameFilesystem:
    """Yields exact directory entry names without OS Unicode normalization."""

    def metadata_input_observations(self, source, *, directory):
        return ()

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
    ) -> DirectoryProbeDecision:
        del kwargs
        evidence = DirectoryProbeEvidence(
            sample_relative_paths=(),
            sample_count=0,
            entries_visited=0,
            max_depth_reached=0,
            termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
        )
        return DirectoryProbeDecision(
            result=ProbeInterpretationResult.NODE_ONLY,
            adapter=None,
            reason_code="NO_SAMPLES",
            evidence=evidence,
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
            if os.name != "nt":
                (root / slash_name).write_bytes(b"c")

            if os.path.samefile(root / "Case.epub", root / "case.epub"):
                repository = SqlAlchemySourceNodeRepository(db)
                for name in ("Case.epub", "case.epub", slash_name):
                    repository.insert_if_absent(
                        library_id="lib-1",
                        parent_id=None,
                        entry=ObservedSourceEntry(
                            relative_path=SourceNodeRelativePath(name),
                            physical_kind=SourceNodePhysicalKind.REGULAR_FILE,
                            observed_size_bytes=1,
                            observed_mtime_ns=1,
                            observed_at=datetime.now(UTC),
                        ),
                    )
                db.commit()
                paths = {
                    row.relative_path
                    for row in db.scalars(select(LibrarySourceNode)).all()
                }
                assert paths == {"Case.epub", "case.epub", slash_name}
                return

            pipeline = _pipeline(db)
            _continue_and_drain(pipeline)
            db.commit()
            paths = {
                row.relative_path for row in db.scalars(select(LibrarySourceNode)).all()
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
                    created_both = (root / nfc).stat().st_ino != (
                        root / nfd
                    ).stat().st_ino
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
