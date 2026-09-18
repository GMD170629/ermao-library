"""Second-phase corrections: durable gaps, precise scopes and real recovery.

Every case exercises the real scan/worker path. No test clears a wait by
calling ``mark_succeeded`` on the old failed task.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
    continue_library_import,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryImportScanGap,
    LibraryReadableResource,
    LibrarySourceNode,
)
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueSourceImport,
)
from app.modules.imports.application.readable_resource.request_library_scan import (
    RequestLibraryScanCommand,
)
from app.modules.imports.domain.scan_policy import (
    MissingEntryPolicy,
    ScanScope,
    decode_scan_scopes,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)


def _pipeline(
    tmp_path: Path, libraries: dict[str, Path]
) -> tuple[Session, Settings, ReadableResourcePipeline]:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    for root in libraries.values():
        root.mkdir(parents=True, exist_ok=True)
    session = Session(engine)
    for library_id, root in libraries.items():
        session.add(
            Library(
                id=library_id,
                name=library_id,
                root_path=str(root),
                organization_mode="FLAT",
                min_file_size_bytes=0,
            )
        )
    session.commit()
    return session, settings, build_readable_resource_pipeline(session, settings)


def _drain(pipeline: ReadableResourcePipeline, *, limit: int = 200) -> list[str]:
    worker = build_readable_resource_worker(pipeline)
    outcomes: list[str] = []
    for _ in range(limit):
        outcome = worker.process_once()
        if outcome == "idle":
            break
        outcomes.append(outcome)
    return outcomes


def _png(path: Path, color: str = "red") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color).save(path)


def _resource_task(db: Session, library_id: str, resource_id: str) -> LibraryImportTask:
    task = db.scalar(
        select(LibraryImportTask).where(
            LibraryImportTask.library_id == library_id,
            LibraryImportTask.kind == "IMPORT_RESOURCE",
            LibraryImportTask.resource_id == resource_id,
        )
    )
    assert task is not None
    return task


def _resource_id_for(db: Session, library_id: str, anchor_path: str) -> str:
    value = db.scalar(
        select(LibraryReadableResource.id)
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryReadableResource.source_node_id,
        )
        .where(
            LibraryReadableResource.library_id == library_id,
            LibrarySourceNode.relative_path == anchor_path,
        )
    )
    assert value is not None
    return value


def _node_for(db: Session, library_id: str, path: str) -> LibrarySourceNode:
    node = db.scalar(
        select(LibrarySourceNode).where(
            LibrarySourceNode.library_id == library_id,
            LibrarySourceNode.relative_path == path,
        )
    )
    assert node is not None
    return node


def _queue_force(
    pipeline: ReadableResourcePipeline, db: Session, resource_id: str
) -> None:
    task = _resource_task(db, "lib", resource_id)
    pipeline.queue.request_import_resource(
        library_id="lib",
        resource_id=resource_id,
        source_node_id=task.source_node_id,
        force=True,
    )
    db.commit()


def _fail_enumeration(pipeline: ReadableResourcePipeline, path: Path):
    original = pipeline.filesystem.iter_directory_entries

    def failing(current: Path):
        if current == path:
            raise OSError("injected incomplete enumeration")
        yield from original(current)

    pipeline.filesystem.iter_directory_entries = failing  # type: ignore[method-assign]
    return original


def test_recursive_parent_scope_keeps_good_and_gates_only_bad(tmp_path: Path) -> None:
    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        (root / "good.txt").write_text("readable", encoding="utf-8")
        _png(root / "bad" / "1.png", "blue")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        good_id = _resource_id_for(db, "lib", "good.txt")
        bad_id = _resource_id_for(db, "lib", "bad")

        original_iter = _fail_enumeration(pipeline, root / "bad")
        # One recursive parent scope: good completes, bad fails.
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER", (ScanScope("", True),))
        )
        _drain(pipeline)
        db.expire_all()

        # Queue both after the gap exists: good is independent, bad is gated.
        _queue_force(pipeline, db, good_id)
        _queue_force(pipeline, db, bad_id)
        outcomes = _drain(pipeline)
        db.expire_all()

        assert _resource_task(db, "lib", good_id).state == "SUCCEEDED"
        assert _resource_task(db, "lib", bad_id).state == "QUEUED"
        assert "identified" in outcomes

        # A real continue-source scan of the failed anchor releases it.
        pipeline.filesystem.iter_directory_entries = original_iter  # type: ignore[method-assign]
        pipeline.continue_import.execute(ContinueSourceImport(_node_for(db, "lib", "bad").id))
        outcomes = _drain(pipeline)
        db.expire_all()
        assert _resource_task(db, "lib", bad_id).state == "SUCCEEDED"
        assert "identified" in outcomes
    finally:
        db.close()


def test_full_scan_unexpected_exception_keeps_unknown_ranges_gated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        _png(root / "local" / "1.png")
        (root / "independent.txt").write_text("readable", encoding="utf-8")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        local_id = _resource_id_for(db, "lib", "local")
        independent_id = _resource_id_for(db, "lib", "independent.txt")

        original = pipeline.filesystem.iter_directory_entries

        def exploding(current: Path):
            if current == root / "local":
                raise RuntimeError("unexpected local failure")
            yield from original(current)

        pipeline.filesystem.iter_directory_entries = exploding  # type: ignore[method-assign]
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        scan = db.scalar(
            select(LibraryImportTask)
            .where(LibraryImportTask.kind == "SCAN_LIBRARY")
            .order_by(LibraryImportTask.created_at.desc())
        )
        assert scan is not None and scan.state == "FAILED"

        _queue_force(pipeline, db, local_id)
        _queue_force(pipeline, db, independent_id)
        _drain(pipeline)
        db.expire_all()
        assert _resource_task(db, "lib", independent_id).state == "SUCCEEDED"
        assert _resource_task(db, "lib", local_id).state == "QUEUED"

        pipeline.filesystem.iter_directory_entries = original  # type: ignore[method-assign]
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        assert _resource_task(db, "lib", local_id).state == "SUCCEEDED"
    finally:
        db.close()


def test_cleaning_scan_records_does_not_release_unfinished_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        _png(root / "book" / "1.png")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        resource_id = _resource_id_for(db, "lib", "book")

        original_iter = _fail_enumeration(pipeline, root / "book")
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        db.execute(
            delete(LibraryImportTask).where(
                LibraryImportTask.kind == "SCAN_LIBRARY"
            )
        )
        db.commit()

        _queue_force(pipeline, db, resource_id)
        outcomes = _drain(pipeline)
        db.expire_all()
        assert _resource_task(db, "lib", resource_id).state == "QUEUED"
        assert "ok" not in outcomes

        pipeline.filesystem.iter_directory_entries = original_iter  # type: ignore[method-assign]
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        assert _resource_task(db, "lib", resource_id).state == "SUCCEEDED"
    finally:
        db.close()


def test_failed_scan_recovered_by_real_continue_source(tmp_path: Path) -> None:
    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        _png(root / "book" / "1.png")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        resource_id = _resource_id_for(db, "lib", "book")

        original_iter = _fail_enumeration(pipeline, root / "book")
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        failed_scan = db.scalar(
            select(LibraryImportTask)
            .where(
                LibraryImportTask.kind == "SCAN_LIBRARY",
                LibraryImportTask.state == "FAILED",
            )
            .order_by(LibraryImportTask.created_at.desc())
        )
        assert failed_scan is not None

        _queue_force(pipeline, db, resource_id)
        _drain(pipeline)
        db.expire_all()
        assert _resource_task(db, "lib", resource_id).state == "QUEUED"

        # Real ContinueSourceImport fills the input; the old task stays FAILED.
        pipeline.filesystem.iter_directory_entries = original_iter  # type: ignore[method-assign]
        pipeline.continue_import.execute(
            ContinueSourceImport(_node_for(db, "lib", "book").id)
        )
        _drain(pipeline)
        db.expire_all()
        assert _resource_task(db, "lib", resource_id).state == "SUCCEEDED"
        assert db.get(LibraryImportTask, failed_scan.id).state == "FAILED"
    finally:
        db.close()


def test_waiting_reason_is_visible_in_task_projection(tmp_path: Path) -> None:
    from app.core.authorization import AuthorizationContext
    from app.modules.imports.infrastructure.library_queries import get_import_task

    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        _png(root / "book" / "1.png")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        resource_id = _resource_id_for(db, "lib", "book")

        _fail_enumeration(pipeline, root / "book")
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        _queue_force(pipeline, db, resource_id)
        _drain(pipeline)
        db.expire_all()

        task = _resource_task(db, "lib", resource_id)
        assert task.state == "QUEUED"
        context = AuthorizationContext(
            user_id="admin",
            is_admin=True,
            can_manage_system=True,
            can_view_manual_imports=True,
            library_ids=(),
            authz_version=1,
        )
        view = get_import_task(db, task.id, context)
        assert view is not None
        assert view["state"] == "QUEUED"
        assert view["waitingFor"] == {
            "reason": "SCAN_INCOMPLETE",
            "scope": "book",
            "recovery": "RETRY_SCAN",
        }
    finally:
        db.close()


def test_recovery_survives_worker_restart(tmp_path: Path) -> None:
    root = tmp_path / "library"
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    root.mkdir(parents=True)
    try:
        with Session(engine) as db:
            db.add(
                Library(
                    id="lib",
                    name="lib",
                    root_path=str(root),
                    organization_mode="FLAT",
                    min_file_size_bytes=0,
                )
            )
            db.commit()
            pipeline = build_readable_resource_pipeline(db, settings)
            _png(root / "book" / "1.png")
            db.commit()
            pipeline.request_library_scan.execute(
                RequestLibraryScanCommand("lib", "WATCHER")
            )
            _drain(pipeline)
            db.expire_all()
            resource_id = _resource_id_for(db, "lib", "book")

            _fail_enumeration(pipeline, root / "book")
            pipeline.request_library_scan.execute(
                RequestLibraryScanCommand("lib", "WATCHER")
            )
            _drain(pipeline)
            db.commit()
            _queue_force(pipeline, db, resource_id)
            db.commit()

        # Restart: a fresh session and pipeline must see the durable gap.
        with Session(engine) as db:
            pipeline = build_readable_resource_pipeline(db, settings)
            worker = build_readable_resource_worker(pipeline)
            assert worker.startup() == 0
            assert worker.process_once() == "idle"
            db.expire_all()
            assert _resource_task(db, "lib", resource_id).state == "QUEUED"

            pipeline.continue_import.execute(
                ContinueSourceImport(_node_for(db, "lib", "book").id)
            )
            _drain(pipeline)
            db.expire_all()
            assert _resource_task(db, "lib", resource_id).state == "SUCCEEDED"
    finally:
        engine.dispose()


def test_recursive_gap_narrows_to_failed_child(tmp_path: Path) -> None:
    from dataclasses import replace

    from app.modules.imports.domain.directory_probe import ProbeTerminationReason

    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        (root / "Shelf").mkdir(parents=True, exist_ok=True)
        (root / "Shelf" / "note.txt").write_text("readable", encoding="utf-8")
        for name in ("good", "bad"):
            _png(root / "Shelf" / name / "1.png")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        good_id = _resource_id_for(db, "lib", "Shelf/good")
        bad_id = _resource_id_for(db, "lib", "Shelf/bad")

        # A previous incomplete Shelf scan left a broad recursive gap.
        pipeline.queue.apply_scan_round(
            None, "lib", resolved=(), incomplete=(ScanScope("Shelf", True),)
        )
        db.commit()
        _queue_force(pipeline, db, good_id)
        _queue_force(pipeline, db, bad_id)

        original_probe = pipeline.filesystem.probe_directory

        def failing_probe(**kwargs):
            decision = original_probe(**kwargs)
            if kwargs["directory_relative_path"] == "Shelf/bad":
                return replace(
                    decision,
                    evidence=replace(
                        decision.evidence,
                        termination_reason=ProbeTerminationReason.LOCAL_IO_ERROR,
                    ),
                )
            return decision

        pipeline.filesystem.probe_directory = failing_probe  # type: ignore[method-assign]
        try:
            pipeline.request_library_scan.execute(
                RequestLibraryScanCommand(
                    "lib", "WATCHER", (ScanScope("Shelf", True),)
                )
            )
            outcomes = _drain(pipeline)
        finally:
            pipeline.filesystem.probe_directory = original_probe  # type: ignore[method-assign]
        db.expire_all()

        gap = db.get(LibraryImportScanGap, "lib")
        remaining = decode_scan_scopes(gap.scopes) if gap is not None else ()
        assert remaining is not None
        assert {scope.relative_path for scope in remaining} <= {"Shelf/bad"}
        assert _resource_task(db, "lib", good_id).state == "SUCCEEDED"
        assert _resource_task(db, "lib", bad_id).state == "QUEUED"
        assert "identified" in outcomes
    finally:
        db.close()


def test_round_resolves_completed_and_keeps_failed_and_unvisited(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        for name in ("a", "b", "c"):
            _png(root / name / "1.png")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        resource_ids = {
            name: _resource_id_for(db, "lib", name) for name in ("a", "b", "c")
        }
        pipeline.queue.apply_scan_round(
            None,
            "lib",
            resolved=(),
            incomplete=tuple(
                ScanScope(name, True) for name in ("a", "b", "c")
            ),
        )
        db.commit()
        for resource_id in resource_ids.values():
            _queue_force(pipeline, db, resource_id)

        original = pipeline.filesystem.iter_directory_entries

        def exploding(path: Path):
            if path == root / "b":
                raise RuntimeError("unexpected b failure")
            yield from original(path)

        pipeline.filesystem.iter_directory_entries = exploding  # type: ignore[method-assign]
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand(
                "lib",
                "WATCHER",
                (ScanScope("a", True), ScanScope("b", True), ScanScope("c", True)),
            )
        )
        _drain(pipeline)
        db.expire_all()

        gap = db.get(LibraryImportScanGap, "lib")
        paths = {
            scope.relative_path
            for scope in (decode_scan_scopes(gap.scopes) or () if gap else ())
        }
        assert "a" not in paths
        assert "b" in paths and "c" in paths
        assert _resource_task(db, "lib", resource_ids["a"]).state == "SUCCEEDED"
        assert _resource_task(db, "lib", resource_ids["b"]).state == "QUEUED"
        assert _resource_task(db, "lib", resource_ids["c"]).state == "QUEUED"
    finally:
        db.close()


def test_directory_waiting_matches_scheduler_with_active_scan(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from app.core.authorization import AuthorizationContext
    from app.modules.imports.infrastructure.library_queries import get_import_task

    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        _png(root / "book" / "1.png")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        resource_id = _resource_id_for(db, "lib", "book")
        _queue_force(pipeline, db, resource_id)
        task = _resource_task(db, "lib", resource_id)
        task.created_at = datetime(2020, 1, 1, tzinfo=UTC)
        db.commit()

        # An active scan covers the anchor but the directory resource is still
        # executable in creation order, so it must not be announced as waiting.
        pipeline.queue.request_library_scan(
            "lib", missing_entry_policy=MissingEntryPolicy.PRESERVE
        )
        db.commit()

        context = AuthorizationContext(
            user_id="admin",
            is_admin=True,
            can_manage_system=True,
            can_view_manual_imports=True,
            library_ids=(),
            authz_version=1,
        )
        view = get_import_task(db, task.id, context)
        assert view is not None and view["waitingFor"] is None
        selected = pipeline.queue.next_queued()
        assert selected is not None and selected.id == task.id
    finally:
        db.close()


def test_page_recovery_entry_runs_real_scan_and_clears_gap(tmp_path: Path) -> None:
    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        _png(root / "book" / "1.png")
        db.commit()
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        resource_id = _resource_id_for(db, "lib", "book")

        original = _fail_enumeration(pipeline, root / "book")
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "WATCHER")
        )
        _drain(pipeline)
        db.expire_all()
        _queue_force(pipeline, db, resource_id)
        _drain(pipeline)
        db.expire_all()
        assert _resource_task(db, "lib", resource_id).state == "QUEUED"
        assert db.get(LibraryImportScanGap, "lib") is not None

        # The page's recovery button targets POST /libraries/{id}/scan, whose
        # backend command is continue_library_import. It must run a real scan.
        pipeline.filesystem.iter_directory_entries = original  # type: ignore[method-assign]
        continue_library_import(db, "lib", trigger="MANUAL")
        _drain(pipeline)
        db.expire_all()
        gap = db.get(LibraryImportScanGap, "lib")
        assert gap is None or not gap.scopes
        assert _resource_task(db, "lib", resource_id).state == "SUCCEEDED"
    finally:
        db.close()
