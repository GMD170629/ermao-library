"""Comic volume page index persistence.

Comic archives are indexed lazily: `LibraryReadingUnit` "page" rows are
materialized from the source archive the first time a volume's pages are
requested, either through the volume page routes or the reader v2 bootstrap
flow. Both call `ensure_volume_page_index` so they cannot disagree about
archive ordering.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns
from typing import Any

from sqlalchemy import MetaData, Table, func, insert, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.worker.importer import parse_comic_archive

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _has_table(db: Session, table: str) -> bool:
    return sa_inspect(db.connection()).has_table(table)


def _legacy_table(db: Session, table: str) -> Table | None:
    if not _has_table(db, table):
        return None
    metadata = MetaData()
    return Table(table, metadata, autoload_with=db.connection(), resolve_fks=False)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _stored_path(path_value: str | None, settings: Settings) -> Path | None:
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
        monitor = settings.resolved_monitor_root
        if monitor:
            monitor = monitor.resolve()
            if resolved == monitor or monitor in resolved.parents:
                return resolved
    except OSError:
        return None
    return None


def list_page_units_for_volume(db: Session, volume_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryReadingUnit")
    if table is None:
        return []
    rows = db.execute(
        select(table)
        .where(table.c.volumeId == volume_id, func.lower(table.c.unitType) == "page")
        .order_by(table.c.sortOrder)
    ).mappings().all()
    return [dict(row) for row in rows]


def get_page_unit(db: Session, volume_id: str, page_index: int) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryReadingUnit")
    if table is None:
        return None
    row = (
        db.execute(
            select(table).where(
                table.c.volumeId == volume_id,
                func.lower(table.c.unitType) == "page",
                table.c.sortOrder == page_index,
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_library_file(db: Session, file_id: str) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryFile")
    if table is None:
        return None
    row = db.execute(select(table).where(table.c.id == file_id)).mappings().first()
    return dict(row) if row else None


def _get_volume(db: Session, volume_table: Table, volume_id: str) -> dict[str, Any] | None:
    row = db.execute(select(volume_table).where(volume_table.c.id == volume_id)).mappings().first()
    return dict(row) if row else None


def _get_comic_file_for_volume(db: Session, file_table: Table, volume: dict[str, Any], volume_id: str) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(file_table)
            .where(file_table.c.volumeId == volume_id, file_table.c.kind == "COMIC")
            .order_by(file_table.c.sortOrder)
            .limit(1)
        )
        .mappings()
        .first()
    )
    if row is not None:
        return dict(row)
    edition_id = volume.get("editionId")
    if not edition_id:
        return None
    row = (
        db.execute(
            select(file_table)
            .where(file_table.c.editionId == edition_id, file_table.c.kind == "COMIC")
            .order_by(file_table.c.sortOrder)
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def _count_page_units(db: Session, unit_table: Table, volume_id: str) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(unit_table)
        .where(unit_table.c.volumeId == volume_id, func.lower(unit_table.c.unitType) == "page")
    )
    return int(count or 0)


def ensure_volume_page_index(db: Session, settings: Settings, volume_id: str) -> int:
    unit_table = _legacy_table(db, "LibraryReadingUnit")
    volume_table = _legacy_table(db, "LibraryVolume")
    file_table = _legacy_table(db, "LibraryFile")
    edition_table = _legacy_table(db, "LibraryEdition")
    if unit_table is None or volume_table is None or file_table is None:
        return 0

    existing = _count_page_units(db, unit_table, volume_id)
    if existing:
        return existing

    volume = _get_volume(db, volume_table, volume_id)
    if not volume:
        return 0
    file = _get_comic_file_for_volume(db, file_table, volume, volume_id)
    archive_path = _stored_path((file or {}).get("path"), settings)
    if not file or not archive_path:
        return 0

    try:
        parsed = parse_comic_archive(archive_path, Path(file.get("path") or archive_path).name)
    except Exception as exc:
        logger.warning(
            "failed to rebuild comic page index volume=%s file=%s error=%s",
            volume_id,
            file.get("id"),
            exc,
        )
        return 0

    now = _now()
    rows = [
        {
            "id": f"py_{time_ns()}_{page['index']}",
            "editionId": volume.get("editionId"),
            "volumeId": volume_id,
            "fileId": file.get("id"),
            "unitType": "page",
            "title": page["title"],
            "href": page["entryPath"],
            "mediaType": page["mediaType"],
            "sortOrder": page["index"],
            "size": page.get("size"),
            "metadataJson": _json_text(
                {
                    "zipEntryName": page["entryPath"],
                    "originalName": Path(page["entryPath"]).name,
                    "pageInVolume": page["index"],
                    "pageInSection": page["index"],
                    "volumeIndex": volume.get("volumeIndex"),
                    "sourceFileName": Path(file.get("path") or archive_path).name,
                }
            ),
            "createdAt": now,
            "updatedAt": now,
        }
        for page in parsed["pages"]
    ]
    if rows:
        try:
            db.execute(insert(unit_table), rows)
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = _count_page_units(db, unit_table, volume_id)
            if existing:
                return existing
            raise

    count = len(parsed["pages"])
    db.execute(update(volume_table).where(volume_table.c.id == volume_id).values(pageCount=count, updatedAt=now))
    db.commit()
    edition_id = volume.get("editionId")
    if edition_id and edition_table is not None:
        total = db.scalar(
            select(func.coalesce(func.sum(volume_table.c.pageCount), count)).where(volume_table.c.editionId == edition_id)
        )
        db.execute(
            update(edition_table)
            .where(edition_table.c.id == edition_id)
            .values(pageCount=int(total if total is not None else count), updatedAt=now)
        )
        db.commit()
    return count
