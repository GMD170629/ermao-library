"""Comic volume page index persistence.

Comic archives are indexed lazily: `LibraryReadingUnit` "page" rows are
materialized from the source archive the first time a volume's pages are
requested, either through the volume page routes or the reader v3 bootstrap
flow. Both call `ensure_volume_page_index` so they cannot disagree about
archive ordering.
"""

from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.library import (
    LibraryFile,
    LibraryReadingUnit,
    LibraryVolume,
)
from app.modules.imports.application.import_comic import parse_comic_archive

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


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


@dataclass(frozen=True)
class _VolumeProjection:
    id: str
    volume_index: float | None


@dataclass(frozen=True)
class _FileProjection:
    id: str
    path: str


def _get_comic_file_for_volume(
    db: Session,
    volume: _VolumeProjection,
) -> _FileProjection | None:
    row = db.execute(
        select(
            LibraryFile.id,
            LibraryFile.path,
        )
        .where(
            LibraryFile.volume_id == volume.id,
            LibraryFile.kind == "COMIC",
        )
        .order_by(LibraryFile.sort_order)
        .limit(1)
    ).one_or_none()
    if row is not None:
        return _FileProjection(*row)
    return None


def _count_page_units(db: Session, volume_id: str) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(LibraryReadingUnit)
        .where(
            LibraryReadingUnit.volume_id == volume_id,
            func.lower(LibraryReadingUnit.unit_type) == "page",
        )
    )
    return int(count or 0)


def ensure_volume_page_index(db: Session, settings: Settings, volume_id: str) -> int:
    existing = _count_page_units(db, volume_id)
    if existing:
        return existing

    volume_row = db.execute(
        select(
            LibraryVolume.id,
            LibraryVolume.volume_index,
        ).where(LibraryVolume.id == volume_id)
    ).one_or_none()
    if volume_row is None:
        return 0
    volume = _VolumeProjection(*volume_row)
    file = _get_comic_file_for_volume(db, volume)
    archive_path = _stored_path(
        file.path if file else None,
        settings,
        database_backed=True,
    )
    if not file or not archive_path:
        return 0

    try:
        parsed = parse_comic_archive(
            archive_path,
            Path(file.path or archive_path).name,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        logger.warning(
            "failed to rebuild comic page index volume=%s file=%s error=%s",
            volume_id,
            file.id,
            exc,
        )
        return 0

    now = _now()
    unit_values = [
        {
            "id": f"py_{time_ns()}_{page['index']}",
            "volume_id": volume_id,
            "file_id": file.id,
            "unit_type": "page",
            "title": page["title"],
            "href": page["entryPath"],
            "media_type": page["mediaType"],
            "sort_order": page["index"],
            "size": page.get("size"),
            "metadata_json": _json_text(
                {
                    "zipEntryName": page["entryPath"],
                    "originalName": Path(page["entryPath"]).name,
                    "pageInVolume": page["index"],
                    "pageInSection": page["index"],
                    "volumeIndex": volume.volume_index,
                    "sourceFileName": Path(file.path or archive_path).name,
                }
            ),
            "created_at": now,
            "updated_at": now,
        }
        for page in parsed["pages"]
    ]
    if unit_values:
        try:
            with db.begin_nested():
                db.execute(insert(LibraryReadingUnit), unit_values)
                db.flush()
        except IntegrityError:
            existing = _count_page_units(db, volume_id)
            if existing:
                return existing
            raise

    count = len(parsed["pages"])
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.id == volume_id)
        .values(page_count=count, updated_at=now)
    )
    db.flush()
    return count
