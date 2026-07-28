from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DownloadTaskDTO:
    id: str
    source_id: str | None
    search_record_id: str | None
    book_id: str | None
    task_type: str
    status: str
    display_name: str
    remote_ref: str | None
    save_path: str | None
    file_path: str | None
    error_message: str | None
    progress: float | None
    created_at: datetime
    updated_at: datetime

    def to_legacy_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "sourceId": self.source_id,
            "searchRecordId": self.search_record_id,
            "bookId": self.book_id,
            "type": self.task_type,
            "status": self.status,
            "displayName": self.display_name,
            "remoteRef": self.remote_ref,
            "savePath": self.save_path,
            "filePath": self.file_path,
            "errorMessage": self.error_message,
            "progress": self.progress,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class CreateDownloadTask:
    id: str
    source_id: str | None
    search_record_id: str | None
    book_id: str | None
    task_type: str
    status: str
    display_name: str
    remote_ref: str | None
    save_path: str
    file_path: str | None
    error_message: str | None
    progress: float


@dataclass(frozen=True)
class UpdateDownloadTask:
    task_type: str | None = None
    status: str | None = None
    display_name: str | None = None
    save_path: str | None = None
    file_path: str | None = None
    error_message: str | None = None
    progress: float | None = None
    remote_ref: str | None = None
    changed_fields: frozenset[str] = frozenset()
