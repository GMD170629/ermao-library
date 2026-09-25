"""Read-only page projections backed by ResourceAsset and SourceNode."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exception_diagnostics import record_exception
from app.infrastructure.bounded_inspection import InspectionLimitReached
from app.infrastructure.comic_archives import ComicArchiveError, inspect_comic_archive
from app.models import (
    Library,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    ReadableResourceNavigationUnit,
)
from app.modules.media.application.page_index import (
    ResourcePageIndexProjection,
    ResourcePageSource,
    ResourcePageUnit,
)
from app.modules.media.infrastructure.http_streaming import stored_path


def _stored_path(
    path_value: str | None,
    settings: Settings,
    allowed_source_roots: Iterable[Path] = (),
) -> Path | None:
    return stored_path(path_value, settings, allowed_source_roots)


class FilesystemComicArchivePageReader:
    """Cache only bounded, validated directory metadata, never page payloads."""

    _MAX_CACHE_BYTES = 16 * 1024 * 1024

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: OrderedDict[
            tuple[object, ...], tuple[tuple[ResourcePageUnit, ...], int]
        ] = OrderedDict()
        self._cache_bytes = 0

    def read(
        self, resource_id: str, source: ResourcePageSource
    ) -> tuple[tuple[ResourcePageUnit, ...], ResourcePageSource]:
        try:
            root = Path(source.source_root).expanduser().resolve(strict=True)
            candidate = root / source.path
            path = candidate.resolve(strict=True)
            if path != candidate or not path.is_relative_to(root) or not path.is_file():
                raise ValueError("comic archive source is outside its library root")
            before = path.stat()
            stamp = self._stamp(before)
            key = (resource_id, source.id, str(path), stamp)
            current_source = replace(
                source,
                size_bytes=before.st_size,
                mtime_ms=before.st_mtime_ns // 1_000_000,
                mtime_ns=before.st_mtime_ns,
                ctime_ns=before.st_ctime_ns,
            )
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    return cached[0], current_source
            inspection = inspect_comic_archive(path, include_cover=False)
            if self._stamp(path.stat()) != stamp:
                raise ValueError("comic archive changed during page inspection")
            pages = tuple(
                ResourcePageUnit(
                    id="comic-page:"
                    + hashlib.sha256(
                        f"{resource_id}\0{source.id}\0{index}\0{page['entryPath']}".encode()
                    ).hexdigest(),
                    resource_id=resource_id,
                    asset_id=source.id,
                    unit_type="page",
                    title=page["title"],
                    href=page["entryPath"],
                    media_type=page["mediaType"],
                    sort_order=index,
                    width=None,
                    height=None,
                    size=page["size"],
                    metadata_json="{}",
                    created_at=None,
                    updated_at=None,
                )
                for index, page in enumerate(inspection["pages"])
            )
            weight = sum(
                512 + len(page.href.encode()) + len(page.title.encode())
                for page in pages
            )
            if weight <= self._MAX_CACHE_BYTES:
                with self._lock:
                    existing = self._cache.get(key)
                    if existing is None:
                        self._cache[key] = (pages, weight)
                        self._cache_bytes += weight
                    else:
                        pages = existing[0]
                    self._cache.move_to_end(key)
                    while self._cache_bytes > self._MAX_CACHE_BYTES:
                        _, (_, evicted_weight) = self._cache.popitem(last=False)
                        self._cache_bytes -= evicted_weight
            return pages, current_source
        except (ComicArchiveError, InspectionLimitReached, OSError, ValueError) as error:
            record_exception(
                logging.getLogger(__name__),
                "modules.media.infrastructure.page_index.comic_archive_read.failed",
                error,
                context={"step": "comic_archive_page_index", "resource_id": resource_id},
            )
            return (), source

    @staticmethod
    def _stamp(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )


def _unit_columns():
    return (
        ReadableResourceNavigationUnit.id,
        ReadableResourceNavigationUnit.resource_id,
        ReadableResourceNavigationUnit.asset_id,
        ReadableResourceNavigationUnit.unit_type,
        ReadableResourceNavigationUnit.title,
        ReadableResourceNavigationUnit.href,
        ReadableResourceNavigationUnit.media_type,
        ReadableResourceNavigationUnit.sort_order,
        ReadableResourceNavigationUnit.width,
        ReadableResourceNavigationUnit.height,
        ReadableResourceNavigationUnit.size,
        ReadableResourceNavigationUnit.metadata_json,
        ReadableResourceNavigationUnit.created_at,
        ReadableResourceNavigationUnit.updated_at,
    )


def list_page_units_for_resource(db: Session, resource_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(*_unit_columns())
        .where(
            ReadableResourceNavigationUnit.resource_id == resource_id,
            func.lower(ReadableResourceNavigationUnit.unit_type) == "page",
        )
        .order_by(ReadableResourceNavigationUnit.sort_order)
    ).all()
    return [
        {
            "id": row.id,
            "resourceId": row.resource_id,
            "assetId": row.asset_id,
            "unitType": row.unit_type,
            "title": row.title,
            "href": row.href,
            "mediaType": row.media_type,
            "sortOrder": row.sort_order,
            "width": row.width,
            "height": row.height,
            "size": row.size,
            "metadataJson": row.metadata_json,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def get_page_unit(
    db: Session, resource_id: str, page_index: int
) -> dict[str, Any] | None:
    row = db.execute(
        select(*_unit_columns()).where(
            ReadableResourceNavigationUnit.resource_id == resource_id,
            func.lower(ReadableResourceNavigationUnit.unit_type) == "page",
            ReadableResourceNavigationUnit.sort_order == page_index,
        )
    ).first()
    if row is None:
        return None
    return {
        "id": row.id,
        "resourceId": row.resource_id,
        "assetId": row.asset_id,
        "unitType": row.unit_type,
        "title": row.title,
        "href": row.href,
        "mediaType": row.media_type,
        "sortOrder": row.sort_order,
        "width": row.width,
        "height": row.height,
        "size": row.size,
        "metadataJson": row.metadata_json,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def get_resource_asset(db: Session, asset_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(
            LibraryResourceAsset.id,
            LibraryResourceAsset.resource_id,
            LibraryResourceAsset.role,
            LibraryResourceAsset.import_state,
            LibraryResourceAsset.sequence_index,
            LibraryResourceAsset.sort_key,
            LibrarySourceNode.relative_path,
            LibrarySourceNode.observed_size_bytes,
            LibrarySourceNode.observed_mtime_ns,
            Library.root_path,
        )
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
        )
        .join(Library, Library.id == LibraryResourceAsset.library_id)
        .where(
            LibraryResourceAsset.id == asset_id,
            LibraryResourceAsset.import_state == "READY",
            LibrarySourceNode.physical_kind == "REGULAR_FILE",
        )
    ).first()
    if row is None:
        return None
    return {
        "id": row.id,
        "resourceId": row.resource_id,
        "role": row.role,
        "path": row.relative_path,
        "sourceRoot": row.root_path,
        "sizeBytes": int(row.observed_size_bytes or 0),
        "mtimeMs": int(row.observed_mtime_ns // 1_000_000),
        "sortOrder": int(row.sequence_index or 0),
    }


def load_read_only_page_index_projection(
    db: Session,
    resource_id: str,
) -> ResourcePageIndexProjection:
    page_rows = db.execute(
        select(*_unit_columns())
        .where(
            ReadableResourceNavigationUnit.resource_id == resource_id,
            func.lower(ReadableResourceNavigationUnit.unit_type) == "page",
        )
        .order_by(ReadableResourceNavigationUnit.sort_order)
    ).all()
    source_rows = db.execute(
        select(
            LibraryResourceAsset.id,
            LibrarySourceNode.relative_path,
            LibrarySourceNode.name,
            LibraryResourceAssetMetadata.mime_type,
            LibraryResourceAsset.role,
            LibraryResourceAsset.import_state,
            LibrarySourceNode.observed_size_bytes,
            LibraryResourceAsset.sequence_index,
            LibrarySourceNode.observed_mtime_ns,
            Library.root_path,
            LibraryResourceAsset.sort_key,
            LibraryReadableResource.format,
        )
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
        )
        .join(Library, Library.id == LibraryResourceAsset.library_id)
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryResourceAsset.resource_id,
        )
        .outerjoin(
            LibraryResourceAssetMetadata,
            LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
        )
        .where(
            LibraryResourceAsset.resource_id == resource_id,
            LibraryResourceAsset.import_state == "READY",
            LibrarySourceNode.physical_kind == "REGULAR_FILE",
        )
        .order_by(LibraryResourceAsset.sequence_index, LibraryResourceAsset.id)
    ).all()
    return ResourcePageIndexProjection(
        resource_id=resource_id,
        resource_index=None,
        persisted_pages=tuple(ResourcePageUnit(*row) for row in page_rows),
        resource_format=source_rows[0].format if source_rows else None,
        sources=tuple(
            ResourcePageSource(
                id=row.id,
                path=row.relative_path,
                title=row.name,
                mime_type=row.mime_type,
                source_root=row.root_path,
                role=row.role,
                import_state=row.import_state,
                size_bytes=int(row.observed_size_bytes or 0),
                sort_order=int(row.sequence_index or 0),
                mtime_ms=int(row.observed_mtime_ns // 1_000_000),
                sort_key=row.relative_path,
                mtime_ns=int(row.observed_mtime_ns),
            )
            for row in source_rows
        ),
    )


__all__ = [
    "FilesystemComicArchivePageReader",
    "_stored_path",
    "get_page_unit",
    "get_resource_asset",
    "list_page_units_for_resource",
    "load_read_only_page_index_projection",
]
