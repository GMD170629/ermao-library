"""Set-based planners for batch volume structure mutations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.auth import ReaderBookmark
from app.models.common import cuid
from app.models.import_pipeline import (
    BookConversionTask,
    ImportAsset,
    ImportTask,
    KindleSendTask,
)
from app.models.library import (
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
    WorkDetailPreference,
)
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.models.shelf import ShelfWork
from app.modules.library.application.volume_commands import (
    BatchVolumeCommand,
    BatchVolumeOutcome,
    VolumeContext,
)
from app.modules.library.infrastructure import operations as operation_store
from app.modules.library.infrastructure.implicit_version import (
    IMPLICIT_VERSION_SOURCE_KEY,
    get_or_create_implicit_version,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
    normalize_identity_part,
)


@dataclass(frozen=True, slots=True)
class PreparedSqlWrite:
    statement: Executable
    parameters: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedBatchVolumeMutation:
    writes: tuple[PreparedSqlWrite, ...]
    outcome: BatchVolumeOutcome


def _parameter_writes(
    statement: Executable,
    rows: tuple[Mapping[str, object], ...],
    *,
    parameters_per_row: int,
) -> tuple[PreparedSqlWrite, ...]:
    return tuple(
        PreparedSqlWrite(statement, tuple(chunk))
        for chunk in sqlite_parameter_chunks(
            rows,
            parameters_per_row=parameters_per_row,
        )
    )


def _delete_writes(
    model: type,
    column: object,
    identifiers: tuple[str, ...],
) -> tuple[PreparedSqlWrite, ...]:
    return tuple(
        PreparedSqlWrite(delete(model).where(column.in_(chunk)))
        for chunk in sqlite_parameter_chunks(identifiers, parameters_per_row=1)
    )


def _operation_writes(
    operations: tuple[operation_store.PreparedOperationWrite, ...],
) -> tuple[PreparedSqlWrite, ...]:
    rows = tuple(operation.row for operation in operations)
    return _parameter_writes(
        insert(LibraryOperation),
        rows,
        parameters_per_row=12,
    )


def _execute_prepared(db: Session, prepared: PreparedBatchVolumeMutation) -> None:
    for write in prepared.writes:
        if write.parameters:
            db.execute(write.statement, list(write.parameters))
        else:
            db.execute(write.statement)


def _volume_entities(
    db: Session, volume_ids: tuple[str, ...]
) -> tuple[tuple[LibraryVolume, LibraryVersion], ...]:
    rows = db.execute(
        select(LibraryVolume, LibraryVersion)
        .join(
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
        )
        .where(LibraryVolume.id.in_(volume_ids))
    ).all()
    by_id = {volume.id: (volume, version) for volume, version in rows}
    return tuple(by_id[volume_id] for volume_id in volume_ids if volume_id in by_id)


def _remaining_by_version(
    db: Session,
    version_ids: tuple[str, ...],
    selected_ids: set[str],
) -> dict[str, list[LibraryVolume]]:
    result: dict[str, list[LibraryVolume]] = defaultdict(list)
    for volume in db.scalars(
        select(LibraryVolume)
        .where(LibraryVolume.version_id.in_(version_ids))
        .order_by(
            LibraryVolume.version_id.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
    ).all():
        if volume.id not in selected_ids:
            result[volume.version_id].append(volume)
    return result


def _prepare_set_media_kind_batch(
    db: Session,
    *,
    actor_id: str,
    source_work_id: str,
    contexts: tuple[VolumeContext, ...],
    target_kind: str,
    now: datetime,
) -> PreparedBatchVolumeMutation:
    volume_ids = tuple(context.id for context in contexts)
    selected = _volume_entities(db, volume_ids)
    selected_by_id = {volume.id: (volume, media) for volume, media in selected}
    source_work = db.get(LibraryWork, source_work_id)
    if source_work is None:
        raise ValueError("Source work does not exist")
    volume_updates = tuple(
        {
            "id": volume.id,
            "classification_source": "USER",
            "classification_reason": "USER_OVERRIDE",
            "suggested_media_kind": target_kind,
            "updated_at": now,
        }
        for volume, _media in selected
    )
    operations = tuple(
        operation_store.prepare_operation_write(
            user_id=actor_id,
            action="RECLASSIFY_VOLUME",
            target_type="volume",
            target_id=context.id,
            summary=f"Reclassified volume as {target_kind}",
            payload={
                "sourceWorkId": source_work_id,
                "targetWorkId": source_work_id,
                "volumeId": context.id,
                "targetMediaKind": target_kind,
            },
            inverse={
                "sourceWork": None,
                "sourceWorkDependents": {},
                "sourceVersion": entity_as_legacy_dict(selected_by_id[context.id][1]),
                "volume": entity_as_legacy_dict(selected_by_id[context.id][0]),
                "volumes": [entity_as_legacy_dict(selected_by_id[context.id][0])],
                "targetWorkId": source_work_id,
                "targetVersionId": selected_by_id[context.id][1].id,
                "targetVersionCreated": False,
            },
            now=now,
        )
        for context in contexts
    )
    writes: list[PreparedSqlWrite] = [
        *_parameter_writes(update(LibraryVolume), volume_updates, parameters_per_row=5),
        PreparedSqlWrite(
            update(LibraryWork)
            .where(LibraryWork.id == source_work_id)
            .values(updated_at=now)
        ),
        *_operation_writes(operations),
    ]
    return PreparedBatchVolumeMutation(
        tuple(writes),
        BatchVolumeOutcome(
            work_id=source_work_id,
            affected_volume_ids=volume_ids,
            target_work_ids=(),
            operation_ids=tuple(operation.record["id"] for operation in operations),
            deleted_work=False,
        ),
    )


def _prepare_split_batch(
    db: Session,
    *,
    actor_id: str,
    source_work_id: str,
    contexts: tuple[VolumeContext, ...],
    now: datetime,
) -> PreparedBatchVolumeMutation:
    volume_ids = tuple(context.id for context in contexts)
    selected = _volume_entities(db, volume_ids)
    selected_by_id = {volume.id: (volume, media) for volume, media in selected}
    selected_ids = set(volume_ids)
    source_work = db.get(LibraryWork, source_work_id)
    if source_work is None:
        raise ValueError("Source work does not exist")
    source_media_ids = tuple(dict.fromkeys(media.id for _volume, media in selected))
    remaining = _remaining_by_version(db, source_media_ids, selected_ids)
    target_work_ids = {context.id: cuid() for context in contexts}
    target_media_ids = {context.id: cuid() for context in contexts}
    work_rows = tuple(
        {
            "id": target_work_ids[context.id],
            "library_id": source_work.library_id,
            "origin": source_work.origin,
            "title": f"{context.work_title}（{context.title}）",
            "normalized_title": normalize_identity_part(
                f"{context.work_title}（{context.title}）"
            ),
            "author": context.author or UNKNOWN_AUTHOR,
            "normalized_author": normalize_identity_part(
                context.author or UNKNOWN_AUTHOR
            ),
            "description": source_work.description,
            "tags": source_work.tags,
            "cover_status": "PENDING",
            "merge_key": identity_merge_key(
                f"{context.work_title}（{context.title}）",
                context.author or UNKNOWN_AUTHOR,
            ),
            "created_at": now,
            "updated_at": now,
        }
        for context in contexts
    )
    version_rows = tuple(
        {
            "id": target_media_ids[context.id],
            "work_id": target_work_ids[context.id],
            "source_key": IMPLICIT_VERSION_SOURCE_KEY,
            "created_at": now,
            "updated_at": now,
        }
        for context in contexts
    )
    volume_updates = tuple(
        {
            "id": context.id,
            "version_id": target_media_ids[context.id],
            "sort_order": 1000,
            "updated_at": now,
        }
        for context in contexts
    )
    remaining_updates = tuple(
        {"id": volume.id, "sort_order": index * 1000, "updated_at": now}
        for media_id in source_media_ids
        for index, volume in enumerate(remaining.get(media_id, []))
    )
    empty_media_ids = tuple(
        media_id for media_id in source_media_ids if not remaining.get(media_id)
    )
    all_source_media_ids = tuple(
        db.scalars(
            select(LibraryVersion.id).where(LibraryVersion.work_id == source_work_id)
        ).all()
    )
    deletes_source_work = set(all_source_media_ids).issubset(empty_media_ids)
    source_dependents = (
        operation_store.snapshot_work_dependents(db, source_work_id)
        if deletes_source_work
        else {}
    )
    operations = tuple(
        operation_store.prepare_operation_write(
            user_id=actor_id,
            action="SPLIT_VOLUME",
            target_type="volume",
            target_id=context.id,
            summary=f"Split volume into {work_rows[index]['title']}",
            payload={
                "sourceWorkId": source_work_id,
                "newWorkId": target_work_ids[context.id],
                "volumeId": context.id,
            },
            inverse={
                "sourceWork": (
                    entity_as_legacy_dict(source_work) if deletes_source_work else None
                ),
                "sourceWorkDependents": source_dependents,
                "sourceVersion": entity_as_legacy_dict(selected_by_id[context.id][1]),
                "volume": entity_as_legacy_dict(selected_by_id[context.id][0]),
                "targetWorkId": target_work_ids[context.id],
                "targetVersionId": target_media_ids[context.id],
                "targetVersionCreated": True,
                "newWorkId": target_work_ids[context.id],
            },
            now=now,
        )
        for index, context in enumerate(contexts)
    )
    writes: list[PreparedSqlWrite] = []
    writes.extend(
        _parameter_writes(insert(LibraryWork), work_rows, parameters_per_row=19)
    )
    writes.extend(
        _parameter_writes(insert(LibraryVersion), version_rows, parameters_per_row=5)
    )
    writes.extend(
        _parameter_writes(update(LibraryVolume), volume_updates, parameters_per_row=4)
    )
    writes.extend(
        _parameter_writes(
            update(LibraryVolume), remaining_updates, parameters_per_row=3
        )
    )
    writes.extend(_delete_writes(LibraryVersion, LibraryVersion.id, empty_media_ids))
    if deletes_source_work:
        writes.append(
            PreparedSqlWrite(
                delete(LibraryWork).where(LibraryWork.id == source_work_id)
            )
        )
    writes.extend(_operation_writes(operations))
    return PreparedBatchVolumeMutation(
        tuple(writes),
        BatchVolumeOutcome(
            work_id=source_work_id,
            affected_volume_ids=volume_ids,
            target_work_ids=tuple(target_work_ids[context.id] for context in contexts),
            operation_ids=tuple(operation.record["id"] for operation in operations),
            deleted_work=deletes_source_work,
        ),
    )


def _legacy_rows(rows: tuple[object, ...] | list[object]) -> list[dict[str, object]]:
    return [entity_as_legacy_dict(row) for row in rows]


def _batch_delete_snapshots(
    db: Session,
    *,
    source_work_id: str,
    selected_by_id: Mapping[
        str,
        tuple[LibraryVolume, LibraryVersion],
    ],
    empty_media_ids: set[str],
    deletes_source_work: bool,
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Project all delete undo data with a fixed number of set queries."""
    volume_ids = tuple(selected_by_id)
    snapshots: dict[str, dict[str, list[dict[str, object]]]] = {
        volume_id: {
            "LibraryVolume": [entity_as_legacy_dict(selected_by_id[volume_id][0])]
        }
        for volume_id in volume_ids
    }

    def add_volume_rows(table: str, rows: list[object]) -> None:
        for row in rows:
            volume_id = str(row.volume_id)
            if volume_id in snapshots:
                snapshots[volume_id].setdefault(table, []).append(
                    entity_as_legacy_dict(row)
                )

    files = list(
        db.scalars(
            select(LibraryFile).where(LibraryFile.volume_id.in_(volume_ids))
        ).all()
    )
    add_volume_rows("LibraryFile", files)
    file_to_volume = {file.id: file.volume_id for file in files}
    file_ids = tuple(file_to_volume)
    for table, model in (
        ("LibraryReadingUnit", LibraryReadingUnit),
        ("LibraryMetadata", LibraryMetadata),
        ("LibraryReadingProgress", LibraryReadingProgress),
        ("ReaderBookmark", ReaderBookmark),
        ("LibraryVolumeFacet", LibraryVolumeFacet),
    ):
        add_volume_rows(
            table,
            list(
                db.scalars(select(model).where(model.volume_id.in_(volume_ids))).all()
            ),
        )

    import_tasks = list(
        db.scalars(
            select(ImportTask).where(
                ImportTask.work_id == source_work_id
                if deletes_source_work
                else ImportTask.volume_id.in_(volume_ids)
            )
        ).all()
    )
    if deletes_source_work:
        rows = _legacy_rows(import_tasks)
        for snapshot in snapshots.values():
            snapshot["ImportTask"] = rows
    else:
        add_volume_rows("ImportTask", import_tasks)

    kindle_condition = (
        KindleSendTask.work_id == source_work_id
        if deletes_source_work
        else or_(
            KindleSendTask.volume_id.in_(volume_ids),
            KindleSendTask.file_id.in_(file_ids),
        )
    )
    kindle_tasks = list(
        db.scalars(select(KindleSendTask).where(kindle_condition)).all()
    )
    if deletes_source_work:
        rows = _legacy_rows(kindle_tasks)
        for snapshot in snapshots.values():
            snapshot["KindleSendTask"] = rows
    else:
        for task in kindle_tasks:
            volume_id = task.volume_id or file_to_volume.get(task.file_id or "")
            if volume_id in snapshots:
                snapshots[volume_id].setdefault("KindleSendTask", []).append(
                    entity_as_legacy_dict(task)
                )

    for table, model in (
        ("OrganizeJob", OrganizeJob),
        ("MetadataLookupTask", MetadataLookupTask),
    ):
        rows = list(
            db.scalars(
                select(model).where(
                    model.work_id == source_work_id
                    if deletes_source_work
                    else model.volume_id.in_(volume_ids)
                )
            ).all()
        )
        if deletes_source_work:
            legacy_rows = _legacy_rows(rows)
            for snapshot in snapshots.values():
                snapshot[table] = legacy_rows
        else:
            add_volume_rows(table, rows)

    conversions = list(
        db.scalars(
            select(BookConversionTask).where(
                or_(
                    BookConversionTask.source_volume_id.in_(volume_ids),
                    BookConversionTask.derived_volume_id.in_(volume_ids),
                )
            )
        ).all()
    )
    for conversion in conversions:
        row = entity_as_legacy_dict(conversion)
        for volume_id in {
            conversion.source_volume_id,
            conversion.derived_volume_id,
        }:
            if volume_id in snapshots:
                snapshots[volume_id].setdefault("BookConversionTask", []).append(row)

    if file_ids:
        assets = list(
            db.scalars(
                select(ImportAsset).where(ImportAsset.file_id.in_(file_ids))
            ).all()
        )
        for asset in assets:
            volume_id = file_to_volume.get(asset.file_id or "")
            if volume_id in snapshots:
                snapshots[volume_id].setdefault("ImportAsset", []).append(
                    entity_as_legacy_dict(asset)
                )

    dependent_volumes = list(
        db.scalars(
            select(LibraryVolume).where(
                LibraryVolume.derived_from_volume_id.in_(volume_ids)
            )
        ).all()
    )
    for dependent in dependent_volumes:
        source_id = dependent.derived_from_volume_id
        if source_id in snapshots:
            snapshots[source_id].setdefault("dependentVolumes", []).append(
                entity_as_legacy_dict(dependent)
            )

    media_rows = (
        list(
            db.scalars(
                select(LibraryMediaVersion).where(
                    LibraryMediaVersion.work_id == source_work_id
                )
            ).all()
        )
        if deletes_source_work
        else []
    )
    for volume_id, (_volume, media) in selected_by_id.items():
        if media.id in empty_media_ids:
            snapshots[volume_id]["LibraryVersion"] = [entity_as_legacy_dict(media)]

    if deletes_source_work:
        work = db.get(LibraryWork, source_work_id)
        if work is None:
            raise ValueError("Work does not exist")
        dependents = operation_store.snapshot_work_dependents(db, source_work_id)
        work_row = entity_as_legacy_dict(work)
        media_legacy = [entity_as_legacy_dict(row) for row in media_rows]
        for snapshot in snapshots.values():
            snapshot["LibraryWork"] = [work_row]
            snapshot["LibraryMediaVersion"] = media_legacy
            snapshot.update(dependents)
    return snapshots


