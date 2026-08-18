"""ORM persistence for volume-only library operation snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import time_ns
from typing import Any

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.auth import ReaderBookmark
from app.models.import_pipeline import (
    BookConversionTask,
    ImportAsset,
    ImportTask,
    KindleSendTask,
)
from app.models.library import (
    LibraryFacet,
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryOperation,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVersion,
    LibraryVolume,
    LibraryVolumeFacet,
    LibraryWork,
    LibraryWorkFacet,
    UserMediaHistory,
    WorkDetailPreference,
)
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.models.shelf import ShelfWork
from app.modules.library.application.volume_commands import OperationSummary
from app.modules.library.infrastructure.works import entity_as_legacy_dict

_SNAPSHOT_MODELS: dict[str, type] = {
    model.__tablename__: model
    for model in (
        LibraryWork,
        LibraryMediaVersion,
        LibraryVersion,
        LibraryVolume,
        LibraryFile,
        LibraryReadingUnit,
        LibraryMetadata,
        LibraryReadingProgress,
        ReaderBookmark,
        LibraryFacet,
        LibraryWorkFacet,
        LibraryVolumeFacet,
        ShelfWork,
        UserMediaHistory,
        WorkDetailPreference,
        ImportTask,
        ImportAsset,
        KindleSendTask,
        OrganizeJob,
        MetadataLookupTask,
        BookConversionTask,
    )
}

_RESTORE_ORDER = (
    "LibraryWork",
    "LibraryMediaVersion",
    "LibraryVersion",
    "LibraryVolume",
    "LibraryFile",
    "LibraryReadingUnit",
    "LibraryMetadata",
    "LibraryReadingProgress",
    "ReaderBookmark",
    "LibraryFacet",
    "LibraryWorkFacet",
    "LibraryVolumeFacet",
    "ShelfWork",
    "UserMediaHistory",
    "WorkDetailPreference",
    "ImportTask",
    "ImportAsset",
    "KindleSendTask",
    "OrganizeJob",
    "MetadataLookupTask",
    "BookConversionTask",
)


def has_table(db: Session, table: str) -> bool:
    return sa_inspect(db.connection()).has_table(table)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@dataclass(frozen=True, slots=True)
class PreparedOperationWrite:
    row: dict[str, Any]
    record: dict[str, Any]


def prepare_operation_write(
    *,
    user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    summary: str,
    payload: dict[str, Any],
    inverse: dict[str, Any],
    now: datetime,
    undoable: bool = True,
) -> PreparedOperationWrite:
    operation_id = f"op_{time_ns()}"
    expires_at = now + timedelta(days=7)
    status = "COMPLETED" if undoable else "FINALIZED"
    payload_json = _json(payload)
    inverse_json = _json(inverse)
    return PreparedOperationWrite(
        row={
            "id": operation_id,
            "user_id": user_id,
            "action": action,
            "status": status,
            "target_type": target_type,
            "target_id": target_id,
            "summary": summary,
            "payload_json": payload_json,
            "inverse_json": inverse_json,
            "expires_at": expires_at if undoable else None,
            "created_at": now,
            "updated_at": now,
        },
        record={
            "id": operation_id,
            "userId": user_id,
            "action": action,
            "status": status,
            "targetType": target_type,
            "targetId": target_id,
            "summary": summary,
            "payloadJson": payload_json,
            "inverseJson": inverse_json,
            "expiresAt": expires_at if undoable else None,
            "createdAt": now,
            "updatedAt": now,
        },
    )


def write_prepared_operation(db: Session, prepared: PreparedOperationWrite) -> None:
    db.execute(insert(LibraryOperation), [prepared.row])


def _column_name_to_attr(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


def row_to_attr_values(model: type, row: dict[str, Any]) -> dict[str, Any]:
    name_to_key = _column_name_to_attr(model)
    return {
        attribute: value
        for name, value in row.items()
        if (attribute := name_to_key.get(name)) is not None
    }


def create_operation(
    db: Session,
    *,
    user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    summary: str,
    payload: dict[str, Any],
    inverse: dict[str, Any],
    now: datetime,
    undoable: bool = True,
) -> dict[str, Any]:
    prepared = prepare_operation_write(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        payload=payload,
        inverse=inverse,
        now=now,
        undoable=undoable,
    )
    write_prepared_operation(db, prepared)
    return prepared.record


def operation_summary(operation: dict[str, Any]) -> OperationSummary:
    expires_at = operation.get("expiresAt")
    if not isinstance(expires_at, datetime):
        raise TypeError("Operation expiry is missing")
    return OperationSummary(
        id=str(operation["id"]),
        action=str(operation["action"]),
        status=str(operation["status"]),
        summary=str(operation["summary"]),
        expires_at=expires_at,
        undo_available=True,
    )


def get_operation(db: Session, operation_id: str) -> dict[str, Any] | None:
    operation = db.get(LibraryOperation, operation_id)
    return entity_as_legacy_dict(operation) if operation is not None else None


def list_operations_for_user(
    db: Session,
    user_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LibraryOperation)
        .where(
            or_(
                LibraryOperation.user_id == user_id,
                LibraryOperation.user_id.is_(None),
            )
        )
        .order_by(LibraryOperation.created_at.desc(), LibraryOperation.id.desc())
        .limit(limit)
    ).all()
    return [entity_as_legacy_dict(row) for row in rows]


def mark_operation_undone(db: Session, *, operation_id: str, now: datetime) -> None:
    db.execute(
        update(LibraryOperation)
        .where(LibraryOperation.id == operation_id)
        .values(status="UNDONE", undone_at=now, updated_at=now)
    )


def insert_snapshot(db: Session, table: str, row: dict[str, Any]) -> None:
    if not row:
        return
    model = _SNAPSHOT_MODELS.get(table)
    if model is None:
        raise ValueError(f"Unsupported snapshot table: {table}")
    values = row_to_attr_values(model, row)
    if not values:
        return
    mapper = sa_inspect(model)
    primary_key = list(mapper.primary_key)
    primary_key_attrs = {
        mapper.get_property_by_column(column).key for column in primary_key
    }
    statement = sqlite_insert(model).values(**values)
    update_set = {
        getattr(model, key): value
        for key, value in values.items()
        if key not in primary_key_attrs
    }
    if update_set:
        statement = statement.on_conflict_do_update(
            index_elements=primary_key,
            set_=update_set,
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=primary_key)
    db.execute(statement)


def restore_rows(db: Session, rows_by_table: dict[str, list[dict[str, Any]]]) -> None:
    for table in _RESTORE_ORDER:
        for row in rows_by_table.get(table, []):
            insert_snapshot(db, table, row)


def snapshot_volumes_for_media_versions(
    db: Session, media_version_ids: list[str]
) -> list[dict[str, Any]]:
    if not media_version_ids:
        return []
    return _rows(
        db,
        LibraryVolume,
        LibraryVolume.version_id.in_(media_version_ids),
    )


def snapshot_work_dependents(
    db: Session, work_id: str
) -> dict[str, list[dict[str, Any]]]:
    return {
        "LibraryWorkFacet": _rows(
            db,
            LibraryWorkFacet,
            LibraryWorkFacet.work_id == work_id,
        ),
        "ShelfWork": _rows(db, ShelfWork, ShelfWork.work_id == work_id),
        "WorkDetailPreference": _rows(
            db,
            WorkDetailPreference,
            WorkDetailPreference.work_id == work_id,
        ),
    }


def _rows(db: Session, model: type, condition: object) -> list[dict[str, Any]]:
    return [
        entity_as_legacy_dict(row)
        for row in db.scalars(select(model).where(condition)).all()
    ]


def capture_volume_delete_snapshot(
    db: Session, *, work_id: str, volume_id: str
) -> dict[str, list[dict[str, Any]]]:
    volume = db.get(LibraryVolume, volume_id)
    if volume is None:
        raise ValueError("Volume does not exist")
    media_version = db.get(LibraryVersion, volume.version_id)
    if media_version is None or media_version.work_id != work_id:
        raise ValueError("Volume does not belong to work")
    work = db.get(LibraryWork, work_id)
    if work is None:
        raise ValueError("Work does not exist")

    file_ids = list(
        db.scalars(select(LibraryFile.id).where(LibraryFile.volume_id == volume_id))
    )
    # A parent is snapshotted only if this deletion removes it.
    media_volume_count = len(
        db.scalars(
            select(LibraryVolume.id).where(
                LibraryVolume.version_id == media_version.id
            )
        ).all()
    )
    work_media_count = len(
        db.scalars(
            select(LibraryVersion.id).where(LibraryVersion.work_id == work_id)
        ).all()
    )
    deletes_media = media_volume_count == 1
    deletes_work = deletes_media and work_media_count == 1

    snapshot: dict[str, list[dict[str, Any]]] = {
        "LibraryVolume": [entity_as_legacy_dict(volume)],
        "LibraryFile": _rows(db, LibraryFile, LibraryFile.volume_id == volume_id),
        "LibraryReadingUnit": _rows(
            db, LibraryReadingUnit, LibraryReadingUnit.volume_id == volume_id
        ),
        "LibraryMetadata": _rows(
            db, LibraryMetadata, LibraryMetadata.volume_id == volume_id
        ),
        "LibraryReadingProgress": _rows(
            db, LibraryReadingProgress, LibraryReadingProgress.volume_id == volume_id
        ),
        "ReaderBookmark": _rows(
            db, ReaderBookmark, ReaderBookmark.volume_id == volume_id
        ),
        "LibraryVolumeFacet": _rows(
            db, LibraryVolumeFacet, LibraryVolumeFacet.volume_id == volume_id
        ),
        "ImportTask": _rows(
            db,
            ImportTask,
            (
                ImportTask.work_id == work_id
                if deletes_work
                else ImportTask.volume_id == volume_id
            ),
        ),
        "KindleSendTask": _rows(
            db,
            KindleSendTask,
            (
                KindleSendTask.work_id == work_id
                if deletes_work
                else (KindleSendTask.volume_id == volume_id)
                | KindleSendTask.file_id.in_(file_ids)
            ),
        ),
        "OrganizeJob": _rows(
            db,
            OrganizeJob,
            (
                OrganizeJob.work_id == work_id
                if deletes_work
                else OrganizeJob.volume_id == volume_id
            ),
        ),
        "MetadataLookupTask": _rows(
            db,
            MetadataLookupTask,
            (
                MetadataLookupTask.work_id == work_id
                if deletes_work
                else MetadataLookupTask.volume_id == volume_id
            ),
        ),
        "BookConversionTask": _rows(
            db,
            BookConversionTask,
            (BookConversionTask.source_volume_id == volume_id)
            | (BookConversionTask.derived_volume_id == volume_id),
        ),
        "ImportAsset": (
            _rows(db, ImportAsset, ImportAsset.file_id.in_(file_ids))
            if file_ids
            else []
        ),
        # Derived resources survive source deletion but their link is set NULL.
        "dependentVolumes": _rows(
            db,
            LibraryVolume,
            LibraryVolume.derived_from_volume_id == volume_id,
        ),
    }
    if deletes_media:
        snapshot["LibraryVersion"] = [entity_as_legacy_dict(media_version)]
        media_row = db.get(LibraryMediaVersion, media_version.id)
        if media_row is not None:
            snapshot["LibraryMediaVersion"] = [entity_as_legacy_dict(media_row)]
        snapshot["UserMediaHistory"] = _rows(
            db,
            UserMediaHistory,
            UserMediaHistory.media_version_id == media_version.id,
        )
    if deletes_work:
        snapshot["LibraryWork"] = [entity_as_legacy_dict(work)]
        snapshot["LibraryWorkFacet"] = _rows(
            db, LibraryWorkFacet, LibraryWorkFacet.work_id == work_id
        )
        snapshot["ShelfWork"] = _rows(db, ShelfWork, ShelfWork.work_id == work_id)
        snapshot["WorkDetailPreference"] = _rows(
            db, WorkDetailPreference, WorkDetailPreference.work_id == work_id
        )
    return snapshot


def restore_volume_delete_snapshot(
    db: Session, snapshot: dict[str, list[dict[str, Any]]]
) -> None:
    rows = dict(snapshot)
    dependent_volumes = rows.pop("dependentVolumes", [])
    restore_rows(db, rows)
    for row in dependent_volumes:
        insert_snapshot(db, "LibraryVolume", row)


def restore_work_row(db: Session, work_id: str, row: dict[str, Any]) -> None:
    del work_id
    insert_snapshot(db, "LibraryWork", row)


def restore_media_version_row(db: Session, row: dict[str, Any]) -> None:
    insert_snapshot(db, "LibraryMediaVersion", row)


def restore_volume_row(db: Session, row: dict[str, Any]) -> None:
    insert_snapshot(db, "LibraryVolume", row)


def restore_facet_row(db: Session, facet_id: str, row: dict[str, Any]) -> None:
    del facet_id
    insert_snapshot(db, "LibraryFacet", row)


def delete_shelf_work_link(db: Session, *, shelf_id: str, work_id: str) -> None:
    db.execute(
        delete(ShelfWork).where(
            ShelfWork.shelf_id == shelf_id,
            ShelfWork.work_id == work_id,
        )
    )


def delete_work(db: Session, work_id: str) -> None:
    db.execute(delete(LibraryWork).where(LibraryWork.id == work_id))


def delete_media_version_if_empty(db: Session, media_version_id: str) -> None:
    has_volume = db.scalar(
        select(LibraryVolume.id)
        .where(LibraryVolume.version_id == media_version_id)
        .limit(1)
    )
    if has_volume is None:
        db.execute(
            delete(LibraryVersion).where(LibraryVersion.id == media_version_id)
        )


def delete_work_if_empty(db: Session, work_id: str) -> None:
    has_media = db.scalar(
        select(LibraryVersion.id)
        .where(LibraryVersion.work_id == work_id)
        .limit(1)
    )
    if has_media is None:
        db.execute(delete(LibraryWork).where(LibraryWork.id == work_id))


def delete_work_facets_for_work(db: Session, work_id: str) -> None:
    db.execute(delete(LibraryWorkFacet).where(LibraryWorkFacet.work_id == work_id))


def delete_volume_facets_for_volume(db: Session, volume_id: str) -> None:
    db.execute(
        delete(LibraryVolumeFacet).where(LibraryVolumeFacet.volume_id == volume_id)
    )
