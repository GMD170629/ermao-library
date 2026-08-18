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
from app.models.library import LibraryVersion, LibraryVolume, LibraryWork
from app.modules.library.application.dto import MoveVolumeResult
from app.modules.library.infrastructure.implicit_version import (
    IMPLICIT_VERSION_SOURCE_KEY,
    get_or_create_implicit_version,
)


@dataclass(frozen=True, slots=True)
class PreparedVolumeMove:
    statements: tuple[Executable, ...]
    result: MoveVolumeResult


def _ordered_volume_rows(
    db: Session, version_id: str
) -> list[tuple[str, int, datetime]]:
    return [
        (str(row.id), int(row.sort_order), row.created_at)
        for row in db.execute(
            select(
                LibraryVolume.id,
                LibraryVolume.sort_order,
                LibraryVolume.created_at,
            )
            .where(LibraryVolume.version_id == version_id)
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
        select(LibraryVolume, LibraryVersion)
        .join(
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
        )
        .where(
            LibraryVolume.id == volume_id,
            LibraryVersion.work_id == source_work_id,
        )
    ).one_or_none()
    if source is None:
        raise ValueError("卷册不存在或不属于该作品")
    if not target_work_prepared:
        if (
            db.scalar(select(LibraryWork.id).where(LibraryWork.id == target_work_id))
            is None
        ):
            raise ValueError("目标作品不存在")
        source_library_id = db.scalar(
            select(LibraryWork.library_id).where(LibraryWork.id == source_work_id)
        )
        target_library_id = db.scalar(
            select(LibraryWork.library_id).where(LibraryWork.id == target_work_id)
        )
        if (
            source_library_id is None
            or target_library_id is None
            or source_library_id != target_library_id
        ):
            raise ValueError("CROSS_LIBRARY_OPERATION")

    volume, source_version = source
    source_version_id = source_version.id
    write_statements: list[Executable] = []
    if target_work_prepared:
        target_version_id = cuid()
        created = True
        write_statements.append(
            insert(LibraryVersion).values(
                id=target_version_id,
                work_id=target_work_id,
                source_key=IMPLICIT_VERSION_SOURCE_KEY,
                source_name=None,
                created_at=now,
                updated_at=now,
            )
        )
        target_rows: list[tuple[str, int, datetime]] = []
    else:
        existing_implicit_id = db.scalar(
            select(LibraryVersion.id).where(
                LibraryVersion.work_id == target_work_id,
                LibraryVersion.source_key == IMPLICIT_VERSION_SOURCE_KEY,
            )
        )
        target_version = get_or_create_implicit_version(db, target_work_id, now=now)
        target_version_id = target_version.id
        created = existing_implicit_id is None
        target_rows = _ordered_volume_rows(db, target_version_id)
    source_rows = [
        row
        for row in _ordered_volume_rows(db, source_version_id)
        if row[0] != volume_id
    ]
    target_rows.append((volume.id, volume.sort_order, volume.created_at))
    source_version_ids = tuple(
        db.scalars(
            select(LibraryVersion.id).where(LibraryVersion.work_id == source_work_id)
        ).all()
    )
    write_statements.append(
        update(LibraryVolume)
        .where(LibraryVolume.id == volume_id)
        .values(version_id=target_version_id, updated_at=now)
    )
    write_statements.extend(_prepare_volume_order_statements(source_rows, now))
    write_statements.extend(_prepare_volume_order_statements(target_rows, now))
    if not source_rows:
        write_statements.append(
            delete(LibraryVersion).where(LibraryVersion.id == source_version_id)
        )
        if len(source_version_ids) == 1:
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
            source_version_id=source_version_id,
            target_version_id=target_version_id,
            target_work_id=target_work_id,
            transfer_mode=("CREATED_VERSION" if created else "APPENDED_VOLUME"),
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
    version_id: str,
    direction: Literal["up", "down"],
    now: datetime,
) -> bool:
    volumes = db.execute(
        select(LibraryVolume.id, LibraryVolume.sort_order)
        .where(LibraryVolume.version_id == version_id)
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
