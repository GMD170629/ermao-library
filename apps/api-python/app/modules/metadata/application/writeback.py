"""Stable two-phase contracts for metadata file writeback scheduling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

NULL_SOURCE_REVISION = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class MetadataWritebackFileProjection:
    id: str
    volume_id: str
    path: str
    size_bytes: int
    mtime_ms: int


@dataclass(frozen=True, slots=True)
class MetadataWritebackImportProjection:
    volume_id: str
    source_path: str
    asset_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetadataWritebackVolumeProjection:
    id: str
    version_id: str
    title: str
    description: str | None
    volume_index: float | None
    narrator: str | None
    abridged: bool | None
    language: str | None
    publisher: str | None
    published_at: datetime | None
    identifier: str | None
    isbn: str | None
    cover_path: str | None


@dataclass(frozen=True, slots=True)
class MetadataWritebackProjection:
    work_id: str
    title: str
    author: str | None
    description: str | None
    tags_json: str
    series_name: str | None
    series_index: float | None
    cover_path: str | None
    source_revision: datetime | None
    version_ids: tuple[str, ...]
    volumes: tuple[MetadataWritebackVolumeProjection, ...]
    files: tuple[MetadataWritebackFileProjection, ...]
    imports: tuple[MetadataWritebackImportProjection, ...]


@dataclass(frozen=True, slots=True)
class PreparedWritebackIntent:
    operation_id: str
    preparation_id: str
    work_id: str
    version_id: str
    lookup_task_id: str | None
    volume_id: str | None
    source: str
    idempotency_key: str
    source_revision: str
    snapshot_json: str


def _authors(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split(" / ") if part.strip()]


def _tags(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return (
        [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, list)
        else []
    )


def prepare_metadata_writeback_intents(
    projection: MetadataWritebackProjection,
    *,
    source: str,
    lookup_task_id: str | None = None,
    volume_id: str | None = None,
) -> tuple[PreparedWritebackIntent, ...]:
    """Purely normalize one immutable projection into durable queue intents."""

    files_by_volume: dict[str, list[dict[str, object]]] = {}
    for file in projection.files:
        files_by_volume.setdefault(file.volume_id, []).append(
            {
                "id": file.id,
                "path": file.path,
                "size": file.size_bytes,
                "mtimeMs": file.mtime_ms,
            }
        )
    imports_by_volume: dict[str, list[dict[str, object]]] = {}
    for imported in projection.imports:
        imports_by_volume.setdefault(imported.volume_id, []).append(
            {
                "sourcePath": imported.source_path,
                "assetPaths": list(imported.asset_paths),
            }
        )
    volumes_by_version: dict[str, list[dict[str, object]]] = {}
    for volume in projection.volumes:
        volumes_by_version.setdefault(volume.version_id, []).append(
            {
                "volumeId": volume.id,
                "payload": {
                    "title": projection.title,
                    "volumeTitle": volume.title,
                    "authors": _authors(projection.author),
                    "description": projection.description or volume.description,
                    "subjects": _tags(projection.tags_json),
                    "seriesName": projection.series_name,
                    "seriesIndex": projection.series_index,
                    "volumeIndex": volume.volume_index,
                    "narrators": _authors(volume.narrator),
                    "abridged": volume.abridged,
                    "language": volume.language,
                    "publisher": volume.publisher,
                    "publishedAt": (
                        volume.published_at.isoformat()
                        if volume.published_at
                        else None
                    ),
                    "identifier": volume.identifier,
                    "isbn": volume.isbn,
                    "coverPath": volume.cover_path or projection.cover_path,
                },
                "files": files_by_volume.get(volume.id, []),
                "importTasks": imports_by_volume.get(volume.id, []),
            }
        )

    revision = (projection.source_revision or NULL_SOURCE_REVISION).isoformat()
    intents: list[PreparedWritebackIntent] = []
    for version_id in projection.version_ids:
        snapshot_json = json.dumps(
            {"volumes": volumes_by_version.get(version_id, [])},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        key_input = "\0".join(
            (
                projection.work_id,
                version_id,
                volume_id or "",
                lookup_task_id or "",
                source,
                revision,
                snapshot_json,
            )
        )
        digest = hashlib.sha256(key_input.encode()).hexdigest()
        intents.append(
            PreparedWritebackIntent(
                operation_id=f"metadata_writeback_{digest}",
                preparation_id=f"metadata_writeback_preparation_{digest}",
                work_id=projection.work_id,
                version_id=version_id,
                lookup_task_id=lookup_task_id,
                volume_id=volume_id,
                source=source,
                idempotency_key=digest,
                source_revision=revision,
                snapshot_json=snapshot_json,
            )
        )
    return tuple(intents)


__all__ = [
    "MetadataWritebackFileProjection",
    "MetadataWritebackImportProjection",
    "MetadataWritebackProjection",
    "MetadataWritebackVolumeProjection",
    "PreparedWritebackIntent",
    "prepare_metadata_writeback_intents",
]
