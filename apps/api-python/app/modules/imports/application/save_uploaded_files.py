"""Application contract for saving browser-uploaded source files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


class UploadPublicationError(RuntimeError):
    """A filesystem failure while publishing a selected upload batch."""

    def __init__(
        self, message: str, *, saved_files: tuple[SavedUploadFile, ...] = ()
    ) -> None:
        super().__init__(message)
        self.saved_files = saved_files


class UploadFileTooLargeError(UploadPublicationError):
    """An upload exceeded the shared single-file import allowance."""

    code = "IMPORT_FILE_TOO_LARGE"


def safe_upload_filename(value: str) -> str:
    """Normalize an untrusted upload name without changing its extension."""

    name = Path(value.replace("\\", "/")).name
    sanitized = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", name).strip(" .")
    return sanitized or "upload"


@dataclass(frozen=True)
class UploadSource:
    """A validated browser upload ready for filesystem publication."""

    filename: str
    stream: BinaryIO
    size_bytes: int | None = None


@dataclass(frozen=True)
class SaveUploadedFilesCommand:
    target_directory: Path
    sources: tuple[UploadSource, ...]


@dataclass(frozen=True)
class SavedUploadFile:
    filename: str
    path: Path
    size_bytes: int


class UploadedFilePublisher(Protocol):
    def publish(
        self, command: SaveUploadedFilesCommand
    ) -> tuple[SavedUploadFile, ...]: ...


class SaveUploadedFiles:
    """Save a batch without creating import-pipeline records."""

    def __init__(self, publisher: UploadedFilePublisher) -> None:
        self._publisher = publisher

    def execute(self, command: SaveUploadedFilesCommand) -> tuple[SavedUploadFile, ...]:
        return self._publisher.publish(command)
