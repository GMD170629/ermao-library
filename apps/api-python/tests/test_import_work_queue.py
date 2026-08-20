from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta
from itertools import chain
from pathlib import Path

import pytest
from app.bootstrap.imports import (
    ImportWorkerRuntime,
    persist_import_task_retry,
)
from app.core.time import now_timestamp_ms
from app.models.common import db_timestamp
from app.models.import_pipeline import ImportScanJob, ImportTask, ImportWorkItem
from app.models.library import Library, LibraryVersion, LibraryVolume, LibraryWork
from app.modules.imports.application.maintenance_commands import prepare_import_retry
from app.modules.imports.application.scan_jobs import prepare_import_scan_job
from app.modules.imports.infrastructure import streaming_scan
from app.modules.imports.infrastructure.library_queries import get_volume_context_by_id
from app.modules.imports.infrastructure.directory_scan import LibraryConfig
from app.modules.imports.infrastructure.scan_batch_store import (
    load_scan_candidate_projection,
    prepare_scan_candidate_batch,
    prepare_scan_sources,
    write_prepared_scan_candidate_batch,
)
from app.modules.imports.infrastructure.streaming_scan import StreamingDirectoryScanner
from app.modules.imports.infrastructure.work_queue import (
    claim_next_work_item,
    create_or_reuse_scan_job,
    ensure_import_work_item,
    get_scan_job,
    insert_prepared_scan_jobs,
    recover_scan_work_items,
)
from app.modules.imports.presentation.schemas import ScanError
from app.services.system_events import prepare_system_event
from sqlalchemy import delete, func, select


def _stage_scan_candidate_batch(db_session, candidates, *, library_id: str):
    library = db_session.get(Library, library_id)
    assert library is not None
    sources = prepare_scan_sources(
        candidates,
        library_root=Path(library.root_path),
        organization_mode=library.organization_mode,
    )
    projection = load_scan_candidate_projection(
        db_session,
        sources,
        library_id=library_id,
    )
    prepared = prepare_scan_candidate_batch(
        sources,
        projection,
        library_id=library_id,
        now_ms=now_timestamp_ms(),
        now=db_timestamp(),
    )
    return write_prepared_scan_candidate_batch(db_session, prepared)


