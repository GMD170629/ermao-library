"""Read-only persisted comic page-index projections."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.library import (
    LibraryFile,
    LibraryReadingUnit,
    LibraryVolume,
)
from app.modules.media.application.page_index import (
    VolumePageIndexProjection,
    VolumePageSource,
    VolumePageUnit,
)

def _stored_path(
    path_value: str | None,
    settings: Settings,
    allowed_source_roots: Iterable[Path] = (),
    *,
    database_backed: bool = False,
) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = settings.resolved_storage_root / path
    try:
        resolved = path.expanduser().resolve()
        storage = settings.resolved_storage_root.resolve()
        if resolved == storage or storage in resolved.parents:
            return resolved
        if database_backed and path.is_absolute():
            return resolved
        for source_root in allowed_source_roots:
            root = source_root.resolve()
            if resolved == root or root in resolved.parents:
                return resolved
    except OSError:
        return None
    return None


def list_page_units_for_volume(db: Session, volume_id: str) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(
                LibraryReadingUnit.id,
                LibraryReadingUnit.volume_id.label("volumeId"),
                LibraryReadingUnit.file_id.label("fileId"),
                LibraryReadingUnit.unit_type.label("unitType"),
                LibraryReadingUnit.title,
                LibraryReadingUnit.href,
                LibraryReadingUnit.media_type.label("mediaType"),
                LibraryReadingUnit.sort_order.label("sortOrder"),
                LibraryReadingUnit.width,
                LibraryReadingUnit.height,
                LibraryReadingUnit.size,
                LibraryReadingUnit.metadata_json.label("metadataJson"),
                LibraryReadingUnit.created_at.label("createdAt"),
                LibraryReadingUnit.updated_at.label("updatedAt"),
            )
            .where(
                LibraryReadingUnit.volume_id == volume_id,
                func.lower(LibraryReadingUnit.unit_type) == "page",
            )
            .order_by(LibraryReadingUnit.sort_order)
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def get_page_unit(
    db: Session, volume_id: str, page_index: int
) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(
                LibraryReadingUnit.id,
                LibraryReadingUnit.volume_id.label("volumeId"),
                LibraryReadingUnit.file_id.label("fileId"),
                LibraryReadingUnit.unit_type.label("unitType"),
                LibraryReadingUnit.title,
                LibraryReadingUnit.href,
                LibraryReadingUnit.media_type.label("mediaType"),
                LibraryReadingUnit.sort_order.label("sortOrder"),
                LibraryReadingUnit.width,
                LibraryReadingUnit.height,
                LibraryReadingUnit.size,
                LibraryReadingUnit.metadata_json.label("metadataJson"),
                LibraryReadingUnit.created_at.label("createdAt"),
                LibraryReadingUnit.updated_at.label("updatedAt"),
            ).where(
                LibraryReadingUnit.volume_id == volume_id,
                func.lower(LibraryReadingUnit.unit_type) == "page",
                LibraryReadingUnit.sort_order == page_index,
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_library_file(db: Session, file_id: str) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(
                LibraryFile.id,
                LibraryFile.volume_id.label("volumeId"),
                LibraryFile.path,
                LibraryFile.kind,
                LibraryFile.mime_type.label("mimeType"),
                LibraryFile.size_bytes.label("sizeBytes"),
                LibraryFile.sort_order.label("sortOrder"),
            ).where(LibraryFile.id == file_id)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def load_read_only_page_index_projection(
    db: Session,
    volume_id: str,
) -> VolumePageIndexProjection:
    """Load all database state needed before inspecting a comic archive."""

    volume_index = db.scalar(
        select(LibraryVolume.volume_index).where(LibraryVolume.id == volume_id)
    )
    page_rows = db.execute(
        select(
            LibraryReadingUnit.id,
            LibraryReadingUnit.volume_id,
            LibraryReadingUnit.file_id,
            LibraryReadingUnit.unit_type,
            LibraryReadingUnit.title,
            LibraryReadingUnit.href,
            LibraryReadingUnit.media_type,
            LibraryReadingUnit.sort_order,
            LibraryReadingUnit.width,
            LibraryReadingUnit.height,
            LibraryReadingUnit.size,
            LibraryReadingUnit.metadata_json,
            LibraryReadingUnit.created_at,
            LibraryReadingUnit.updated_at,
        )
        .where(
            LibraryReadingUnit.volume_id == volume_id,
            func.lower(LibraryReadingUnit.unit_type) == "page",
        )
        .order_by(LibraryReadingUnit.sort_order)
    ).all()
    source_rows = db.execute(
        select(
            LibraryFile.id,
            LibraryFile.path,
            LibraryFile.kind,
            LibraryFile.mime_type,
            LibraryFile.size_bytes,
            LibraryFile.sort_order,
        )
        .where(LibraryFile.volume_id == volume_id)
        .order_by(LibraryFile.sort_order, LibraryFile.id)
    ).all()
    return VolumePageIndexProjection(
        volume_id=volume_id,
        volume_index=volume_index,
        persisted_pages=tuple(VolumePageUnit(*row) for row in page_rows),
        sources=tuple(VolumePageSource(*row) for row in source_rows),
    )
