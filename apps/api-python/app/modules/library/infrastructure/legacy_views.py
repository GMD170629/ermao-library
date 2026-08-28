"""Legacy ORM projection adapter behind the Library composition boundary."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.media_capabilities import (
    exact_source_format,
    kindle_send_available_for_format,
    require_reader_type_for_format,
    resolve_asset_mime_type,
)
from app.core.natural_sort import natural_sort_key
from app.models import (
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    ReaderResourceProgress,
)
from app.modules.library.application.bookshelf import BookshelfItemSummary
from app.modules.library.domain.asset_titles import (
    AssetTitleCandidate,
    resolve_asset_display_titles,
)
from app.modules.library.infrastructure import books as library_books


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
    return library_books.get_book(db, book_id)


def _resource_rows(
    db: Session, book_id: str
) -> list[tuple[LibraryReadableResource, LibraryReadableResourceMetadata | None]]:
    rows = [
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
    return sorted(rows, key=_resource_order_key)


def _resource_order_key(
    row: tuple[LibraryReadableResource, LibraryReadableResourceMetadata | None],
) -> tuple[int, float, tuple[tuple[int, int | str], ...], str]:
    resource, metadata = row
    resource_index = metadata.resource_index if metadata else None
    title = metadata.title.strip() if metadata and metadata.title else resource.id
    return (
        1 if resource_index is None else 0,
        float(resource_index or 0),
        natural_sort_key(title),
        resource.id,
    )


def _asset_rows(
    db: Session, resource_id: str
) -> list[
    tuple[
        LibraryResourceAsset,
        LibraryResourceAssetMetadata | None,
        LibrarySourceNode,
    ]
]:
    rows = [
        (row[0], row[1], row[2])
        for row in db.execute(
            select(
                LibraryResourceAsset,
                LibraryResourceAssetMetadata,
                LibrarySourceNode,
            )
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
        ).all()
    ]
    return sorted(
        rows,
        key=lambda row: (
            row[1].disc_number if row[1] and row[1].disc_number else 1,
            row[1].track_number
            if row[1] and row[1].track_number is not None
            else 10**9,
            natural_sort_key(row[2].relative_path),
            row[0].id,
        ),
    )


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
    reader_type = require_reader_type_for_format(format_value)
    assets = _asset_rows(db, resource.id) if include_assets else []
    asset_titles = resolve_asset_display_titles(
        AssetTitleCandidate(
            asset_id=asset.id,
            metadata_title=asset_metadata.title if asset_metadata else None,
            source_filename=source.name,
        )
        for asset, asset_metadata, source in assets
    )
    asset_views: list[dict[str, Any]] = [
        {
            "id": asset.id,
            "resourceId": asset.resource_id,
            "sourceNodeId": asset.source_node_id,
            "role": asset.role,
            "title": asset_titles[asset.id],
            "sourceFormat": exact_source_format(
                resource_format=format_value, filename=source.name
            ),
            "mimeType": resolve_asset_mime_type(
                resource_format=format_value,
                asset_role=asset.role,
                filename=source.name,
                stored_mime_type=asset_metadata.mime_type if asset_metadata else None,
            ),
            "sizeBytes": int(source.observed_size_bytes or 0),
            "size": _format_bytes(source.observed_size_bytes),
            "mtimeMs": int(source.observed_mtime_ns // 1_000_000),
            "durationMs": asset_metadata.duration_ms if asset_metadata else None,
            "codec": asset_metadata.codec if asset_metadata else None,
            "bitrate": asset_metadata.bitrate if asset_metadata else None,
            "sampleRate": asset_metadata.sample_rate if asset_metadata else None,
            "channels": asset_metadata.channels if asset_metadata else None,
            "discNumber": asset_metadata.disc_number if asset_metadata else None,
            "trackNumber": asset_metadata.track_number if asset_metadata else None,
            "sortOrder": asset_index,
            "url": f"/api/assets/{quote(asset.id, safe='')}",
            "downloadUrl": f"/api/assets/{quote(asset.id, safe='')}?download=true",
        }
        for asset_index, (asset, asset_metadata, source) in enumerate(assets)
    ]
    total_size = sum(
        int(item["sizeBytes"])
        for item in asset_views
        if isinstance(item.get("sizeBytes"), (int, float, str))
    )
    return {
        "id": resource.id,
        "bookId": resource.book_id,
        "sourceNodeId": resource.source_node_id,
        "title": metadata.title if metadata else "",
        "description": metadata.description if metadata else None,
        "resourceIndex": metadata.resource_index if metadata else None,
        "sortOrder": sort_order,
        "format": format_value,
        "readerType": reader_type.value,
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
    candidates = unfinished or resources
    with_history = [item for item in candidates if item["lastReadAt"] is not None]
    selected = (
        max(
            with_history, key=lambda item: (item["lastReadAt"], -int(item["sortOrder"]))
        )
        if with_history
        else min(candidates, key=lambda item: (int(item["sortOrder"]), str(item["id"])))
        if candidates
        else None
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
        "progress": float(item.progress),
    }


def bookshelf_item_views(
    items: tuple[BookshelfItemSummary, ...] | list[BookshelfItemSummary],
) -> list[dict[str, Any]]:
    return [bookshelf_item_view(item) for item in items]


def bookshelf_book_list_view(item: dict[str, object]) -> dict[str, object]:
    """Map the ORM list projection to the public bookshelf wire shape."""

    book_id = str(item["id"])
    progress = item.get("progress")
    return {
        "id": book_id,
        "title": str(item["title"]),
        "author": item.get("author"),
        "coverUrl": _cover_url("books", book_id, size="medium"),
        "resourceImportSummary": item.get("resourceImportSummary"),
        "progress": (
            float(progress) if isinstance(progress, (int, float, str)) else 0.0
        ),
    }


def management_book_list_view(item: dict[str, object]) -> dict[str, object]:
    """Map the ORM list projection to the public management wire shape."""

    book_id = str(item["id"])
    tags = item.get("tags")
    return {
        "id": book_id,
        "title": str(item["title"]),
        "author": item.get("author"),
        "gradient": str(item.get("gradient") or ""),
        "coverStatus": str(item.get("coverStatus") or "PENDING"),
        "coverUrl": _cover_url("books", book_id, size="medium"),
        "seriesName": item.get("seriesName"),
        "tags": list(tags) if isinstance(tags, (list, tuple)) else [],
        "resourceImportSummary": item.get("resourceImportSummary"),
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