def _prepare_delete_batch(
    db: Session,
    *,
    actor_id: str,
    source_work_id: str,
    contexts: tuple[VolumeContext, ...],
    now: datetime,
) -> PreparedBatchVolumeMutation:
    volume_ids = tuple(context.id for context in contexts)
    selected_ids = set(volume_ids)
    selected = _volume_entities(db, volume_ids)
    selected_by_id = {volume.id: (volume, media) for volume, media in selected}
    source_media_ids = tuple(dict.fromkeys(media.id for _volume, media in selected))
    remaining = _remaining_by_version(db, source_media_ids, selected_ids)
    empty_media_ids = tuple(
        media_id for media_id in source_media_ids if not remaining.get(media_id)
    )
    all_source_media_ids = tuple(
        db.scalars(
            select(LibraryVersion.id).where(LibraryVersion.work_id == source_work_id)
        ).all()
    )
    deletes_source_work = set(all_source_media_ids).issubset(empty_media_ids)
    snapshots = _batch_delete_snapshots(
        db,
        source_work_id=source_work_id,
        selected_by_id=selected_by_id,
        empty_media_ids=set(empty_media_ids),
        deletes_source_work=deletes_source_work,
    )
    operations = tuple(
        operation_store.prepare_operation_write(
            user_id=actor_id,
            action="DELETE_VOLUME",
            target_type="volume",
            target_id=context.id,
            summary=f"Deleted volume {context.title}",
            payload={"workId": source_work_id, "volumeId": context.id},
            inverse={"snapshot": snapshots[context.id]},
            now=now,
        )
        for context in contexts
    )
    writes: list[PreparedSqlWrite] = []
    for chunk in sqlite_parameter_chunks(volume_ids, parameters_per_row=1):
        file_ids = select(LibraryFile.id).where(LibraryFile.volume_id.in_(chunk))
        writes.extend(
            (
                PreparedSqlWrite(
                    update(ImportAsset)
                    .where(ImportAsset.file_id.in_(file_ids))
                    .values(file_id=None)
                ),
                PreparedSqlWrite(
                    update(KindleSendTask)
                    .where(KindleSendTask.file_id.in_(file_ids))
                    .values(file_id=None)
                ),
                PreparedSqlWrite(
                    update(ImportTask)
                    .where(ImportTask.volume_id.in_(chunk))
                    .values(volume_id=None)
                ),
                PreparedSqlWrite(
                    update(KindleSendTask)
                    .where(KindleSendTask.volume_id.in_(chunk))
                    .values(volume_id=None, file_id=None)
                ),
                PreparedSqlWrite(
                    update(MetadataLookupTask)
                    .where(MetadataLookupTask.volume_id.in_(chunk))
                    .values(volume_id=None)
                ),
                PreparedSqlWrite(
                    update(OrganizeJob)
                    .where(OrganizeJob.volume_id.in_(chunk))
                    .values(volume_id=None)
                ),
                PreparedSqlWrite(
                    update(LibraryVolume)
                    .where(LibraryVolume.derived_from_volume_id.in_(chunk))
                    .values(derived_from_volume_id=None)
                ),
                PreparedSqlWrite(
                    delete(BookConversionTask).where(
                        BookConversionTask.source_volume_id.in_(chunk)
                    )
                ),
                PreparedSqlWrite(
                    update(BookConversionTask)
                    .where(BookConversionTask.derived_volume_id.in_(chunk))
                    .values(derived_volume_id=None)
                ),
                PreparedSqlWrite(
                    delete(ReaderBookmark).where(ReaderBookmark.volume_id.in_(chunk))
                ),
                PreparedSqlWrite(
                    delete(LibraryReadingProgress).where(
                        LibraryReadingProgress.volume_id.in_(chunk)
                    )
                ),
                PreparedSqlWrite(
                    delete(LibraryReadingUnit).where(
                        LibraryReadingUnit.volume_id.in_(chunk)
                    )
                ),
                PreparedSqlWrite(
                    delete(LibraryMetadata).where(LibraryMetadata.volume_id.in_(chunk))
                ),
                PreparedSqlWrite(
                    delete(LibraryVolumeFacet).where(
                        LibraryVolumeFacet.volume_id.in_(chunk)
                    )
                ),
                PreparedSqlWrite(
                    delete(LibraryFile).where(LibraryFile.volume_id.in_(chunk))
                ),
                PreparedSqlWrite(
                    delete(LibraryVolume).where(LibraryVolume.id.in_(chunk))
                ),
            )
        )
    writes.extend(_delete_writes(LibraryVersion, LibraryVersion.id, empty_media_ids))
    if deletes_source_work:
        writes.extend(
            (
                PreparedSqlWrite(
                    update(ImportTask)
                    .where(ImportTask.work_id == source_work_id)
                    .values(work_id=None, volume_id=None)
                ),
                PreparedSqlWrite(
                    update(KindleSendTask)
                    .where(KindleSendTask.work_id == source_work_id)
                    .values(work_id=None, volume_id=None, file_id=None)
                ),
                PreparedSqlWrite(
                    delete(OrganizeJob).where(OrganizeJob.work_id == source_work_id)
                ),
                PreparedSqlWrite(
                    delete(MetadataLookupTask).where(
                        MetadataLookupTask.work_id == source_work_id
                    )
                ),
                PreparedSqlWrite(
                    delete(LibraryWorkFacet).where(
                        LibraryWorkFacet.work_id == source_work_id
                    )
                ),
                PreparedSqlWrite(
                    delete(ShelfWork).where(ShelfWork.work_id == source_work_id)
                ),
                PreparedSqlWrite(
                    delete(WorkDetailPreference).where(
                        WorkDetailPreference.work_id == source_work_id
                    )
                ),
                PreparedSqlWrite(
                    delete(LibraryWork).where(LibraryWork.id == source_work_id)
                ),
            )
        )
    writes.extend(_operation_writes(operations))
    return PreparedBatchVolumeMutation(
        tuple(writes),
        BatchVolumeOutcome(
            work_id=source_work_id,
            affected_volume_ids=volume_ids,
            target_work_ids=(),
            operation_ids=tuple(operation.record["id"] for operation in operations),
            deleted_work=deletes_source_work,
        ),
    )


