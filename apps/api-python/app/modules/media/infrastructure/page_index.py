"""Read-only page projections backed by ResourceAsset and SourceNode."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    Library,
    LibraryResourceAsset,
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
            LibraryResourceAsset.role,
            LibraryResourceAsset.import_state,
            LibrarySourceNode.observed_size_bytes,
            LibraryResourceAsset.sequence_index,
            LibrarySourceNode.observed_mtime_ns,
            Library.root_path,
        )
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
        )
        .join(Library, Library.id == LibraryResourceAsset.library_id)
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
        sources=tuple(
            ResourcePageSource(
                id=row.id,
                path=row.relative_path,
                source_root=row.root_path,
                role=row.role,
                import_state=row.import_state,
                size_bytes=int(row.observed_size_bytes or 0),
                sort_order=int(row.sequence_index or 0),
                mtime_ms=int(row.observed_mtime_ns // 1_000_000),
            )
            for row in source_rows
        ),
    )


__all__ = [
    "_stored_path",
    "get_page_unit",
    "get_resource_asset",
    "list_page_units_for_resource",
    "load_read_only_page_index_projection",
]
