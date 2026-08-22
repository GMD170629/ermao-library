"""Book and resource projections used by delivery adapters."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.library import get_book as load_book
from app.contracts.media_capabilities import (
    kindle_send_available_for_format,
    reader_type_for_format,
)
from app.models import (
    Library,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    ReaderResourceProgress,
)
from app.modules.library.application.bookshelf import BookshelfItemSummary


def _dt(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _parse_json(value: object, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return parsed


def _cover_url(
    kind: str,
    identity: str,
    book: dict[str, Any] | None = None,
    *,
    size: str | None = None,
) -> str:
    path = f"/api/{kind}/{quote(identity, safe='')}/cover"
    return f"{path}?size={quote(size, safe='')}" if size else path


def get_book(db: Session, book_id: str) -> dict[str, Any] | None:
    return load_book(db, book_id)


def _resource_rows(
    db: Session, book_id: str
) -> list[tuple[LibraryReadableResource, LibraryReadableResourceMetadata | None]]:
    return [
        (row[0], row[1])
        for row in db.execute(
            select(LibraryReadableResource, LibraryReadableResourceMetadata)
            .outerjoin(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .where(
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
            )
            .order_by(
                LibraryReadableResourceMetadata.resource_index.asc().nulls_last(),
                LibraryReadableResource.id.asc(),
            )
        ).all()
    ]


def _asset_rows(
    db: Session, resource_id: str
) -> list[
    tuple[
        LibraryResourceAsset,
        LibraryResourceAssetMetadata | None,
        LibrarySourceNode,
        Library,
    ]
]:
    return [
        (row[0], row[1], row[2], row[3])
        for row in db.execute(
            select(
                LibraryResourceAsset,
                LibraryResourceAssetMetadata,
                LibrarySourceNode,
                Library,
            )
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
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
    ]


def _resource_view(
    db: Session,
    resource: LibraryReadableResource,
    metadata: LibraryReadableResourceMetadata | None,
    *,
    progress: ReaderResourceProgress | None = None,
    include_assets: bool = True,
    sort_order: int = 0,
) -> dict[str, Any]:
    format_value = str(resource.format)
    reader_type = reader_type_for_format(format_value)
    assets = _asset_rows(db, resource.id) if include_assets else []
    asset_views: list[dict[str, Any]] = [
        {
            "id": asset.id,
            "resourceId": asset.resource_id,
            "sourceNodeId": asset.source_node_id,
            "role": asset.role,
            "mimeType": asset_metadata.mime_type
            if asset_metadata
            else "application/octet-stream",
            "sizeBytes": int(source.observed_size_bytes or 0),
            "path": str(Path(library.root_path) / source.relative_path),
            "kind": asset.role,
            "size": _format_bytes(source.observed_size_bytes),
            "mtimeMs": int(source.observed_mtime_ns // 1_000_000),
            "durationMs": asset_metadata.duration_ms if asset_metadata else None,
            "codec": asset_metadata.codec if asset_metadata else None,
            "discNumber": asset_metadata.disc_number if asset_metadata else None,
            "trackNumber": asset_metadata.track_number if asset_metadata else None,
            "sortOrder": int(asset.sequence_index or 0),
            "url": f"/api/assets/{quote(asset.id, safe='')}",
        }
        for asset, asset_metadata, source, library in assets
    ]
    total_size = sum(
        int(item["sizeBytes"])
        for item in asset_views
        if isinstance(item.get("sizeBytes"), (int, float, str))
    )
    media_kind = str(resource.media_kind)
    return {
        "id": resource.id,
        "bookId": resource.book_id,
        "sourceNodeId": resource.source_node_id,
        "title": metadata.title if metadata else "",
        "resourceIndex": metadata.resource_index if metadata else None,
        "sortOrder": sort_order,
        "format": format_value,
        "mediaKind": media_kind,
        "readerType": reader_type.value if reader_type else "reflowable",
        "classification": {
            "source": "AUTO",
            "reason": "FORMAT_DEFAULT",
            "suggestedMediaKind": media_kind,
        },
        "kindleSendAvailable": kindle_send_available_for_format(format_value),
        "publisher": metadata.publisher if metadata else None,
        "publishedAt": _dt(metadata.published_at) if metadata else None,
        "language": metadata.language if metadata else None,
        "isbn": metadata.isbn if metadata else None,
        "identifier": metadata.identifier if metadata else None,
        "narrator": metadata.narrator if metadata else None,
        "abridged": metadata.abridged if metadata else None,
        "importStatus": resource.import_state,
        "importError": None,
        "sizeBytes": total_size,
        "pageCount": metadata.page_count if metadata else None,
        "chapterCount": metadata.chapter_count if metadata else None,
        "durationMs": metadata.duration_ms if metadata else None,
        "trackCount": metadata.track_count if metadata else None,
        "coverStatus": metadata.cover_status if metadata else "PENDING",
        "coverPath": metadata.cover_path if metadata else None,
        "coverUrl": _cover_url("resources", resource.id),
        "progress": float(progress.percent if progress else 0),
        "lastReadAt": _dt(progress.updated_at) if progress else None,
        "resourceCompleted": bool(progress and progress.percent >= 100),
        "hidden": resource.enablement_state != "ENABLED",
        "readable": resource.import_state == "READY" and bool(asset_views),
        "assets": asset_views,
    }


def _format_bytes(value: int | None) -> str:
    size = max(0, int(value or 0))
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size //= 1024
        index += 1
    return f"{size} {units[index]}"


def book_view(
    db: Session, book: dict[str, Any], user_id: str | None = None
) -> dict[str, Any]:
    book_id = str(book["id"])
    progress_by_resource: dict[str, ReaderResourceProgress] = {}
    if user_id:
        resource_ids = [
            resource.id for resource, _metadata in _resource_rows(db, book_id)
        ]
        if resource_ids:
            progress_by_resource = {
                row.resource_id: row
                for row in db.scalars(
                    select(ReaderResourceProgress).where(
                        ReaderResourceProgress.user_id == user_id,
                        ReaderResourceProgress.resource_id.in_(resource_ids),
                    )
                ).all()
            }
    resources = [
        _resource_view(
            db,
            resource,
            metadata,
            progress=progress_by_resource.get(resource.id),
            sort_order=index,
        )
        for index, (resource, metadata) in enumerate(_resource_rows(db, book_id))
    ]
    unfinished = [item for item in resources if item["progress"] < 100]
    selected = max(
        (item for item in resources if item["lastReadAt"] is not None),
        key=lambda item: item["lastReadAt"],
        default=None,
    )
    return {
        **book,
        "tags": list(book.get("tags") or []),
        "ignored": book.get("visibilityState") != "VISIBLE",
        "organized": book.get("curationState") not in {None, "PENDING"},
        "addedAt": book.get("createdAt"),
        "updatedAt": book.get("updatedAt"),
        "gradient": "",
        "coverUrl": _cover_url("books", book_id, book, size="medium"),
        "resources": resources,
        "availableMediaKinds": sorted({str(item["mediaKind"]) for item in resources}),
        "completed": bool(resources) and not unfinished,
        "continueResourceId": selected["id"] if selected else None,
        "continueResourceTitle": selected["title"] if selected else None,
        "continueResourceProgress": selected["progress"] if selected else 0,
    }


def resource_view(
    db: Session,
    resource_id: str,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryReadableResource, LibraryReadableResourceMetadata)
        .outerjoin(
            LibraryReadableResourceMetadata,
            LibraryReadableResourceMetadata.resource_id == LibraryReadableResource.id,
        )
        .where(LibraryReadableResource.id == resource_id)
    ).first()
    if row is None:
        return None
    progress = None
    if user_id:
        progress = db.scalar(
            select(ReaderResourceProgress).where(
                ReaderResourceProgress.user_id == user_id,
                ReaderResourceProgress.resource_id == resource_id,
            )
        )
    return _resource_view(db, row[0], row[1], progress=progress)


def list_resource_views(
    db: Session,
    book_id: str,
    user_id: str | None,
    *,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Return one deterministic Resource page with actor-scoped progress."""

    rows = _resource_rows(db, book_id)
    total = len(rows)
    normalized_page = max(1, page)
    normalized_size = min(500, max(1, page_size))
    start = (normalized_page - 1) * normalized_size
    selected = rows[start : start + normalized_size]
    resource_ids = [resource.id for resource, _metadata in selected]
    progress_by_resource: dict[str, ReaderResourceProgress] = {}
    if user_id and resource_ids:
        progress_by_resource = {
            row.resource_id: row
            for row in db.scalars(
                select(ReaderResourceProgress).where(
                    ReaderResourceProgress.user_id == user_id,
                    ReaderResourceProgress.resource_id.in_(resource_ids),
                )
            ).all()
        }
    offset = start
    return (
        [
            _resource_view(
                db,
                resource,
                metadata,
                progress=progress_by_resource.get(resource.id),
                sort_order=offset + index,
            )
            for index, (resource, metadata) in enumerate(selected)
        ],
        normalized_page,
        normalized_size,
        total,
    )


