"""ORM queries used to build library work and reader projections."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, inspect as sa_inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.library import (
    LibraryConsumptionState,
    LibraryEdition,
    LibraryFile,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    WorkDetailPreference,
)
from app.models.organize import MetadataLookupTask
from app.modules.library.infrastructure.works import entity_as_legacy_dict
from app.modules.imports.infrastructure.schema import has_table, table_columns


def select_existing_rows(
    db: Session,
    model: type,
    table_name: str,
    *,
    filters: Sequence[ColumnElement[bool]] = (),
    order_by: Sequence[ColumnElement[Any]] = (),
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, object]]:
    if not has_table(db, table_name):
        return []
    column_attrs = [
        prop
        for prop in sa_inspect(model).mapper.column_attrs
        if prop.columns[0].name in table_columns(db, table_name)
    ]
    statement = select(*(getattr(model, prop.key) for prop in column_attrs)).where(
        *filters
    )
    if order_by:
        statement = statement.order_by(*order_by)
    if limit is not None:
        statement = statement.limit(limit)
    if offset is not None:
        statement = statement.offset(offset)
    rows = db.execute(statement).all()
    return [
        {
            column_attrs[index].columns[0].name: value
            for index, value in enumerate(row)
        }
        for row in rows
    ]


def get_detail_preference(
    db: Session,
    *,
    user_id: str,
    work_id: str,
) -> dict[str, object] | None:
    preference = db.scalar(
        select(WorkDetailPreference).where(
            WorkDetailPreference.user_id == user_id,
            WorkDetailPreference.work_id == work_id,
        )
    )
    return entity_as_legacy_dict(preference) if preference is not None else None


def save_detail_preference(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    selected_tab: str,
    now: datetime,
) -> dict[str, object]:
    preference = db.scalar(
        select(WorkDetailPreference).where(
            WorkDetailPreference.user_id == user_id,
            WorkDetailPreference.work_id == work_id,
        )
    )
    if preference is None:
        preference = WorkDetailPreference(
            id=f"py_{uuid4().hex}",
            user_id=user_id,
            work_id=work_id,
            selected_tab=selected_tab,
            created_at=now,
            updated_at=now,
        )
        db.add(preference)
    else:
        preference.selected_tab = selected_tab
        preference.updated_at = now
    db.flush()
    return entity_as_legacy_dict(preference)


def get_consumption_state(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    media_kind: str,
) -> dict[str, object] | None:
    state = db.scalar(
        select(LibraryConsumptionState).where(
            LibraryConsumptionState.user_id == user_id,
            LibraryConsumptionState.work_id == work_id,
            LibraryConsumptionState.media_kind == media_kind,
        )
    )
    return entity_as_legacy_dict(state) if state is not None else None


def save_consumption_state(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    media_kind: str,
    status: str,
    last_edition_id: str | None,
    last_volume_id: str | None,
    last_unit_id: str | None,
    now: datetime,
) -> dict[str, object]:
    state = db.scalar(
        select(LibraryConsumptionState).where(
            LibraryConsumptionState.user_id == user_id,
            LibraryConsumptionState.work_id == work_id,
            LibraryConsumptionState.media_kind == media_kind,
        )
    )
    if state is None:
        state = LibraryConsumptionState(
            id=f"py_{uuid4().hex}",
            user_id=user_id,
            work_id=work_id,
            media_kind=media_kind,
            status=status,
            last_edition_id=last_edition_id,
            last_volume_id=last_volume_id,
            last_unit_id=last_unit_id,
            created_at=now,
            updated_at=now,
        )
        db.add(state)
    else:
        state.status = status
        state.last_edition_id = last_edition_id
        state.last_volume_id = last_volume_id
        state.last_unit_id = last_unit_id
        state.updated_at = now
    db.flush()
    return entity_as_legacy_dict(state)


def get_edition(db: Session, edition_id: str) -> dict[str, object] | None:
    rows = select_existing_rows(
        db,
        LibraryEdition,
        "LibraryEdition",
        filters=(LibraryEdition.id == edition_id,),
        limit=1,
    )
    return rows[0] if rows else None


def list_consumption_states(
    db: Session,
    *,
    user_id: str,
    work_id: str,
) -> list[dict[str, object]]:
    states = db.scalars(
        select(LibraryConsumptionState).where(
            LibraryConsumptionState.user_id == user_id,
            LibraryConsumptionState.work_id == work_id,
        )
    ).all()
    return [entity_as_legacy_dict(state) for state in states]


def get_reading_unit_title(db: Session, unit_id: str) -> str | None:
    return db.scalar(
        select(LibraryReadingUnit.title).where(LibraryReadingUnit.id == unit_id)
    )


def list_files_for_edition(
    db: Session,
    edition_id: str,
) -> list[dict[str, object]]:
    return select_existing_rows(
        db,
        LibraryFile,
        "LibraryFile",
        filters=(LibraryFile.edition_id == edition_id,),
        order_by=(LibraryFile.sort_order.asc(), LibraryFile.id.asc()),
    )


def list_volumes_for_edition(
    db: Session,
    edition_id: str,
) -> list[dict[str, object]]:
    return select_existing_rows(
        db,
        LibraryVolume,
        "LibraryVolume",
        filters=(LibraryVolume.edition_id == edition_id,),
        order_by=(LibraryVolume.sort_order.asc(), LibraryVolume.id.asc()),
    )


def latest_conversion_metadata(
    db: Session,
    edition_id: str,
) -> dict[str, object] | None:
    rows = select_existing_rows(
        db,
        LibraryMetadata,
        "LibraryMetadata",
        filters=(
            LibraryMetadata.edition_id == edition_id,
            LibraryMetadata.source == "conversion",
        ),
        order_by=(LibraryMetadata.created_at.desc(), LibraryMetadata.id.desc()),
        limit=1,
    )
    return rows[0] if rows else None


def list_progress_for_edition(
    db: Session,
    *,
    edition_id: str,
    user_id: str,
) -> list[dict[str, object]]:
    return select_existing_rows(
        db,
        LibraryReadingProgress,
        "LibraryReadingProgress",
        filters=(
            LibraryReadingProgress.edition_id == edition_id,
            LibraryReadingProgress.user_id == user_id,
        ),
        order_by=(
            LibraryReadingProgress.updated_at.desc(),
            LibraryReadingProgress.id.desc(),
        ),
    )


def list_reading_units(
    db: Session,
    *,
    edition_id: str,
    volume_id: str | None = None,
) -> list[dict[str, object]]:
    filters: list[ColumnElement[bool]] = [
        LibraryReadingUnit.edition_id == edition_id
    ]
    if volume_id is not None:
        filters.append(LibraryReadingUnit.volume_id == volume_id)
    return select_existing_rows(
        db,
        LibraryReadingUnit,
        "LibraryReadingUnit",
        filters=filters,
        order_by=(
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.id.asc(),
        ),
    )


def reading_units_page(
    db: Session,
    *,
    edition_id: str,
    volume_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    if not has_table(db, "LibraryReadingUnit"):
        return [], 0
    filters: list[ColumnElement[bool]] = [
        LibraryReadingUnit.edition_id == edition_id
    ]
    if volume_id is not None:
        filters.append(LibraryReadingUnit.volume_id == volume_id)
    total = int(
        db.scalar(
            select(func.count(LibraryReadingUnit.id)).where(*filters)
        )
        or 0
    )
    rows = select_existing_rows(
        db,
        LibraryReadingUnit,
        "LibraryReadingUnit",
        filters=filters,
        order_by=(
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.id.asc(),
        ),
        limit=limit,
        offset=offset,
    )
    return rows, total


def latest_metadata_lookup_for_work(
    db: Session,
    work_id: str,
) -> dict[str, object] | None:
    rows = select_existing_rows(
        db,
        MetadataLookupTask,
        "MetadataLookupTask",
        filters=(MetadataLookupTask.work_id == work_id,),
        order_by=(
            MetadataLookupTask.created_at.desc(),
            MetadataLookupTask.id.desc(),
        ),
        limit=1,
    )
    return rows[0] if rows else None
