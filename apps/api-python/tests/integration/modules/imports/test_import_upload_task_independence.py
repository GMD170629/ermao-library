"""An upload result is not controlled by older failed Book executions."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.contracts.automation_upload import UploadOutcome, UploadSpec, UploadTarget
from app.core.config import Settings
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.imports.infrastructure.automation_uploads import (
    ImportAttachmentUploads,
)
from app.modules.library.public import SourceNodeRelativePath


def test_older_failed_book_does_not_fail_completed_upload(
    db_session: Session, test_settings: Settings, tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    node = LibrarySourceNode(
        id="node", library_id="test-library", relative_path="one.txt",
        path_key=SourceNodeRelativePath("one.txt").path_key,
        name="one.txt", physical_kind="REGULAR_FILE",
        observed_size_bytes=1, observed_mtime_ns=1, observed_at=now,
    )
    db_session.add(node)
    db_session.flush()
    db_session.add(LibraryBook(
        id="book", library_id="test-library", source_node_id="node",
    ))
    db_session.flush()
    db_session.add(LibraryBookMetadata(
        book_id="book", title="Book", normalized_title="book",
        metadata_pending=False, metadata_state="COMPLETED",
    ))
    db_session.add(LibraryReadableResource(
        id="resource", library_id="test-library", book_id="book",
        source_node_id="node", adapter_id="txt", adapter_version="1",
        format="TXT", import_state="READY",
    ))
    db_session.flush()
    db_session.add(LibraryResourceAsset(
        id="asset", library_id="test-library", resource_id="resource",
        source_node_id="node", role="PRIMARY", import_state="READY",
    ))
    db_session.add_all([
        LibraryImportTask(
            id="old-failure", kind="IMPORT_BOOK", library_id="test-library",
            book_id="book", source_node_id="node", state="FAILED",
            phase="FINALIZE", book_work='{"scanScopes":[],"resourceIds":["resource"],"identify":true,"reasons":[]}',
            error_summary="PARSE_FAILED", created_at=now - timedelta(days=1),
        ),
        LibraryImportTask(
            id="upload-scan", kind="SCAN_LIBRARY", library_id="test-library",
            state="SUCCEEDED", created_at=now,
        ),
    ])
    db_session.commit()
    uploads = ImportAttachmentUploads(
        db_session, test_settings, open_directory=lambda *_: nullcontext(0),
    )
    result = uploads.progress(
        UploadSpec(purpose="book", filename="one.txt", size_bytes=1, sha256="0" * 64,
                   library_id="test-library"),
        UploadTarget(
            library_id="test-library", root=tmp_path, relative_path="one.txt",
            parent_device=0, parent_inode=0,
        ),
        UploadOutcome("QUEUED", task_id="upload-scan"),
    )
    assert result.status == "COMPLETED"
    assert result.book_ids == ("book",)
    assert db_session.get(LibraryImportTask, "old-failure").state == "FAILED"
    db_session.add(LibraryImportTask(
        id="current-book", kind="IMPORT_BOOK", library_id="test-library",
        book_id="book", source_node_id="node", state="QUEUED", phase="RESOURCES",
        book_work='{"scanScopes":[],"resourceIds":["resource"],"identify":true,"reasons":[]}',
        created_at=now + timedelta(seconds=1),
    ))
    db_session.commit()
    assert uploads.progress(
        UploadSpec(purpose="book", filename="one.txt", size_bytes=1, sha256="0" * 64,
                   library_id="test-library"),
        UploadTarget(
            library_id="test-library", root=tmp_path, relative_path="one.txt",
            parent_device=0, parent_inode=0,
        ),
        UploadOutcome("QUEUED", task_id="upload-scan"),
    ).status == "IMPORTING"
