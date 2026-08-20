from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.bootstrap.library import delete_prepared_library_works
from app.bootstrap.system import prepare_system_event
from app.models.library import (
    LibraryFile,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.settings import SystemEvent
from app.modules.library.application.work_deletion import (
    DeleteLibraryWorks,
    PreparedFileQuarantineEntry,
    PreparedLibraryWorkDeletion,
)
from app.modules.library.infrastructure.deletion import (
    SqlAlchemyLibraryWorkDeletionStore,
)
from app.modules.library.infrastructure.file_quarantine import (
    LocalLibraryFileQuarantine,
)
from app.modules.system.public import PreparedSystemEvent


def _work_with_file(db: Session, path: Path, suffix: str) -> LibraryWork:
    work = LibraryWork(
        library_id="test-library",
        id=f"delete-work-{suffix}",
        origin="MANUAL",
        title="Delete me",
        normalized_title="delete me",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    version = LibraryVersion(
        id=f"delete-version-{suffix}",
        work_id=work.id,
        source_key=f"delete-source-{suffix}",
    )
    volume = LibraryVolume(
        id=f"delete-volume-{suffix}",
        version_id=version.id,
        title="Volume",
        sort_order=0,
        format="EPUB",
        resource_key=f"delete:{suffix}",
        import_status="COMPLETED",
    )
    file = LibraryFile(
        id=f"delete-file-{suffix}",
        volume_id=volume.id,
        path=str(path),
        mtime_ms=1,
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=path.stat().st_size,
        sort_order=0,
    )
    db.add(work)
    db.flush()
    db.add(version)
    db.flush()
    db.add(volume)
    db.flush()
    db.add(file)
    db.commit()
    return work


def _prepared(
    path: Path, work_id: str, event: PreparedSystemEvent
) -> PreparedLibraryWorkDeletion:
    quarantine_root = path.parent / ".quarantine" / work_id
    return PreparedLibraryWorkDeletion(
        work_ids=(work_id,),
        files=(
            PreparedFileQuarantineEntry(
                original_path=str(path),
                quarantine_path=str(quarantine_root / path.name),
                quarantine_root=str(quarantine_root),
                source_file=False,
            ),
        ),
        events=(event,),
    )


def test_work_deletion_commits_event_with_records_then_finalizes_file(
    db_session: Session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "success.epub"
    path.write_bytes(b"epub")
    work = _work_with_file(db_session, path, "success")
    event = prepare_system_event(
        level="error",
        source="library",
        action="deleted",
        target_type="work",
        target_id=work.id,
        message="deleted",
    )

    outcome = delete_prepared_library_works(db_session, _prepared(path, work.id, event))

    assert outcome.deleted == 1
    assert not path.exists()
    assert db_session.get(LibraryWork, work.id) is None
    assert db_session.query(SystemEvent).filter_by(target_id=work.id).count() == 1


def test_work_deletion_restores_quarantine_when_event_write_fails(
    db_session: Session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "rollback.epub"
    path.write_bytes(b"epub")
    work = _work_with_file(db_session, path, "rollback")
    event = prepare_system_event(
        level="error",
        source="library",
        action="deleted",
        target_type="work",
        target_id=work.id,
        message="deleted",
    )

    class FailingEvents:
        def write(self, _events: tuple[PreparedSystemEvent, ...]) -> None:
            raise RuntimeError("event unavailable")

    command = DeleteLibraryWorks(
        SqlAlchemyLibraryWorkDeletionStore(db_session),
        LocalLibraryFileQuarantine(),
        FailingEvents(),
        db_session,
    )

    with pytest.raises(RuntimeError, match="event unavailable"):
        command.execute(_prepared(path, work.id, event))

    assert path.read_bytes() == b"epub"
    db_session.expire_all()
    assert db_session.get(LibraryWork, work.id) is not None
