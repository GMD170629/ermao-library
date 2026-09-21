"""Immutable standard-metadata write intentions and recovery phases."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.contracts.file_operation import FileIdentity
from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.standard_files import StandardMetadataError

StandardWriteFormat = Literal[
    "OPF", "ComicInfo", "EPUB", "CBZ", "ZIP", "MP3", "M4A", "M4B", "FLAC", "PDF"
]


@dataclass(frozen=True)
class StandardWriteFile:
    library_id: str
    root: Path
    relative_path: str
    parent_device: int
    parent_inode: int
    format: StandardWriteFormat
    original: FileIdentity | None
    values: PublicationMetadata
    fields: frozenset[str]
    prepared_name: str
    backup_name: str


@dataclass(frozen=True)
class PreparedStandardFile:
    identity: FileIdentity
    sha256: str
    original_sha256: str | None


@dataclass(frozen=True)
class StandardWriteInspection:
    original: FileIdentity | None
    parent_device: int
    parent_inode: int
    before: PublicationMetadata


@dataclass(frozen=True)
class PlannedStandardWrite:
    file: StandardWriteFile
    source_node_id: str
    source_relative_path: str
    book_id: str
    resource_id: str | None
    asset_id: str | None
    metadata_target_type: str
    metadata_target_id: str
    metadata_revision: str
    before: PublicationMetadata


@dataclass(frozen=True)
class StandardWritePlan:
    id: str
    user_id: str
    grant_id: str
    created_at_ms: int
    expires_at_ms: int
    targets: tuple[PlannedStandardWrite, ...]


class StandardWriteInspectionPort(Protocol):
    def require_unshared_opf(
        self, root: Path, source_relative_path: str, *, directory: bool
    ) -> None: ...
    def inspect(
        self,
        root: Path,
        relative_path: str,
        format: StandardWriteFormat,
        values: PublicationMetadata,
        fields: frozenset[str],
    ) -> StandardWriteInspection: ...


class StandardPreparationError(StandardMetadataError):
    def __init__(self, code: str, prepared_identity: FileIdentity) -> None:
        super().__init__(code)
        self.prepared_identity = prepared_identity


@dataclass(frozen=True)
class StandardWriteStatus:
    operation_id: str
    plan: StandardWritePlan
    stages: tuple[str, ...]
    errors: tuple[str | None, ...]
    cancel_requested: bool


class StandardWritePlanStore(Protocol):
    def save(self, plan: StandardWritePlan) -> None: ...
    def load(self, plan_id: str, grant_id: str, user_id: str) -> StandardWritePlan: ...
    def enqueue(
        self, plan: StandardWritePlan, operation_id: str, request_id: str, now_ms: int
    ) -> str: ...
    def progress(
        self, operation_id: str, grant_id: str, user_id: str
    ) -> StandardWriteStatus: ...
    def cancel(
        self, operation_id: str, grant_id: str, user_id: str, now_ms: int
    ) -> StandardWriteStatus: ...