def bookshelf_item_view(item: BookshelfItemSummary) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "author": item.author,
        "coverUrl": _cover_url("books", item.id, size="medium"),
        "availableMediaKinds": list(item.available_media_kinds),
        "progress": float(item.progress),
    }


def bookshelf_item_views(
    items: tuple[BookshelfItemSummary, ...] | list[BookshelfItemSummary],
) -> list[dict[str, Any]]:
    return [bookshelf_item_view(item) for item in items]


def bookshelf_book_list_view(item: dict[str, object]) -> dict[str, object]:
    """Map the ORM list projection to the public bookshelf wire shape."""

    book_id = str(item["id"])
    media_kinds = item.get("availableMediaKinds")
    progress = item.get("progress")
    return {
        "id": book_id,
        "title": str(item["title"]),
        "author": item.get("author"),
        "coverUrl": _cover_url("books", book_id, size="medium"),
        "availableMediaKinds": (
            list(media_kinds) if isinstance(media_kinds, (list, tuple)) else []
        ),
        "progress": (
            float(progress) if isinstance(progress, (int, float, str)) else 0.0
        ),
    }


def management_book_list_view(item: dict[str, object]) -> dict[str, object]:
    """Map the ORM list projection to the public management wire shape."""

    book_id = str(item["id"])
    tags = item.get("tags")
    media_kinds = item.get("availableMediaKinds")
    return {
        "id": book_id,
        "title": str(item["title"]),
        "author": item.get("author"),
        "gradient": str(item.get("gradient") or ""),
        "coverStatus": str(item.get("coverStatus") or "PENDING"),
        "coverUrl": _cover_url("books", book_id, size="medium"),
        "seriesName": item.get("seriesName"),
        "tags": list(tags) if isinstance(tags, (list, tuple)) else [],
        "availableMediaKinds": (
            list(media_kinds) if isinstance(media_kinds, (list, tuple)) else []
        ),
        "statusValue": str(item.get("statusValue") or "UNREAD"),
        "lastReadAt": item.get("lastReadAt"),
        "importedAt": item.get("importedAt"),
    }


def preferred_book_cover_path(book: dict[str, Any]) -> str | None:
    value = book.get("coverPath")
    return str(value) if value else None


__all__ = [
    "_cover_url",
    "book_view",
    "bookshelf_book_list_view",
    "bookshelf_item_view",
    "bookshelf_item_views",
    "get_book",
    "list_resource_views",
    "management_book_list_view",
    "preferred_book_cover_path",
    "resource_view",
]
