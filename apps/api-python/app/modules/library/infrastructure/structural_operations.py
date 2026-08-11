"""ORM adapter for media-version and volume structure changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import case, delete, insert, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.common import cuid
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.modules.library.application.dto import MoveVolumeResult


@dataclass(frozen=True, slots=True)
class PreparedVolumeMove:
    statements: tuple[Executable, ...]
    result: MoveVolumeResult


def _media_version_for_work(
    db: Session, *, work_id: str, media_kind: str
) -> LibraryMediaVersion | None:
    return db.scalar(
        select(LibraryMediaVersion)
        .where(
            LibraryMediaVersion.work_id == work_id,
            LibraryMediaVersion.media_kind == media_kind,
        )
        .limit(1)
    )


def _ordered_volume_rows(
    db: Session, media_version_id: str
) -> list[tuple[str, int, datetime]]:
    return [
        (str(row.id), int(row.sort_order), row.created_at)
        for row in db.execute(
            select(
                LibraryVolume.id,
                LibraryVolume.sort_order,
                LibraryVolume.created_at,
            )
            .where(LibraryVolume.media_version_id == media_version_id)
            .order_by(
                LibraryVolume.sort_order.asc(),
                LibraryVolume.created_at.asc(),
                LibraryVolume.id.asc(),
            )
        ).all()
    ]


def _prepare_volume_order_statements(
    rows: list[tuple[str, int, datetime]], now: datetime
) -> tuple[Executable, ...]:
    ordered_ids = tuple(
        row[0] for row in sorted(rows, key=lambda row: (row[1], row[2], row[0]))
    )
    positions = {
        volume_id: (index + 1) * 1000 for index, volume_id in enumerate(ordered_ids)
    }
    statements: list[Executable] = []
    for chunk in sqlite_parameter_chunks(ordered_ids, parameters_per_row=3):
        sort_orders = {volume_id: positions[volume_id] for volume_id in chunk}
        statements.append(
            update(LibraryVolume)
            .where(LibraryVolume.id.in_(chunk))
            .values(
                sort_order=case(sort_orders, value=LibraryVolume.id),
                updated_at=now,
            )
        )
    return tuple(statements)


def prepare_volume_move(
    db: Session,
    *,
    source_work_id: str,
    volume_id: str,
    target_work_id: str,
    now: datetime,
    target_work_prepared: bool = False,
) -> PreparedVolumeMove:
    """Project and prepare one resource move before acquiring a write lock."""

    source = db.execute(
        select(LibraryVolume, LibraryMediaVersion)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryVolume.id == volume_id,
            LibraryMediaVersion.work_id == source_work_id,
        )
    ).one_or_none()
    if source is None:
        raise ValueError("卷册不存在或不属于该作品")
    if not target_work_prepared and (
        db.scalar(select(LibraryWork.id).where(LibraryWork.id == target_work_id))
        is None
    ):
        raise ValueError("目标作品不存在")

    volume, source_media_version = source
    target_media_version = (
        None
        if target_work_prepared
        else _media_version_for_work(
            db, work_id=target_work_id, media_kind=source_media_version.media_kind
        )
    )
    source_media_version_id = source_media_version.id
    created = target_media_version is None
    target_media_version_id = (
        cuid() if target_media_version is None else target_media_version.id
    )
    source_rows = [
        row
        for row in _ordered_volume_rows(db, source_media_version_id)
        if row[0] != volume_id
    ]
    target_rows = (
        []
        if target_work_prepared
        else _ordered_volume_rows(db, target_media_version_id)
    )
    target_rows.append((volume.id, volume.sort_order, volume.created_at))
    source_media_ids = tuple(
        db.scalars(
            select(LibraryMediaVersion.id).where(
                LibraryMediaVersion.work_id == source_work_id
            )
        ).all()
    )
    write_statements: list[Executable] = []
    if created:
        write_statements.append(
            insert(LibraryMediaVersion).values(
                id=target_media_version_id,
                work_id=target_work_id,
                media_kind=source_media_version.media_kind,
                created_at=now,
                updated_at=now,
            )
        )
    write_statements.append(
        update(LibraryVolume)
        .where(LibraryVolume.id == volume_id)
        .values(media_version_id=target_media_version_id, updated_at=now)
    )
    write_statements.extend(_prepare_volume_order_statements(source_rows, now))
    write_statements.extend(_prepare_volume_order_statements(target_rows, now))
    if not source_rows:
        write_statements.append(
            delete(LibraryMediaVersion).where(
                LibraryMediaVersion.id == source_media_version_id
            )
        )
        if len(source_media_ids) == 1:
            write_statements.append(
                delete(LibraryWork).where(LibraryWork.id == source_work_id)
            )
    write_statements.append(
        update(LibraryWork)
        .where(LibraryWork.id == target_work_id)
        .values(updated_at=now)
    )
    return PreparedVolumeMove(
        statements=tuple(write_statements),
        result=MoveVolumeResult(
            source_media_version_id=source_media_version_id,
            target_media_version_id=target_media_version_id,
            target_work_id=target_work_id,
            transfer_mode=("CREATED_MEDIA_VERSION" if created else "APPENDED_VOLUME"),
        ),
    )


def execute_prepared_volume_move(db: Session, prepared: PreparedVolumeMove) -> None:
    for statement in prepared.statements:
        db.execute(statement)


def move_volume_to_work(
    db: Session,
    *,
    source_work_id: str,
    volume_id: str,
    target_work_id: str,
    now: datetime,
) -> MoveVolumeResult:
    """Move one resource without using a volume number as identity."""

    prepared = prepare_volume_move(
        db,
        source_work_id=source_work_id,
        volume_id=volume_id,
        target_work_id=target_work_id,
        now=now,
    )
    execute_prepared_volume_move(db, prepared)
    return prepared.result


def reorder_volume(
    db: Session,
    *,
    volume_id: str,
    media_version_id: str,
    direction: Literal["up", "down"],
    now: datetime,
) -> bool:
    volumes = db.execute(
        select(LibraryVolume.id, LibraryVolume.sort_order)
        .where(LibraryVolume.media_version_id == media_version_id)
        .order_by(LibraryVolume.sort_order.asc(), LibraryVolume.id.asc())
    ).all()
    index = next(
        (item_index for item_index, item in enumerate(volumes) if item.id == volume_id),
        -1,
    )
    target_index = index - 1 if direction == "up" else index + 1
    if index < 0 or target_index < 0 or target_index >= len(volumes):
        return False
    target = volumes[target_index]
    current = volumes[index]
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.id.in_((current.id, target.id)))
        .values(
            sort_order=case(
                {current.id: target.sort_order, target.id: current.sort_order},
                value=LibraryVolume.id,
            ),
            updated_at=now,
        )
    )
    return True