def prepare_batch_volume_mutation(
    db: Session,
    *,
    actor_id: str,
    source_work_id: str,
    contexts: tuple[VolumeContext, ...],
    command: BatchVolumeCommand,
    now: datetime,
) -> PreparedBatchVolumeMutation:
    if command.action == "SET_MEDIA_KIND":
        return _prepare_set_media_kind_batch(
            db,
            actor_id=actor_id,
            source_work_id=source_work_id,
            contexts=contexts,
            target_kind=str(command.target_media_kind),
            now=now,
        )
    if command.action == "SPLIT":
        return _prepare_split_batch(
            db,
            actor_id=actor_id,
            source_work_id=source_work_id,
            contexts=contexts,
            now=now,
        )
    if command.action == "DELETE":
        return _prepare_delete_batch(
            db,
            actor_id=actor_id,
            source_work_id=source_work_id,
            contexts=contexts,
            now=now,
        )
    raise ValueError("INVALID_BATCH_OPERATION")


def execute_batch_volume_mutation(
    db: Session,
    prepared: PreparedBatchVolumeMutation,
) -> BatchVolumeOutcome:
    _execute_prepared(db, prepared)
    return prepared.outcome


__all__ = [
    "PreparedBatchVolumeMutation",
    "execute_batch_volume_mutation",
    "prepare_batch_volume_mutation",
]
