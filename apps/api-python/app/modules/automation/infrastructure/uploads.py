"""ORM upload journals and bounded, locked attachment staging."""

import hashlib
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.contracts.automation_upload import UploadError
from app.db.file_lock import try_file_lock, unlock_file
from app.infrastructure.file_operation_conflicts import file_operation_blocks_library
from app.models import Library, LibraryImportTask
from app.modules.automation.application.uploads import TRANSFER_STATES, UploadRecord
from app.modules.automation.infrastructure.upload_schema import AutomationUploadRow

_RECORD = TypeAdapter(UploadRecord)


class SqlAlchemyUploads:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, upload_id: str, user_id: str, grant_id: str) -> UploadRecord:
        row = self.db.scalar(
            select(AutomationUploadRow)
            .where(
                AutomationUploadRow.id == upload_id,
                AutomationUploadRow.user_id == user_id,
                AutomationUploadRow.grant_id == grant_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise UploadError("RESOURCE_NOT_FOUND")
        return _RECORD.validate_python(row.payload)

    def save(self, record: UploadRecord) -> None:
        row = self.db.get(AutomationUploadRow, record.id)
        if row is None:
            row = AutomationUploadRow(id=record.id)
            self.db.add(row)
        if (
            record.spec.purpose == "replace"
            and record.status == "PUBLISHING"
            and row.status not in {"PUBLISHING", "RECOVERY_REQUIRED"}
        ):
            flag_modified(row, "payload")
            self.db.flush()
            busy = self.db.scalar(
                select(Library.id).where(
                    Library.id == record.target.library_id,
                    file_operation_blocks_library(Library.id),
                )
            )
            importing = self.db.scalar(
                select(LibraryImportTask.id)
                .where(
                    LibraryImportTask.library_id == record.target.library_id,
                    LibraryImportTask.state == "RUNNING",
                )
                .limit(1)
            )
            if busy or importing:
                raise UploadError("LIBRARY_BUSY")
        row.user_id, row.grant_id = record.user_id, record.grant_id
        row.library_id = record.target.library_id
        row.status, row.size_bytes = record.status, record.spec.size_bytes
        row.created_at_ms, row.expires_at_ms = (
            record.created_at_ms,
            record.expires_at_ms,
        )
        row.payload = _RECORD.dump_python(record, mode="json")
        self.db.flush()

    def capacity(self, grant_id: str) -> tuple[int, int]:
        count, size = self.db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                AutomationUploadRow.status.in_(
                                    TRANSFER_STATES | {"SAVED"}
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                AutomationUploadRow.payload["staging_cleaned"]
                                .as_boolean()
                                .is_(False),
                                AutomationUploadRow.size_bytes,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(AutomationUploadRow.grant_id == grant_id)
        ).one()
        return int(count), int(size)

    def expired(self, now_ms: int) -> tuple[UploadRecord, ...]:
        return tuple(
            _RECORD.validate_python(row.payload)
            for row in self.db.scalars(
                select(AutomationUploadRow)
                .where(
                    AutomationUploadRow.expires_at_ms <= now_ms,
                    AutomationUploadRow.cleanup_after_ms <= now_ms,
                    AutomationUploadRow.payload["staging_cleaned"]
                    .as_boolean()
                    .is_(False),
                )
                .order_by(AutomationUploadRow.expires_at_ms, AutomationUploadRow.id)
                .limit(20)
            )
        )

    def defer_cleanup(self, upload_id: str, until_ms: int) -> None:
        self.db.execute(
            update(AutomationUploadRow)
            .where(AutomationUploadRow.id == upload_id)
            .values(cleanup_after_ms=until_ms)
        )
        self.db.flush()

    def mark_cleaned(self, record: UploadRecord) -> None:
        self.save(replace(record, staging_cleaned=True))


class StagedUploadFiles:
    def __init__(self, root: Path) -> None:
        self.root = root / "automation-uploads"

    def _path(self, upload_id: str, suffix: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", upload_id):
            raise UploadError("RESOURCE_NOT_FOUND")
        return self.root / (upload_id + suffix)

    @contextmanager
    def lock(self, upload_id: str) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(
            self._path(upload_id, ".lock"),
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "r+b") as handle:
            if not try_file_lock(handle, exclusive=True):
                raise UploadError("UPLOAD_BUSY")
            try:
                yield
            finally:
                unlock_file(handle)

    def append(self, upload_id: str, confirmed: int, offset: int, data: bytes) -> int:
        if offset > confirmed:
            raise UploadError("UPLOAD_OFFSET_MISMATCH")
        fd = os.open(
            self._path(upload_id, ".part"),
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "r+b") as handle:
            if os.fstat(handle.fileno()).st_size < confirmed:
                raise UploadError("UPLOAD_STAGING_MISSING")
            if offset < confirmed:
                handle.seek(offset)
                if offset + len(data) > confirmed or handle.read(len(data)) != data:
                    raise UploadError("UPLOAD_CHUNK_CONFLICT")
                return confirmed
            handle.truncate(
                confirmed
            )  # Discard bytes written before an uncommitted acknowledgement.
            handle.seek(confirmed)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return confirmed + len(data)

    def verify(self, upload_id: str, size: int, digest: str) -> Path:
        path = self._path(upload_id, ".part")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        observed = hashlib.sha256()
        with os.fdopen(fd, "rb") as handle:
            if os.fstat(handle.fileno()).st_size != size:
                raise UploadError("UPLOAD_SIZE_MISMATCH")
            while block := handle.read(1024 * 1024):
                observed.update(block)
        if observed.hexdigest() != digest:
            raise UploadError("UPLOAD_DIGEST_MISMATCH")
        return path

    def remove(self, upload_id: str) -> None:
        self._path(upload_id, ".part").unlink(missing_ok=True)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
