from __future__ import annotations

import json
from pathlib import Path

from app.models.common import db_timestamp
from app.models.import_pipeline import ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import (
    MetadataOpfQueueState,
    MetadataWritebackOperation,
    MetadataWritebackTarget,
    OrganizePolicy,
)
from app.modules.metadata.application.opf import parse_opf_metadata
from app.modules.metadata.infrastructure.writeback_queue import (
    enqueue_writeback,
    reconcile_queue_state,
)
from app.services.metadata_file_writeback import (
    enqueue_metadata_writeback,
    metadata_writeback_view,
    process_next_metadata_writeback,
    schedule_work_metadata_writebacks,
)
from sqlalchemy import select


def _library_source(
    db_session, source: Path, *, volume_index: float | None = None
) -> None:
    stat = source.stat()
    db_session.add_all(
        [
            LibraryWork(
                id="work-1",
                title="快照标题",
                normalized_title="快照标题",
                author="作者",
                normalized_author="作者",
                description="简介",
                tags='["科幻"]',
            ),
            LibraryMediaVersion(id="media-1", work_id="work-1", media_kind="EBOOK"),
            LibraryVolume(
                id="volume-1",
                media_version_id="media-1",
                title="第一卷",
                volume_index=volume_index,
                format="TXT",
                resource_key="volume-1",
                import_status="READY",
            ),
            LibraryFile(
                id="file-1",
                volume_id="volume-1",
                path=str(source),
                hash_status="READY",
                mtime_ms=int(stat.st_mtime * 1000),
                kind="BOOK",
                mime_type="text/plain",
                size_bytes=stat.st_size,
            ),
            ImportTask(
                id="import-1",
                volume_id="volume-1",
                work_id="work-1",
                origin="MANUAL",
                status="COMPLETED",
                source_path=str(source),
            ),
        ]
    )
    db_session.commit()


