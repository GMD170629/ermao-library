"""Migrate every stored reading position to the Reader v3 location contract.

Revision ID: 0016_reader_progress_v3
Revises: 0015_management_query_indexes
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_reader_progress_v3"
down_revision: str | Sequence[str] | None = "0015_management_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed: object = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value: object) -> int | float | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _legacy_location(
    row: Mapping[object, object],
    *,
    volume_format: str | None,
    first_file_id: str | None,
) -> dict[str, object]:
    reader_type = _string(row.get("readerType")) or "reflowable"
    volume_id = _string(row.get("volumeId")) or ""
    extra = _mapping(row.get("extra"))

    if reader_type == "comic":
        return {
            "type": "comic",
            "volumeId": volume_id,
            "pageIndex": _number(extra.get("pageIndex"))
            or _number(row.get("page"))
            or 1,
        }
    if reader_type == "pdf":
        return {
            "type": "pdf",
            "volumeId": volume_id,
            "pageNumber": _number(extra.get("pageNumber"))
            or _number(row.get("page"))
            or 1,
        }
    if reader_type == "audio":
        position_ms = _number(extra.get("positionMs"))
        if position_ms is None:
            try:
                position_ms = int(float(str(row.get("position") or 0)))
            except ValueError:
                position_ms = 0
        location: dict[str, object] = {
            "type": "audio",
            "volumeId": volume_id,
            "fileId": _string(extra.get("fileId")) or first_file_id or volume_id,
            "positionMs": position_ms,
        }
        for key in ("chapterId",):
            value = _string(extra.get(key))
            if value is not None:
                location[key] = value
        return location

    percent = _number(row.get("percent")) or 0
    source_format = _string(extra.get("sourceFormat")) or (
        volume_format.lower() if volume_format else "epub"
    )
    if source_format not in {"epub", "mobi", "azw", "azw3", "prc", "fb2", "txt"}:
        source_format = "epub"
    location = {
        "type": "reflowable",
        "volumeId": volume_id,
        "format": source_format,
        "progression": _number(extra.get("progression"))
        or max(0.0, min(1.0, float(percent) / 100)),
    }
    for key in ("cfi",):
        value = _string(extra.get(key))
        if value is not None:
            location[key] = value
    href = _string(extra.get("currentHref")) or _string(extra.get("chapterHref"))
    if href is not None:
        location["href"] = href

    toc: dict[str, object] = {}
    toc_values = {
        "index": _number(extra.get("chapterIndex")),
        "title": _string(extra.get("chapterTitle")),
        "href": href,
        "navigationKey": _string(extra.get("navigationKey")),
    }
    toc.update({key: value for key, value in toc_values.items() if value is not None})
    section_values = {
        "current": _number(extra.get("sectionIndex")),
        "total": _number(extra.get("sectionTotal")),
    }
    section = {key: value for key, value in section_values.items() if value is not None}
    location_values = {
        "current": _number(extra.get("locationCurrent")),
        "next": _number(extra.get("locationNext")),
        "total": _number(extra.get("locationTotal")),
    }
    foliate_location = {
        key: value for key, value in location_values.items() if value is not None
    }
    foliate: dict[str, object] = {}
    if toc:
        foliate["toc"] = toc
    if section:
        foliate["section"] = section
    if foliate_location:
        foliate["location"] = foliate_location
    if foliate:
        location["foliate"] = foliate
    return location


def upgrade() -> None:
    progress = sa.table(
        "LibraryReadingProgress",
        sa.column("id", sa.String(length=191)),
        sa.column("volumeId", sa.String(length=191)),
        sa.column("readerType", sa.String(length=191)),
        sa.column("position", sa.Text()),
        sa.column("page", sa.Integer()),
        sa.column("percent", sa.Float()),
        sa.column("extra", sa.Text()),
        sa.column("schemaVersion", sa.Integer()),
        sa.column("locationType", sa.String(length=191)),
        sa.column("locationJson", sa.Text()),
    )
    volume = sa.table(
        "LibraryVolume",
        sa.column("id", sa.String(length=191)),
        sa.column("format", sa.String(length=191)),
    )
    library_file = sa.table(
        "LibraryFile",
        sa.column("id", sa.String(length=191)),
        sa.column("volumeId", sa.String(length=191)),
        sa.column("sortOrder", sa.Integer()),
    )
    connection = op.get_bind()
    while True:
        rows = (
            connection.execute(
                sa.select(progress)
                .where(
                    sa.or_(
                        progress.c.schemaVersion != 3,
                        progress.c.locationJson.is_(None),
                    )
                )
                .order_by(progress.c.id.asc())
                .limit(500)
            )
            .mappings()
            .all()
        )
        if not rows:
            break
        volume_ids = [str(row["volumeId"]) for row in rows]
        volume_formats = {
            str(volume_id): str(volume_format)
            for volume_id, volume_format in connection.execute(
                sa.select(volume.c.id, volume.c.format).where(
                    volume.c.id.in_(volume_ids)
                )
            )
        }
        first_file_ids: dict[str, str] = {}
        for volume_id, file_id in connection.execute(
            sa.select(library_file.c.volumeId, library_file.c.id)
            .where(library_file.c.volumeId.in_(volume_ids))
            .order_by(
                library_file.c.volumeId.asc(),
                library_file.c.sortOrder.asc(),
                library_file.c.id.asc(),
            )
        ):
            first_file_ids.setdefault(str(volume_id), str(file_id))
        for row in rows:
            row_values: dict[object, object] = {
                key: value for key, value in row.items()
            }
            volume_id = str(row["volumeId"])
            location = _legacy_location(
                row_values,
                volume_format=volume_formats.get(volume_id),
                first_file_id=first_file_ids.get(volume_id),
            )
            connection.execute(
                sa.update(progress)
                .where(progress.c.id == row["id"])
                .values(
                    schemaVersion=3,
                    locationType=location["type"],
                    locationJson=json.dumps(
                        location, ensure_ascii=False, separators=(",", ":")
                    ),
                    extra="{}",
                )
            )

    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.alter_column(
            "schemaVersion",
            existing_type=sa.Integer(),
            server_default="3",
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.alter_column(
            "schemaVersion",
            existing_type=sa.Integer(),
            server_default="1",
            nullable=False,
        )
