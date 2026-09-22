"""Freeze selected system metadata and explicit, authorized standard-file targets."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from app.modules.automation.application.catalog import AutomationCatalog
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
    WritebackTarget,
)
from app.modules.automation.domain.tools import (
    FILE_PLAN_BYTES_LIMIT,
    METADATA_BATCH_LIMIT,
    PLAN_LIFETIME_SECONDS,
)
from app.modules.library.public import (
    MetadataFileTarget,
    MetadataFileTargetPort,
    MetadataTarget,
    MetadataValue,
    file_path_collision_key,
)
from app.modules.metadata.public import (
    PlannedStandardWrite,
    PublicationMetadata,
    StandardWriteFile,
    StandardWriteFormat,
    StandardWriteInspectionPort,
    StandardWritePlan,
)

_METADATA_FIELDS = {
    "title": "title",
    "author": "authors",
    "description": "description",
    "tags": "subjects",
    "series_name": "series_name",
    "series_index": "series_index",
    "resource_index": "volume_index",
    "publisher": "publisher",
    "published_at": "published_at",
    "language": "language",
    "isbn": "isbn",
    "identifier": "identifier",
    "narrator": "narrators",
    "abridged": "abridged",
}


@dataclass(frozen=True)
class StandardWriteSelection:
    target_type: MetadataTarget
    target_id: str
    expected_revision: str
    node_id: str
    mode: Literal["opf", "comicinfo", "embedded"]
    fields: frozenset[str]
    clear_fields: frozenset[str] = frozenset()


def _destination(
    source: MetadataFileTarget, mode: str
) -> tuple[str, StandardWriteFormat]:
    path = PurePosixPath(source.relative_path)
    if mode == "opf":
        return str(
            path / "metadata.opf" if source.directory else path.with_suffix(".opf")
        ), "OPF"
    if mode == "comicinfo" and source.directory and source.format == "IMAGE_DIR":
        return str(path / "ComicInfo.xml"), "ComicInfo"
    if mode == "embedded" and not source.directory:
        extension = path.suffix.lower()
        if source.format == "EPUB" and extension == ".epub":
            return str(path), "EPUB"
        if source.format in {"COMIC", "CBZ", "ZIP"} and extension in {".cbz", ".zip"}:
            return str(path), "CBZ" if extension == ".cbz" else "ZIP"
        if source.format == "PDF" and extension == ".pdf":
            return str(path), "PDF"
        audio: dict[str, StandardWriteFormat] = {
            ".mp3": "MP3",
            ".m4a": "M4A",
            ".m4b": "M4B",
            ".flac": "FLAC",
        }
        if (
            source.format in {"AUDIO", "AUDIOBOOK_DIR", "MP3", "M4A", "M4B", "FLAC"}
            and extension in audio
        ):
            return str(path), audio[extension]
    raise AutomationAccessError("UNSUPPORTED_WRITEBACK_TARGET")


def _values(
    request: StandardWriteSelection, values: dict[str, MetadataValue]
) -> tuple[PublicationMetadata, frozenset[str]]:
    if (
        not request.fields
        or not request.fields <= values.keys()
        or not request.fields <= _METADATA_FIELDS.keys()
        or not request.clear_fields <= request.fields
    ):
        raise AutomationAccessError("INVALID_FIELDS")
    selected: dict[str, MetadataValue] = {}
    for name in request.fields:
        value = values[name]
        empty = value in (None, "", ())
        if empty != (name in request.clear_fields):
            raise AutomationAccessError(
                "EXPLICIT_CLEAR_REQUIRED" if empty else "SYSTEM_FIELD_NOT_EMPTY"
            )
        if name in {"author", "narrator"}:
            value = tuple(
                part.strip() for part in str(value or "").split(" / ") if part.strip()
            )
        if name == "tags" and empty:
            value = ()
        selected[_METADATA_FIELDS[name]] = value

    def text(name: str) -> str | None:
        value = selected.get(name)
        if value is not None and not isinstance(value, str):
            raise AutomationAccessError("INVALID_SYSTEM_FIELD")
        return value

    def names(name: str) -> tuple[str, ...]:
        value = selected.get(name)
        if value is None:
            return ()
        if not isinstance(value, tuple):
            raise AutomationAccessError("INVALID_SYSTEM_FIELD")
        return value

    def number(name: str) -> float | None:
        value = selected.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AutomationAccessError("INVALID_SYSTEM_FIELD")
        return float(value)

    abridged = selected.get("abridged")
    if abridged is not None and not isinstance(abridged, bool):
        raise AutomationAccessError("INVALID_SYSTEM_FIELD")
    return PublicationMetadata(
        title=text("title"),
        authors=names("authors"),
        description=text("description"),
        subjects=names("subjects"),
        series_name=text("series_name"),
        series_index=number("series_index"),
        volume_index=number("volume_index"),
        publisher=text("publisher"),
        published_at=text("published_at"),
        language=text("language"),
        isbn=text("isbn"),
        identifier=text("identifier"),
        narrators=names("narrators"),
        abridged=abridged,
    ), frozenset(selected)


@dataclass(frozen=True)
class BuildStandardWritePlan:
    catalog: AutomationCatalog
    sources: MetadataFileTargetPort
    files: StandardWriteInspectionPort
    clock_ms: Callable[[], int]
    new_id: Callable[[], str]

    def execute(
        self, access: EffectiveAccess, requests: tuple[StandardWriteSelection, ...]
    ) -> StandardWritePlan:
        access.require(Scope.SYSTEM_READ, Scope.FILES_MODIFY)
        if not 1 <= len(requests) <= METADATA_BATCH_LIMIT:
            raise AutomationAccessError("INVALID_TARGETS")
        prepared = []
        for request in requests:
            self.catalog.require_metadata_source(
                access, request.target_type, request.target_id, request.node_id
            )
            snapshot = self.catalog.metadata.snapshot(
                request.target_type, request.target_id, access.permissions.library_ids
            )
            source = self.sources.get(request.node_id, access.permissions.library_ids)
            if snapshot is None or source is None or snapshot.book_id != source.book_id:
                raise AutomationAccessError("RESOURCE_NOT_FOUND")
            if snapshot.revision != request.expected_revision:
                raise AutomationAccessError("METADATA_CONFLICT")
            access.require_writeback(
                WritebackTarget.EMBEDDED
                if request.mode == "embedded"
                else WritebackTarget.SIDECAR,
                source.library_id,
            )
            path, format = _destination(source, request.mode)
            values, fields = _values(request, snapshot.values)
            prepared.append((request, source, path, format, values, fields))
        keys = [
            (source.library_id, file_path_collision_key(path))
            for _, source, path, _, _, _ in prepared
        ]
        if len(set(keys)) != len(keys):
            raise AutomationAccessError("SHARED_WRITEBACK_TARGET")
        plan_id = self.new_id()
        targets = []
        size = 0
        physical_targets: set[tuple[int, int, str]] = set()
        for index, (request, source, path, format, values, fields) in enumerate(
            prepared
        ):
            if format == "OPF":
                self.files.require_unshared_opf(
                    source.root, source.relative_path, directory=source.directory
                )
            observed = self.files.inspect(source.root, path, format, values, fields)
            physical = (
                observed.parent_device,
                observed.parent_inode,
                file_path_collision_key(PurePosixPath(path).name),
            )
            if physical in physical_targets:
                raise AutomationAccessError("SHARED_WRITEBACK_TARGET")
            physical_targets.add(physical)
            size += observed.original.size if observed.original else 0
            if size > FILE_PLAN_BYTES_LIMIT:
                raise AutomationAccessError("FILE_PLAN_BYTE_LIMIT")
            slot = hashlib.sha256(f"{plan_id}:{index}".encode()).hexdigest()[:32]
            targets.append(
                PlannedStandardWrite(
                    StandardWriteFile(
                        source.library_id,
                        source.root,
                        path,
                        observed.parent_device,
                        observed.parent_inode,
                        format,
                        observed.original,
                        values,
                        fields,
                        f".ermao-mcp-{slot}-target",
                        f".ermao-mcp-{slot}-source",
                    ),
                    source.node_id,
                    source.relative_path,
                    source.book_id,
                    source.resource_id,
                    source.asset_id,
                    request.target_type,
                    request.target_id,
                    request.expected_revision,
                    observed.before,
                )
            )
        now = self.clock_ms()
        return StandardWritePlan(
            plan_id,
            access.user_id,
            access.grant_id,
            now,
            now + PLAN_LIFETIME_SECONDS * 1000,
            tuple(targets),
        )
