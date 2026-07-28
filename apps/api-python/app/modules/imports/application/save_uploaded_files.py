"""Application contract for saving browser-uploaded source files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


class UploadPublicationError(RuntimeError):
    """A filesystem failure while publishing a selected upload batch."""


class UploadFileTooLargeError(UploadPublicationError):
    """An upload exceeded its configured safety limit."""


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
    is_audio: bool
    max_bytes: int | None


@dataclass(frozen=True)
class SaveUploadedFilesCommand:
    target_directory: Path
    sources: tuple[UploadSource, ...]
    audio_bundle_max_bytes: int


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
