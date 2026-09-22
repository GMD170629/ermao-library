"""Typed upload boundaries shared by Automation, Imports and Library."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.contracts.file_operation import FileIdentity


class UploadError(ValueError):
    """Public stable code; never contains file contents or private paths."""


@dataclass(frozen=True)
class UploadSpec:
    purpose: Literal["book", "cover", "replace"]
    filename: str
    size_bytes: int
    sha256: str
    library_id: str | None = None
    directory_node_id: str | None = None
    book_id: str | None = None
    expected_revision: str | None = None
    override: bool = False
    source_node_id: str | None = None
    expected_source_version: str | None = None


@dataclass(frozen=True)
class UploadActor:
    user_id: str
    grant_id: str
    library_ids: frozenset[str]
    can_override: bool


@dataclass(frozen=True)
class UploadTarget:
    library_id: str
    root: Path
    relative_path: str
    parent_device: int
    parent_inode: int
    original: FileIdentity | None = None


@dataclass(frozen=True)
class UploadPublication:
    target: UploadTarget
    staged_name: str
    identity: FileIdentity
    stored_cover_path: str | None = None
    backup_name: str | None = None
    # Missing versions describe historical publishers and must never be replayed.
    execution_version: int = 1


@dataclass(frozen=True)
class UploadOutcome:
    status: str
    task_id: str | None = None
    book_ids: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    cover_url: str | None = None
    revision: str | None = None
    error_code: str | None = None
