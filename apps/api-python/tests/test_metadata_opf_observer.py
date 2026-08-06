from __future__ import annotations

from pathlib import Path

from app.bootstrap.metadata_opf_observer import install_metadata_opf_observer
from app.models.import_pipeline import ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import MetadataWritebackTarget, OrganizePolicy
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker


def _pending_count(db: Session) -> int:
    return int(
        db.scalar(select(func.count()).select_from(MetadataWritebackTarget)) or 0
    )


def test_observer_schedules_new_metadata_changes_without_backfilling_on_enable(
    db_session: Session, test_settings, tmp_path: Path
) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    install_metadata_opf_observer(factory, test_settings)
    db = factory()
    source = tmp_path / "observed.epub"
    source.write_bytes(b"immutable")
    stat = source.stat()
    try:
        db.add(OrganizePolicy(id="default", write_metadata_to_files=False))
        db.add_all(
            [
                LibraryWork(
                    id="observed-work",
                    title="旧标题",
                    normalized_title="旧标题",
                    author="作者",
                    normalized_author="作者",
                    tags="[]",
                ),
                LibraryMediaVersion(
                    id="observed-media",
                    work_id="observed-work",
                    media_kind="EBOOK",
                ),
                LibraryVolume(
                    id="observed-volume",
                    media_version_id="observed-media",
                    title="第一卷",
                    format="EPUB",
                    resource_key="observed-volume",
                    import_status="READY",
                ),
                LibraryFile(
                    id="observed-file",
                    volume_id="observed-volume",
                    path=str(source),
                    hash_status="READY",
                    mtime_ms=int(stat.st_mtime * 1000),
                    kind="BOOK",
                    mime_type="application/epub+zip",
                    size_bytes=stat.st_size,
                ),
                ImportTask(
                    id="observed-import",
                    volume_id="observed-volume",
                    work_id="observed-work",
                    origin="MANUAL",
                    status="COMPLETED",
                    source_path=str(source),
                ),
            ]
        )
        db.commit()
        assert _pending_count(db) == 0

        policy = db.get(OrganizePolicy, "default")
        assert policy is not None
        policy.write_metadata_to_files = True
        db.commit()
        assert _pending_count(db) == 0

        work = db.get(LibraryWork, "observed-work")
        assert work is not None
        work.title = "新标题"
        db.commit()
        assert _pending_count(db) == 1

        volume = db.get(LibraryVolume, "observed-volume")
        assert volume is not None
        volume.narrator = "朗读者"
        db.flush()
        db.commit()
        assert _pending_count(db) == 2

        policy.write_metadata_to_files = False
        work.description = "关闭后的变化"
        db.commit()
        assert _pending_count(db) == 2
    finally:
        db.close()
