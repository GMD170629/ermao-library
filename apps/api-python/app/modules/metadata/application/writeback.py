"""Stable two-phase contracts for metadata file writeback scheduling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

NULL_SOURCE_REVISION = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class MetadataWritebackAssetProjection:
    id: str
    resource_id: str
    relative_path: str
    size_bytes: int
    mtime_ms: int


@dataclass(frozen=True, slots=True)
class MetadataWritebackImportProjection:
    resource_id: str
    source_path: str
    asset_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetadataWritebackResourceProjection:
    id: str
    resource_id: str
    title: str
    description: str | None
    resource_index: float | None
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
    book_id: str
    title: str
    author: str | None
    description: str | None
    tags_json: str
    series_name: str | None
    series_index: float | None
    cover_path: str | None
    source_revision: datetime | None
    resource_ids: tuple[str, ...]
    resources: tuple[MetadataWritebackResourceProjection, ...]
    assets: tuple[MetadataWritebackAssetProjection, ...]
    imports: tuple[MetadataWritebackImportProjection, ...]


@dataclass(frozen=True, slots=True)
class PreparedWritebackIntent:
    operation_id: str
    preparation_id: str
    book_id: str
    resource_id: str
    lookup_task_id: str | None
    asset_id: str | None
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
    resource_id: str | None = None,
) -> tuple[PreparedWritebackIntent, ...]:
    """Purely normalize one immutable projection into durable queue intents."""

    assets_by_resource: dict[str, list[dict[str, object]]] = {}
    for asset in projection.assets:
        assets_by_resource.setdefault(asset.resource_id, []).append(
            {
                "id": asset.id,
                "relativePath": asset.relative_path,
                "size": asset.size_bytes,
                "mtimeMs": asset.mtime_ms,
            }
        )
    imports_by_resource: dict[str, list[dict[str, object]]] = {}
    for imported in projection.imports:
        imports_by_resource.setdefault(imported.resource_id, []).append(
            {
                "sourcePath": imported.source_path,
                "assetPaths": list(imported.asset_paths),
            }
        )
    resources_by_book: dict[str, list[dict[str, object]]] = {}
    for resource in projection.resources:
        resources_by_book.setdefault(resource.resource_id, []).append(
            {
                "resourceId": resource.id,
                "payload": {
                    "title": projection.title,
                    "resourceTitle": resource.title,
                    "authors": _authors(projection.author),
                    "description": projection.description or resource.description,
                    "subjects": _tags(projection.tags_json),
                    "seriesName": projection.series_name,
                    "seriesIndex": projection.series_index,
                    "resourceIndex": resource.resource_index,
                    "narrators": _authors(resource.narrator),
                    "abridged": resource.abridged,
                    "language": resource.language,
                    "publisher": resource.publisher,
                    "publishedAt": (
                        resource.published_at.isoformat()
                        if resource.published_at
                        else None
                    ),
                    "identifier": resource.identifier,
                    "isbn": resource.isbn,
                    "coverPath": resource.cover_path or projection.cover_path,
                },
                "assets": assets_by_resource.get(resource.id, []),
                "importTasks": imports_by_resource.get(resource.id, []),
            }
        )

    revision = (projection.source_revision or NULL_SOURCE_REVISION).isoformat()
    intents: list[PreparedWritebackIntent] = []
    for current_resource_id in projection.resource_ids:
        snapshot_json = json.dumps(
            {"resources": resources_by_book.get(current_resource_id, [])},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        key_input = "\0".join(
            (
                projection.book_id,
                current_resource_id,
                current_resource_id or "",
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
                book_id=projection.book_id,
                asset_id=resource_id,
                lookup_task_id=lookup_task_id,
                resource_id=resource_id,
                source=source,
                idempotency_key=digest,
                source_revision=revision,
                snapshot_json=snapshot_json,
            )
        )
    return tuple(intents)


__all__ = [
    "MetadataWritebackAssetProjection",
    "MetadataWritebackImportProjection",
    "MetadataWritebackProjection",
    "MetadataWritebackResourceProjection",
    "PreparedWritebackIntent",
    "prepare_metadata_writeback_intents",
]