def test_import_retry_rolls_back_state_when_event_write_fails(
    db_session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.imports.infrastructure import maintenance_write

    source = tmp_path / "failed.epub"
    source.write_bytes(b"book")
    task = ImportTask(
        id="task-retry-rollback",
        origin="WATCH",
        status="FAILED",
        source_path=str(source),
        retryable=True,
    )
    db_session.add(task)
    db_session.commit()
    event = prepare_system_event(
        source="import",
        action="retry",
        message="retry",
        target_type="importTask",
        target_id=task.id,
    )
    prepared = prepare_import_retry(
        task_id=task.id,
        source_path=source.resolve(),
        updated_at=db_timestamp(),
        event=event,
    )

    def fail_event(*_args, **_kwargs) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(
        maintenance_write,
        "write_prepared_system_events",
        fail_event,
    )

    with pytest.raises(RuntimeError, match="audit failure"):
        persist_import_task_retry(db_session, prepared)

    db_session.expire_all()
    assert db_session.get(ImportTask, task.id).status == "FAILED"
    assert db_session.scalar(select(func.count()).select_from(ImportWorkItem)) == 0


class _FakeFileEntry:
    def __init__(self, index: int) -> None:
        self.name = f"{index}.epub"
        self.path = f"/virtual/library/{index}.epub"

    def is_dir(self, *, follow_symlinks: bool) -> bool:
        return False

    def is_file(self, *, follow_symlinks: bool) -> bool:
        return True


class _NamedFakeFileEntry:
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = f"/virtual/library/{name}"

    def is_dir(self, *, follow_symlinks: bool) -> bool:
        return False

    def is_file(self, *, follow_symlinks: bool) -> bool:
        return True


class _NamedFakeDirectoryEntry:
    def __init__(self, path: str) -> None:
        self.name = Path(path).name
        self.path = path

    def is_dir(self, *, follow_symlinks: bool) -> bool:
        return True

    def is_file(self, *, follow_symlinks: bool) -> bool:
        return False


@pytest.mark.parametrize(
    ("model", "expected_candidates"),
    [
        ("ignored", 0),
        ("candidates", 1_800_000),
        ("mixed", 900_000),
    ],
)
def test_streaming_scan_keeps_million_scale_candidate_buffer_bounded(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    expected_candidates: int,
) -> None:
    total_entries = 1_800_000
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(streaming_scan, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        streaming_scan.os,
        "scandir",
        lambda _path: (_FakeFileEntry(index) for index in range(total_entries)),
    )

    def ignore_reason(path: Path, _folder: LibraryConfig):
        if model == "ignored":
            return "unsupported_file_type"
        if model == "mixed" and int(path.stem) % 2:
            return "unsupported_file_type"
        return None

    monkeypatch.setattr(streaming_scan, "import_source_ignore_reason", ignore_reason)
    scanner = StreamingDirectoryScanner(
        Path("/virtual/library"),
        LibraryConfig(
            id="folder-million",
            root_path="/virtual/library",
            min_file_size_bytes=0,
        ),
    )
    files_scanned = 0
    candidates_found = 0
    largest_batch = 0
    try:
        while True:
            scan_slice = scanner.next_slice()
            files_scanned += scan_slice.files_scanned
            candidates_found += scan_slice.candidates_found
            largest_batch = max(largest_batch, len(scan_slice.candidates))
            if scan_slice.completed:
                break
    finally:
        scanner.close()

    assert files_scanned == total_entries
    assert candidates_found == expected_candidates
    assert largest_batch <= 500


def test_streaming_scan_blocks_overflowing_audio_bundle_without_hiding_non_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = (_NamedFakeFileEntry(f"{index:07d}.mp3") for index in range(1_800_000))
    mixed_entries = chain(entries, (_NamedFakeFileEntry("appendix.epub"),))
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(streaming_scan, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        streaming_scan.os,
        "scandir",
        lambda _path: iter(mixed_entries),
    )
    monkeypatch.setattr(
        streaming_scan, "import_source_ignore_reason", lambda _path, _folder: None
    )
    scanner = StreamingDirectoryScanner(
        Path("/virtual/library"),
        LibraryConfig(
            id="folder-audio-overflow",
            root_path="/virtual/library",
            min_file_size_bytes=0,
        ),
    )
    candidates: list[Path] = []
    errors: list[object] = []
    files_scanned = 0
    skipped = 0
    largest_audio_buffer = 0
    largest_file_slice = 0
    try:
        while True:
            scan_slice = scanner.next_slice()
            candidates.extend(scan_slice.candidates)
            errors.extend(scan_slice.errors)
            files_scanned += scan_slice.files_scanned
            skipped += scan_slice.skipped_count
            largest_audio_buffer = max(
                largest_audio_buffer,
                scanner.buffered_audio_path_count,
            )
            largest_file_slice = max(largest_file_slice, scan_slice.files_scanned)
            if scan_slice.completed:
                break
    finally:
        scanner.close()

    assert candidates == [Path("/virtual/library/appendix.epub")]
    assert files_scanned == 1_800_001
    assert skipped == 1_800_000
    assert largest_audio_buffer <= 10_000
    assert largest_file_slice <= 5_000
    assert len(errors) == 1
    assert errors[0].code == "AUDIO_TRACK_LIMIT_EXCEEDED"
    assert errors[0].limit == 10_000
    assert errors[0].observed_count == 1_800_000


def test_audio_overflow_scan_persists_typed_error_without_import_work(
    db_session,
    test_settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "overflow"
    root.mkdir()
    folder = Library(
        organization_mode="FLAT",
        id="folder-audio-overflow-persistence",
        name="Audio overflow persistence",
        root_path=str(root),
        enabled=True,
        min_file_size_bytes=0,
    )
    db_session.add(folder)
    db_session.flush()
    _job, created = create_or_reuse_scan_job(
        db_session,
        library_id=folder.id,
        actor_user_id=None,
        root_path=root,
        trigger="TEST",
    )
    db_session.commit()
    assert created is True
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(streaming_scan, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        streaming_scan.os,
        "scandir",
        lambda _path: (
            _NamedFakeFileEntry(f"{index:05d}.mp3") for index in range(10_001)
        ),
    )
    monkeypatch.setattr(
        streaming_scan, "import_source_ignore_reason", lambda _path, _folder: None
    )
    runtime = ImportWorkerRuntime(lambda: nullcontext(db_session), test_settings)

    while True:
        work_item = runtime.claim_work("audio-overflow-worker", 900)
        if work_item is None:
            break
        assert work_item.kind == "SCAN_DIRECTORY"
        runtime.process_scan(work_item)

    stored = get_scan_job(db_session, _job.id)
    assert stored is not None
    assert stored.status == "COMPLETED"
    assert stored.queued_count == 0
    assert stored.skipped_count == 10_001
    assert stored.error_count == 1
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 0
    assert db_session.scalar(select(func.count()).select_from(ImportWorkItem)) == 0
    error = stored.error_samples[0]
    assert error.code == "AUDIO_TRACK_LIMIT_EXCEEDED"
    assert error.limit == 10_000
    assert error.observed_count == 10_001
    assert ScanError.model_validate(error, from_attributes=True).model_dump(
        by_alias=True
    ) == {
        "path": str(root),
        "error": "有声书音轨超过 10000 条，请拆分目录后重新导入",
        "code": "AUDIO_TRACK_LIMIT_EXCEEDED",
        "limit": 10_000,
        "observedCount": 10_001,
    }


def test_multivolume_audio_limit_is_aggregated_across_the_whole_book(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("/virtual/library/Book")
    first_volume = root / "Vol.1"
    second_volume = root / "Vol.2"

    def entries(path: Path):
        if path == root:
            return iter(
                (
                    _NamedFakeDirectoryEntry(str(first_volume)),
                    _NamedFakeDirectoryEntry(str(second_volume)),
                )
            )
        if path == first_volume:
            return (
                _NamedFakeFileEntry(f"Vol.1/{index:05d}.mp3") for index in range(6_000)
            )
        if path == second_volume:
            return (
                _NamedFakeFileEntry(f"Vol.2/{index:05d}.mp3") for index in range(6_000)
            )
        raise AssertionError(f"unexpected directory: {path}")

    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(streaming_scan, "monotonic", lambda: 0.0)
    monkeypatch.setattr(streaming_scan.os, "scandir", entries)
    monkeypatch.setattr(
        streaming_scan, "import_source_ignore_reason", lambda _path, _folder: None
    )
    scanner = StreamingDirectoryScanner(
        root,
        LibraryConfig(
            id="folder-multivolume-overflow",
            root_path=str(root),
            min_file_size_bytes=0,
        ),
    )
    errors: list[object] = []
    candidates: list[Path] = []
    skipped = 0
    try:
        while True:
            scan_slice = scanner.next_slice()
            candidates.extend(scan_slice.candidates)
            errors.extend(scan_slice.errors)
            skipped += scan_slice.skipped_count
            assert scanner.buffered_audio_path_count <= 10_000
            if scan_slice.completed:
                break
    finally:
        scanner.close()

    assert candidates == []
    assert skipped == 12_000
    assert len(errors) == 1
    assert errors[0].code == "AUDIO_TRACK_LIMIT_EXCEEDED"
    assert errors[0].observed_count == 12_000


def test_persistent_queue_prioritizes_import_and_debounces_pending_work(
    db_session,
    tmp_path: Path,
) -> None:
    folder = Library(
            organization_mode="FLAT", 
        id="folder-priority",
        name="Priority",
        root_path=str(tmp_path),
        enabled=True,
    )
    db_session.add(folder)
    db_session.flush()
    task = ImportTask(
        id="task-priority",
        library_id=folder.id,
        origin="WATCH",
        status="PENDING",
        source_path=str(tmp_path / "book.epub"),
    )
    db_session.add(task)
    db_session.flush()
    first_available_at = db_timestamp() + timedelta(seconds=2)
    work = ensure_import_work_item(db_session, task, available_at=first_available_at)
    create_or_reuse_scan_job(
        db_session,
        library_id=folder.id,
        actor_user_id=None,
        root_path=tmp_path,
        trigger="TEST",
    )
    later_available_at = db_timestamp() + timedelta(seconds=4)
    ensure_import_work_item(db_session, task, available_at=later_available_at)
    assert work.available_at == later_available_at

    work.available_at = db_timestamp()
    db_session.commit()
    claimed = claim_next_work_item(
        db_session, worker_id="worker-priority", import_lease_seconds=900
    )
    assert claimed is not None
    assert claimed.kind == "IMPORT_SOURCE"
    ensure_import_work_item(
        db_session,
        task,
        available_at=db_timestamp() + timedelta(seconds=30),
    )
    leased = db_session.get(ImportWorkItem, claimed.id)
    assert leased is not None and leased.status == "LEASED"


def test_pending_audio_scan_job_refreshes_stability_debounce(
    db_session,
    tmp_path: Path,
) -> None:
    folder = Library(
            organization_mode="FLAT", 
        id="folder-audio-scan-debounce",
        name="Audio scan debounce",
        root_path=str(tmp_path),
        enabled=True,
    )
    db_session.add(folder)
    db_session.flush()
    first_available_at = db_timestamp() + timedelta(seconds=2)
    job, created = create_or_reuse_scan_job(
        db_session,
        library_id=folder.id,
        actor_user_id=None,
        root_path=tmp_path / "audiobook",
        trigger="WATCHER_AUDIO_EVENT",
        available_at=first_available_at,
    )
    later_available_at = db_timestamp() + timedelta(seconds=5)
    reused, created_again = create_or_reuse_scan_job(
        db_session,
        library_id=folder.id,
        actor_user_id=None,
        root_path=tmp_path / "audiobook",
        trigger="WATCHER_AUDIO_EVENT",
        available_at=later_available_at,
    )
    db_session.flush()

    work = db_session.scalar(
        select(ImportWorkItem).where(ImportWorkItem.scan_job_id == job.id)
    )
    assert created is True
    assert created_again is False
    assert reused.id == job.id
    assert work is not None
    assert abs((work.available_at - later_available_at).total_seconds()) < 0.001


def test_prepared_monitor_rescan_jobs_insert_as_one_set_and_reuse_existing(
    db_session,
    tmp_path: Path,
) -> None:
    folders = tuple(
        Library(
            organization_mode="FLAT", 
            id=f"folder-rescan-{index}",
            name=f"Rescan {index}",
            root_path=str(tmp_path / str(index)),
            enabled=True,
        )
        for index in range(3)
    )
    db_session.add_all(folders)
    db_session.commit()
    prepared_at = db_timestamp()
    requests = tuple(
        prepare_import_scan_job(
            job_id=f"scan-rescan-{index}",
            work_item_id=f"work-rescan-{index}",
            library_id=folder.id,
            actor_user_id=None,
            canonical_root_path=folder.root_path,
            trigger="manual_rescan",
            available_at=None,
            created_at=prepared_at,
        )
        for index, folder in enumerate(folders)
    )

    created = insert_prepared_scan_jobs(db_session, requests)
    db_session.commit()
    reused = insert_prepared_scan_jobs(db_session, requests)
    db_session.commit()

    assert created == 3
    assert reused == 0
    assert db_session.scalar(select(func.count()).select_from(ImportScanJob)) == 3
    assert db_session.scalar(select(func.count()).select_from(ImportWorkItem)) == 3


def test_scan_candidate_batch_bulk_inserts_and_is_idempotent(
    db_session,
    tmp_path: Path,
) -> None:
    folder = Library(
            organization_mode="FLAT", 
        id="folder-batch",
        name="Batch",
        root_path=str(tmp_path),
        enabled=True,
    )
    db_session.add(folder)
    candidates = tuple(tmp_path / f"book-{index:03d}.epub" for index in range(500))
    for candidate in candidates:
        candidate.write_bytes(b"book")
    db_session.flush()

    first = _stage_scan_candidate_batch(
        db_session, candidates, library_id=folder.id
    )
    second = _stage_scan_candidate_batch(
        db_session, candidates, library_id=folder.id
    )
    db_session.commit()

    assert first.queued_count == 500
    assert first.cached_count == 0
    assert second.queued_count == 0
    assert second.cached_count == 500
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 500
    assert db_session.scalar(select(func.count()).select_from(ImportWorkItem)) == 500


def test_completed_audio_bundle_is_not_requeued_by_repeated_scan(
    db_session,
    tmp_path: Path,
) -> None:
    folder = Library(
        organization_mode="AUDIOBOOK",
        id="folder-audio-repeat",
        name="Audio repeat",
        root_path=str(tmp_path),
        enabled=True,
    )
    bundle = tmp_path / "audiobook"
    bundle.mkdir()
    (bundle / "01.mp3").write_bytes(b"first")
    (bundle / "02.mp3").write_bytes(b"second")
    db_session.add(folder)
    db_session.flush()

    first = _stage_scan_candidate_batch(
        db_session, (bundle,), library_id=folder.id
    )
    task = db_session.scalar(select(ImportTask))
    assert task is not None
    task.status = "COMPLETED"
    db_session.execute(delete(ImportWorkItem))
    db_session.flush()

    second = _stage_scan_candidate_batch(
        db_session, (bundle,), library_id=folder.id
    )
    db_session.commit()

    assert first.queued_count == 1
    assert second.queued_count == 0
    assert second.cached_count == 1
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 1
    assert db_session.scalar(select(func.count()).select_from(ImportWorkItem)) == 0


def test_volume_layout_scan_materializes_and_binds_directory_topology(
    db_session,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    source = root / "三体" / "中文版" / "01 地球往事.epub"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"book")
    library = Library(
        id="folder-topology",
        name="Topology",
        root_path=str(root),
        organization_mode="VOLUMES",
        enabled=True,
        min_file_size_bytes=0,
    )
    db_session.add(library)
    db_session.flush()

    result = _stage_scan_candidate_batch(
        db_session,
        (source,),
        library_id=library.id,
    )
    db_session.flush()

    work = db_session.scalar(
        select(LibraryWork).where(LibraryWork.library_id == library.id)
    )
    version = db_session.scalar(select(LibraryVersion))
    volume = db_session.scalar(select(LibraryVolume))
    task = db_session.scalar(select(ImportTask))
    assert result.queued_count == 1
    assert result.rejected_count == 0
    assert work is not None and work.source_key == "work:三体"
    assert version is not None and version.source_key == "version:三体/中文版"
    assert volume is not None
    assert volume.resource_key == "volume:三体/中文版/01 地球往事.epub"
    assert task is not None
    assert task.work_id == work.id
    assert task.volume_id == volume.id
    context = get_volume_context_by_id(db_session, volume.id)
    assert context is not None
    assert context["workId"] == work.id
    assert context["versionId"] == version.id


def test_invalid_volume_layout_is_rejected_before_import_enqueue(
    db_session,
    tmp_path: Path,
) -> None:
    root = tmp_path / "invalid-library"
    source = root / "missing-version.epub"
    root.mkdir()
    source.write_bytes(b"book")
    library = Library(
        id="folder-invalid-topology",
        name="Invalid topology",
        root_path=str(root),
        organization_mode="VOLUMES",
        enabled=True,
        min_file_size_bytes=0,
    )
    db_session.add(library)
    db_session.flush()

    result = _stage_scan_candidate_batch(
        db_session,
        (source,),
        library_id=library.id,
    )
    db_session.flush()

    assert result.queued_count == 0
    assert result.rejected_count == 1
    assert result.errors[0].code == "LIBRARY_LAYOUT_VERSION_DIRECTORY_REQUIRED"
    assert db_session.scalar(select(func.count()).select_from(LibraryWork)) == 0
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 0


def test_audiobook_layout_creates_one_task_for_each_volume_directory(
    db_session,
    tmp_path: Path,
) -> None:
    root = tmp_path / "audio-library"
    book = root / "Book"
    first_volume = book / "Vol.1"
    second_volume = book / "Vol.2"
    first_volume.mkdir(parents=True)
    second_volume.mkdir()
    (first_volume / "01.mp3").write_bytes(b"first")
    (second_volume / "01.mp3").write_bytes(b"second")
    library = Library(
        id="folder-audio-topology",
        name="Audio topology",
        root_path=str(root),
        organization_mode="AUDIOBOOK",
        enabled=True,
        min_file_size_bytes=0,
    )
    db_session.add(library)
    db_session.flush()

    result = _stage_scan_candidate_batch(
        db_session,
        (book,),
        library_id=library.id,
    )
    db_session.flush()

    work = db_session.scalar(
        select(LibraryWork).where(LibraryWork.library_id == library.id)
    )
    volumes = list(
        db_session.scalars(
            select(LibraryVolume).order_by(LibraryVolume.resource_key)
        ).all()
    )
    tasks = list(db_session.scalars(select(ImportTask)).all())
    assert result.queued_count == 2
    assert work is not None and work.source_key == "work:Book"
    assert [volume.resource_key for volume in volumes] == [
        "volume:Book/Vol.1",
        "volume:Book/Vol.2",
    ]
    assert {task.source_path for task in tasks} == {
        str(first_volume),
        str(second_volume),
    }
    assert {task.volume_id for task in tasks} == {
        volume.id for volume in volumes
    }


def test_scan_worker_persists_topology_and_bound_import_in_one_checkpoint(
    db_session,
    test_settings,
    tmp_path: Path,
) -> None:
    root = tmp_path / "worker-library"
    source = root / "Work" / "Version" / "01.epub"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"book")
    library = Library(
        id="folder-worker-topology",
        name="Worker topology",
        root_path=str(root),
        organization_mode="VOLUMES",
        enabled=True,
        min_file_size_bytes=0,
    )
    db_session.add(library)
    db_session.flush()
    job, created = create_or_reuse_scan_job(
        db_session,
        library_id=library.id,
        actor_user_id=None,
        root_path=root,
        trigger="TEST",
    )
    db_session.commit()
    assert created is True
    runtime = ImportWorkerRuntime(lambda: nullcontext(db_session), test_settings)

    work_item = runtime.claim_work("topology-worker", 900)
    assert work_item is not None and work_item.kind == "SCAN_DIRECTORY"
    assert runtime.process_scan(work_item) is True

    stored = get_scan_job(db_session, job.id)
    task = db_session.scalar(select(ImportTask))
    volume = db_session.scalar(select(LibraryVolume))
    assert stored is not None and stored.status == "COMPLETED"
    assert stored.queued_count == 1
    assert task is not None and volume is not None
    assert task.volume_id == volume.id


def test_scan_recovery_restarts_from_root_and_resets_attempt_counts(
    db_session,
    tmp_path: Path,
) -> None:
    folder = Library(
            organization_mode="FLAT", 
        id="folder-recovery",
        name="Recovery",
        root_path=str(tmp_path),
        enabled=True,
    )
    db_session.add(folder)
    db_session.flush()
    job, _created = create_or_reuse_scan_job(
        db_session,
        library_id=folder.id,
        actor_user_id=None,
        root_path=tmp_path,
        trigger="TEST",
    )
    claimed = claim_next_work_item(
        db_session, worker_id="worker-recovery", import_lease_seconds=900
    )
    assert claimed is not None
    scan_row = db_session.get(ImportScanJob, job.id)
    assert scan_row is not None
    scan_row.files_scanned = 100_000
    scan_row.queued_count = 500
    db_session.commit()

    assert recover_scan_work_items(db_session) == 1
    db_session.commit()
    recovered = get_scan_job(db_session, job.id)
    assert recovered is not None
    assert recovered.status == "PENDING"
    assert recovered.files_scanned == 0
    assert recovered.queued_count == 0
    assert recovered.restart_count == 1