def test_writeback_uses_immutable_snapshot_and_finishes_after_background_processing(
    db_session, test_settings, tmp_path: Path
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("正文")
    original_source = source.read_bytes()
    original_stat = source.stat()
    _library_source(db_session, source)
    work = db_session.get(LibraryWork, "work-1")
    assert work is not None
    work.series_index = 23
    operation_id = enqueue_metadata_writeback(
        db_session,
        work_id="work-1",
        media_version_id="media-1",
        source="MANUAL",
    )
    db_session.commit()

    work.title = "后续编辑标题"
    db_session.commit()

    assert process_next_metadata_writeback(db_session, test_settings) is True
    expanded = metadata_writeback_view(db_session, operation_id)
    assert expanded is not None
    assert expanded["totalTargets"] == 1
    assert process_next_metadata_writeback(db_session, test_settings) is True
    assert metadata_writeback_view(db_session, operation_id) is None
    metadata = parse_opf_metadata(source.with_suffix(".opf").read_bytes())
    assert metadata.title == "快照标题"
    assert metadata.author == "作者"
    assert metadata.series_index == 23
    assert source.read_bytes() == original_source
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns
    library_file = db_session.get(LibraryFile, "file-1")
    assert library_file is not None
    assert library_file.size_bytes == original_stat.st_size
    assert library_file.mtime_ms == int(original_stat.st_mtime * 1000)


def test_external_change_is_logged_and_removed_without_retry(
    db_session, test_settings, tmp_path: Path
) -> None:
    source = tmp_path / "changed.txt"
    source.write_text("原正文")
    _library_source(db_session, source)
    operation_id = enqueue_metadata_writeback(
        db_session,
        work_id="work-1",
        media_version_id="media-1",
        source="AUTOMATIC",
    )
    assert process_next_metadata_writeback(db_session, test_settings) is True
    target = db_session.scalar(select(MetadataWritebackTarget))
    assert target is not None
    target.attempts = 2
    db_session.commit()
    source.write_text("用户在识别后修改的正文")

    assert process_next_metadata_writeback(db_session, test_settings) is True

    assert metadata_writeback_view(db_session, operation_id) is None
    assert db_session.scalar(select(MetadataWritebackTarget)) is None
    assert source.read_text() == "用户在识别后修改的正文"
    assert not source.with_suffix(".opf").exists()


def test_writeback_adds_explicit_volume_number_to_publication_title(
    db_session, test_settings, tmp_path: Path
) -> None:
    source = tmp_path / "numbered.txt"
    source.write_text("正文")
    _library_source(db_session, source, volume_index=2)
    work = db_session.get(LibraryWork, "work-1")
    assert work is not None
    work.series_index = 23
    enqueue_metadata_writeback(
        db_session,
        work_id="work-1",
        media_version_id="media-1",
        source="MANUAL",
    )
    db_session.commit()

    assert process_next_metadata_writeback(db_session, test_settings) is True
    assert process_next_metadata_writeback(db_session, test_settings) is True
    metadata = parse_opf_metadata(source.with_suffix(".opf").read_bytes())
    assert metadata.title == "快照标题"
    assert metadata.volume_title == "第一卷"
    assert metadata.series_index == 23
    assert metadata.volume_index == 2


def test_queue_capacity_defers_new_preparation_without_dropping_it(
    db_session, test_settings, tmp_path: Path
) -> None:
    source = tmp_path / "capacity.txt"
    source.write_text("正文")
    _library_source(db_session, source)

    first = enqueue_writeback(
        db_session,
        work_id="work-1",
        media_version_id="media-1",
        source="TEST_FIRST",
        max_pending_targets=1,
    )
    second = enqueue_writeback(
        db_session,
        work_id="work-1",
        media_version_id="media-1",
        source="TEST_SECOND",
        max_pending_targets=1,
    )

    assert first.outcome == "QUEUED"
    assert second.outcome == "QUEUED"
    db_session.commit()
    constrained = test_settings.model_copy(
        update={"metadata_opf_queue_max_pending": 1}
    )
    assert process_next_metadata_writeback(db_session, constrained) is True
    assert process_next_metadata_writeback(db_session, constrained) is True
    assert len(db_session.scalars(select(MetadataWritebackOperation)).all()) == 2
    state = db_session.get(MetadataOpfQueueState, "default")
    assert state is not None
    assert state.pending_targets == 1
    assert state.pending_preparations == 1


def test_reconcile_queue_state_updates_existing_counter(db_session) -> None:
    state = db_session.get(MetadataOpfQueueState, "default")
    if state is None:
        state = MetadataOpfQueueState(id="default", pending_targets=7)
        db_session.add(state)
    else:
        state.pending_targets = 7
    db_session.commit()

    assert reconcile_queue_state(db_session, now=db_timestamp()) == 0
    db_session.expire_all()

    reconciled_state = db_session.get(MetadataOpfQueueState, "default")
    assert reconciled_state is not None
    assert reconciled_state.pending_targets == 0


def test_multi_media_batch_defers_later_scope_when_capacity_is_full(
    db_session, test_settings, tmp_path: Path
) -> None:
    first_source = tmp_path / "first.epub"
    second_source = tmp_path / "second.mp3"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    _library_source(db_session, first_source)
    second_stat = second_source.stat()
    db_session.add_all(
        [
            LibraryMediaVersion(
                id="media-2", work_id="work-1", media_kind="AUDIOBOOK"
            ),
            LibraryVolume(
                id="volume-2",
                media_version_id="media-2",
                title="有声版",
                format="MP3",
                resource_key="volume-2",
                import_status="READY",
            ),
            LibraryFile(
                id="file-2",
                volume_id="volume-2",
                path=str(second_source),
                hash_status="READY",
                mtime_ms=int(second_stat.st_mtime * 1000),
                kind="AUDIO",
                mime_type="audio/mpeg",
                size_bytes=second_stat.st_size,
            ),
            ImportTask(
                id="import-2",
                volume_id="volume-2",
                work_id="work-1",
                origin="MANUAL",
                status="COMPLETED",
                source_path=str(second_source),
            ),
            OrganizePolicy(id="default", write_metadata_to_files=True),
        ]
    )
    db_session.commit()
    constrained_settings = test_settings.model_copy(
        update={"metadata_opf_queue_max_pending": 1}
    )

    operations = schedule_work_metadata_writebacks(
        db_session,
        work_id="work-1",
        source="TEST",
        settings=constrained_settings,
    )

    assert len(operations) == 2
    db_session.commit()
    assert process_next_metadata_writeback(db_session, constrained_settings) is True
    assert process_next_metadata_writeback(db_session, constrained_settings) is True
    assert db_session.scalar(select(MetadataWritebackTarget)) is not None
    state = db_session.get(MetadataOpfQueueState, "default")
    assert state is not None
    assert state.pending_targets == 1
    assert state.pending_preparations == 1


def test_writeback_can_target_one_volume_in_media_version(
    db_session, test_settings, tmp_path: Path
) -> None:
    first_source = tmp_path / "first.txt"
    second_source = tmp_path / "second.txt"
    first_source.write_text("第一卷")
    second_source.write_text("第二卷")
    _library_source(db_session, first_source, volume_index=1)
    second_stat = second_source.stat()
    db_session.add_all(
        [
            LibraryVolume(
                id="volume-2",
                media_version_id="media-1",
                title="第二卷",
                volume_index=2,
                sort_order=2,
                format="TXT",
                resource_key="volume-2",
                import_status="READY",
            ),
            LibraryFile(
                id="file-2",
                volume_id="volume-2",
                path=str(second_source),
                hash_status="READY",
                mtime_ms=int(second_stat.st_mtime * 1000),
                kind="BOOK",
                mime_type="text/plain",
                size_bytes=second_stat.st_size,
            ),
            ImportTask(
                id="import-2",
                volume_id="volume-2",
                work_id="work-1",
                origin="MANUAL",
                status="COMPLETED",
                source_path=str(second_source),
            ),
        ]
    )
    db_session.commit()

    operation_id = enqueue_metadata_writeback(
        db_session,
        work_id="work-1",
        media_version_id="media-1",
        source="MANUAL",
        volume_id="volume-1",
    )
    db_session.commit()

    view = metadata_writeback_view(db_session, operation_id)
    assert view is not None
    assert view["totalTargets"] == 0
    assert process_next_metadata_writeback(db_session, test_settings) is True
    expanded = metadata_writeback_view(db_session, operation_id)
    assert expanded is not None
    assert expanded["totalTargets"] == 1
    assert process_next_metadata_writeback(db_session, test_settings) is True
    assert first_source.with_suffix(".opf").exists()
    assert not second_source.with_suffix(".opf").exists()


def test_writeback_prefers_the_target_volumes_cover_over_the_work_cover(
    db_session, test_settings, tmp_path: Path
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("正文")
    _library_source(db_session, source)
    storage_root = test_settings.resolved_storage_root
    storage_root.mkdir(parents=True, exist_ok=True)
    work_cover = storage_root / "work-cover.jpg"
    volume_cover = storage_root / "volume-cover.jpg"
    work_cover.write_bytes(b"work cover")
    volume_cover.write_bytes(b"volume cover")
    work = db_session.get(LibraryWork, "work-1")
    volume = db_session.get(LibraryVolume, "volume-1")
    assert work is not None
    assert volume is not None
    work.cover_path = str(work_cover)
    volume.cover_path = str(volume_cover)

    enqueue_metadata_writeback(
        db_session,
        work_id="work-1",
        media_version_id="media-1",
        source="MANUAL",
    )
    assert process_next_metadata_writeback(db_session, test_settings) is True
    target = db_session.scalar(select(MetadataWritebackTarget))

    assert target is not None
    payload = json.loads(target.payload_json)
    assert payload["coverPath"] == str(volume_cover)


def test_writeback_falls_back_to_the_work_cover_when_the_volume_has_none(
    db_session, test_settings, tmp_path: Path
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("正文")
    _library_source(db_session, source)
    storage_root = test_settings.resolved_storage_root
    storage_root.mkdir(parents=True, exist_ok=True)
    work_cover = storage_root / "work-cover.jpg"
    work_cover.write_bytes(b"work cover")
    work = db_session.get(LibraryWork, "work-1")
    assert work is not None
    work.cover_path = str(work_cover)

    enqueue_metadata_writeback(
        db_session,
        work_id="work-1",
        media_version_id="media-1",
        source="MANUAL",
    )
    assert process_next_metadata_writeback(db_session, test_settings) is True
    target = db_session.scalar(select(MetadataWritebackTarget))

    assert target is not None
    payload = json.loads(target.payload_json)
    assert payload["coverPath"] == str(work_cover)
