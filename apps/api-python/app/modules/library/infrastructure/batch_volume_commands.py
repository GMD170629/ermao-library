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
    LibraryVersion,
    LibraryMetadata,
    LibraryOperation,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryVolumeFacet,
    LibraryWork,
    LibraryWorkFacet,
    UserMediaHistory,
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
    by_id = {volume.id: (volume, media) for volume, media in rows}
    return tuple(by_id[volume_id] for volume_id in volume_ids if volume_id in by_id)


def _remaining_by_media(
    db: Session,
    media_ids: tuple[str, ...],
    selected_ids: set[str],
) -> dict[str, list[LibraryVolume]]:
    result: dict[str, list[LibraryVolume]] = defaultdict(list)
    for volume in db.scalars(
        select(LibraryVolume)
        .where(LibraryVolume.version_id.in_(media_ids))
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


def _history_rows(
    db: Session, media_ids: tuple[str, ...]
) -> tuple[UserMediaHistory, ...]:
    if not media_ids:
        return ()
    return tuple(
        db.scalars(
            select(UserMediaHistory).where(
                UserMediaHistory.media_version_id.in_(media_ids)
            )
        ).all()
    )


def _prepare_history_reparent(
    *,
    histories: tuple[UserMediaHistory, ...],
    source_to_target: Mapping[str, str],
    remaining_by_media: Mapping[str, list[LibraryVolume]],
    preferred_volume_by_target: Mapping[str, str],
    moved_ids: set[str],
    now: datetime,
) -> tuple[
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[str, ...],
]:
    histories_by_media: dict[str, list[UserMediaHistory]] = defaultdict(list)
    target_by_key: dict[tuple[str, str], UserMediaHistory | Mapping[str, object]] = {}
    for history in histories:
        histories_by_media[history.media_version_id].append(history)
        target_by_key[(history.media_version_id, history.user_id)] = history
    updates: dict[str, dict[str, object]] = {}
    inserts: list[Mapping[str, object]] = []
    deletes: set[str] = set()
    for source_id, target_id in source_to_target.items():
        if source_id == target_id:
            continue
        remaining = remaining_by_media.get(source_id, [])
        preferred_volume_id = preferred_volume_by_target[target_id]
        for source_history in histories_by_media.get(source_id, []):
            key = (target_id, source_history.user_id)
            target_history = target_by_key.get(key)
            if target_history is None:
                if not remaining:
                    row = {
                        "id": source_history.id,
                        "media_version_id": target_id,
                        "last_volume_id": preferred_volume_id,
                        "updated_at": now,
                    }
                    updates[source_history.id] = row
                    target_by_key[key] = row
                else:
                    row = {
                        "id": cuid(),
                        "user_id": source_history.user_id,
                        "media_version_id": target_id,
                        "last_volume_id": preferred_volume_id,
                        "created_at": now,
                        "updated_at": source_history.updated_at,
                    }
                    inserts.append(row)
                    target_by_key[key] = row
            else:
                target_updated_at = (
                    target_history.updated_at
                    if isinstance(target_history, UserMediaHistory)
                    else target_history.get("updated_at", now)
                )
                if source_history.updated_at > target_updated_at:
                    target_id_value = (
                        target_history.id
                        if isinstance(target_history, UserMediaHistory)
                        else str(target_history["id"])
                    )
                    updates[target_id_value] = {
                        "id": target_id_value,
                        "last_volume_id": preferred_volume_id,
                        "updated_at": source_history.updated_at,
                    }
                if not remaining:
                    deletes.add(source_history.id)
            if remaining and source_history.last_volume_id in moved_ids:
                updates[source_history.id] = {
                    "id": source_history.id,
                    "last_volume_id": remaining[0].id,
                    "updated_at": now,
                }
    deletes.difference_update(updates)
    return tuple(updates.values()), tuple(inserts), tuple(sorted(deletes))


def _require_same_library(
    db: Session, *, source_work_id: str, target_work_id: str
) -> None:
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


def _prepare_reparent_batch(
    db: Session,
    *,
    actor_id: str,
    source_work_id: str,
    target_work_id: str,
    contexts: tuple[VolumeContext, ...],
    target_kind: str | None,
    now: datetime,
) -> PreparedBatchVolumeMutation:
    volume_ids = tuple(context.id for context in contexts)
    selected = _volume_entities(db, volume_ids)
    selected_by_id = {volume.id: (volume, media) for volume, media in selected}
    selected_ids = set(volume_ids)
    source_media = {media.id: media for _volume, media in selected}
    source_media_ids = tuple(source_media)
    source_work = db.get(LibraryWork, source_work_id)
    if source_work is None:
        raise ValueError("Source work does not exist")
    if source_work_id != target_work_id:
        _require_same_library(
            db, source_work_id=source_work_id, target_work_id=target_work_id
        )
    target_kinds = tuple(
        dict.fromkeys(target_kind or media.source_key for _volume, media in selected)
    )
    target_media_by_kind = {
        media.source_key: media
        for media in db.scalars(
            select(LibraryVersion).where(
                LibraryVersion.work_id == target_work_id,
                LibraryVersion.source_key.in_(target_kinds),
            )
        ).all()
    }
    target_media_ids = {
        kind: (
            target_media_by_kind[kind].id if kind in target_media_by_kind else cuid()
        )
        for kind in target_kinds
    }
    target_version_rows = tuple(
        {
            "id": target_media_ids[kind],
            "work_id": target_work_id,
            "source_key": kind,
            "created_at": now,
            "updated_at": now,
        }
        for kind in target_kinds
        if kind not in target_media_by_kind
    )
    target_media_rows = tuple(
        {
            "id": target_media_ids[kind],
            "work_id": target_work_id,
            "media_kind": kind,
            "created_at": now,
            "updated_at": now,
        }
        for kind in target_kinds
        if kind not in target_media_by_kind
    )
    existing_target_volumes: dict[str, list[LibraryVolume]] = defaultdict(list)
    known_target_ids = tuple(target_media_ids.values())
    for volume in db.scalars(
        select(LibraryVolume)
        .where(LibraryVolume.version_id.in_(known_target_ids))
        .order_by(
            LibraryVolume.version_id.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.id.asc(),
        )
    ).all():
        if volume.id not in selected_ids:
            existing_target_volumes[volume.version_id].append(volume)
    remaining = _remaining_by_media(db, source_media_ids, selected_ids)
    source_to_target = {
        source_id: target_media_ids[target_kind or source_media[source_id].source_key]
        for source_id in source_media_ids
    }
    incoming_by_target: dict[str, list[LibraryVolume]] = defaultdict(list)
    for context in contexts:
        volume, media = selected_by_id[context.id]
        target_id = target_media_ids[target_kind or media.source_key]
        if volume.version_id != target_id:
            incoming_by_target[target_id].append(volume)
    volume_updates: list[Mapping[str, object]] = []
    preferred_by_target: dict[str, str] = {}
    for target_id, incoming in incoming_by_target.items():
        start = len(existing_target_volumes.get(target_id, []))
        for offset, volume in enumerate(incoming, start=1):
            volume_updates.append(
                {
                    "id": volume.id,
                    "version_id": target_id,
                    "sort_order": (start + offset) * 1000,
                    "classification_source": "USER",
                    "classification_reason": "USER_OVERRIDE",
                    "suggested_media_kind": None,
                    "updated_at": now,
                }
            )
        preferred_by_target[target_id] = incoming[-1].id
    for context in contexts:
        volume, media = selected_by_id[context.id]
        target_id = target_media_ids[target_kind or media.source_key]
        preferred_by_target.setdefault(target_id, volume.id)
        if volume.version_id == target_id:
            volume_updates.append(
                {
                    "id": volume.id,
                    "classification_source": "USER",
                    "classification_reason": "USER_OVERRIDE",
                    "suggested_media_kind": None,
                    "updated_at": now,
                }
            )
    remaining_updates = tuple(
        {"id": volume.id, "sort_order": index * 1000, "updated_at": now}
        for media_id in source_media_ids
        for index, volume in enumerate(remaining.get(media_id, []))
    )
    all_history_media_ids = tuple(
        dict.fromkeys((*source_media_ids, *target_media_ids.values()))
    )
    histories = _history_rows(db, all_history_media_ids)
    history_updates, history_inserts, history_deletes = _prepare_history_reparent(
        histories=histories,
        source_to_target=source_to_target,
        remaining_by_media=remaining,
        preferred_volume_by_target=preferred_by_target,
        moved_ids=selected_ids,
        now=now,
    )
    empty_source_media_ids = tuple(
        media_id
        for media_id in source_media_ids
        if media_id != source_to_target[media_id] and not remaining.get(media_id)
    )
    all_source_media_ids = tuple(
        db.scalars(
            select(LibraryVersion.id).where(
                LibraryVersion.work_id == source_work_id
            )
        ).all()
    )
    deletes_source_work = source_work_id != target_work_id and set(
        all_source_media_ids
    ).issubset(empty_source_media_ids)
    source_dependents = (
        operation_store.snapshot_work_dependents(db, source_work_id)
        if deletes_source_work
        else {}
    )
    operations = tuple(
        operation_store.prepare_operation_write(
            user_id=actor_id,
            action="RECLASSIFY_VOLUME" if target_kind else "MOVE_VOLUME",
            target_type="volume",
            target_id=context.id,
            summary=(
                f"Reclassified volume as {target_kind}"
                if target_kind
                else f"Moved volume {context.title}"
            ),
            payload={
                "sourceWorkId": source_work_id,
                "targetWorkId": target_work_id,
                "volumeId": context.id,
                "targetMediaKind": target_kind,
            },
            inverse={
                "sourceWork": (
                    entity_as_legacy_dict(source_work) if deletes_source_work else None
                ),
                "sourceWorkDependents": source_dependents,
                "sourceMediaVersion": entity_as_legacy_dict(
                    selected_by_id[context.id][1]
                ),
                "volume": entity_as_legacy_dict(selected_by_id[context.id][0]),
                "targetWorkId": target_work_id,
                "targetMediaVersionId": target_media_ids[
                    target_kind or selected_by_id[context.id][1].source_key
                ],
                "targetMediaVersionCreated": (
                    target_kind or selected_by_id[context.id][1].source_key
                )
                not in target_media_by_kind,
                "mediaHistories": [
                    entity_as_legacy_dict(history)
                    for history in histories
                    if history.media_version_id
                    in {
                        selected_by_id[context.id][1].id,
                        target_media_ids[
                            target_kind or selected_by_id[context.id][1].source_key
                        ],
                    }
                ],
            },
            now=now,
        )
        for context in contexts
    )
    writes: list[PreparedSqlWrite] = []
    writes.extend(
        _parameter_writes(
            insert(LibraryVersion), target_version_rows, parameters_per_row=5
        )
    )
    writes.extend(
        _parameter_writes(
            insert(LibraryMediaVersion), target_media_rows, parameters_per_row=5
        )
    )
    writes.extend(
        _parameter_writes(
            update(LibraryVolume), tuple(volume_updates), parameters_per_row=7
        )
    )
    writes.extend(
        _parameter_writes(
            update(LibraryVolume), remaining_updates, parameters_per_row=3
        )
    )
    writes.extend(
        _parameter_writes(
            update(UserMediaHistory), history_updates, parameters_per_row=4
        )
    )
    writes.extend(
        _parameter_writes(
            insert(UserMediaHistory), history_inserts, parameters_per_row=6
        )
    )
    writes.extend(
        _delete_writes(UserMediaHistory, UserMediaHistory.id, history_deletes)
    )
    writes.extend(
        _delete_writes(
            LibraryMediaVersion,
            LibraryMediaVersion.id,
            empty_source_media_ids,
        )
    )
    writes.extend(
        _delete_writes(
            LibraryVersion,
            LibraryVersion.id,
            empty_source_media_ids,
        )
    )
    writes.append(
        PreparedSqlWrite(
            update(LibraryWork)
            .where(LibraryWork.id == target_work_id)
            .values(updated_at=now)
        )
    )
    if deletes_source_work:
        writes.append(
            PreparedSqlWrite(
                delete(LibraryWork).where(LibraryWork.id == source_work_id)
            )
        )
    writes.extend(_operation_writes(operations))
    outcome = BatchVolumeOutcome(
        work_id=source_work_id,
        affected_volume_ids=volume_ids,
        target_work_ids=(target_work_id,) if source_work_id != target_work_id else (),
        operation_ids=tuple(operation.record["id"] for operation in operations),
        deleted_work=deletes_source_work,
    )
    return PreparedBatchVolumeMutation(tuple(writes), outcome)


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
    remaining = _remaining_by_media(db, source_media_ids, selected_ids)
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
            "source_key": selected_by_id[context.id][1].source_key,
            "created_at": now,
            "updated_at": now,
        }
        for context in contexts
    )
    media_rows = tuple(
        {
            "id": target_media_ids[context.id],
            "work_id": target_work_ids[context.id],
            "media_kind": selected_by_id[context.id][1].source_key,
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
    histories = _history_rows(db, source_media_ids)
    target_contexts_by_source: dict[str, list[VolumeContext]] = defaultdict(list)
    for context in contexts:
        target_contexts_by_source[selected_by_id[context.id][1].id].append(context)
    history_updates: list[Mapping[str, object]] = []
    history_inserts: list[Mapping[str, object]] = []
    for source_history in histories:
        targets = target_contexts_by_source.get(source_history.media_version_id, [])
        if not targets:
            continue
        source_remaining = remaining.get(source_history.media_version_id, [])
        move_target = targets[-1] if not source_remaining else None
        for context in targets:
            if move_target is not None and context.id == move_target.id:
                history_updates.append(
                    {
                        "id": source_history.id,
                        "media_version_id": target_media_ids[context.id],
                        "last_volume_id": context.id,
                        "updated_at": now,
                    }
                )
            else:
                history_inserts.append(
                    {
                        "id": cuid(),
                        "user_id": source_history.user_id,
                        "media_version_id": target_media_ids[context.id],
                        "last_volume_id": context.id,
                        "created_at": now,
                        "updated_at": source_history.updated_at,
                    }
                )
        if source_remaining and source_history.last_volume_id in selected_ids:
            history_updates.append(
                {
                    "id": source_history.id,
                    "last_volume_id": source_remaining[0].id,
                    "updated_at": now,
                }
            )
    empty_media_ids = tuple(
        media_id for media_id in source_media_ids if not remaining.get(media_id)
    )
    all_source_media_ids = tuple(
        db.scalars(
            select(LibraryVersion.id).where(
                LibraryVersion.work_id == source_work_id
            )
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
                "sourceMediaVersion": entity_as_legacy_dict(
                    selected_by_id[context.id][1]
                ),
                "volume": entity_as_legacy_dict(selected_by_id[context.id][0]),
                "targetWorkId": target_work_ids[context.id],
                "targetMediaVersionId": target_media_ids[context.id],
                "targetMediaVersionCreated": True,
                "newWorkId": target_work_ids[context.id],
                "mediaHistories": [
                    entity_as_legacy_dict(history)
                    for history in histories
                    if history.media_version_id == selected_by_id[context.id][1].id
                ],
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
        _parameter_writes(insert(LibraryMediaVersion), media_rows, parameters_per_row=5)
    )
    writes.extend(
        _parameter_writes(update(LibraryVolume), volume_updates, parameters_per_row=4)
    )
    writes.extend(
        _parameter_writes(
            update(LibraryVolume), remaining_updates, parameters_per_row=3
        )
    )
    writes.extend(
        _parameter_writes(
            update(UserMediaHistory), tuple(history_updates), parameters_per_row=4
        )
    )
    writes.extend(
        _parameter_writes(
            insert(UserMediaHistory), tuple(history_inserts), parameters_per_row=6
        )
    )
    writes.extend(
        _delete_writes(LibraryMediaVersion, LibraryMediaVersion.id, empty_media_ids)
    )
    writes.extend(
        _delete_writes(LibraryVersion, LibraryVersion.id, empty_media_ids)
    )
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
    media_ids = tuple(
        dict.fromkeys(media.id for _volume, media in selected_by_id.values())
    )
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

    histories = list(
        db.scalars(
            select(UserMediaHistory).where(
                UserMediaHistory.media_version_id.in_(media_ids)
            )
        ).all()
    )
    histories_by_media: dict[str, list[dict[str, object]]] = defaultdict(list)
    for history in histories:
        histories_by_media[history.media_version_id].append(
            entity_as_legacy_dict(history)
        )
    for volume_id, (_volume, media) in selected_by_id.items():
        if media.id in empty_media_ids:
            snapshots[volume_id]["LibraryVersion"] = [entity_as_legacy_dict(media)]
            media_row = db.get(LibraryMediaVersion, media.id)
            if media_row is not None:
                snapshots[volume_id]["LibraryMediaVersion"] = [
                    entity_as_legacy_dict(media_row)
                ]
            snapshots[volume_id]["UserMediaHistory"] = histories_by_media.get(
                media.id,
                [],
            )

    if deletes_source_work:
        work = db.get(LibraryWork, source_work_id)
        if work is None:
            raise ValueError("Work does not exist")
        dependents = operation_store.snapshot_work_dependents(db, source_work_id)
        work_row = entity_as_legacy_dict(work)
        for snapshot in snapshots.values():
            snapshot["LibraryWork"] = [work_row]
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
    remaining = _remaining_by_media(db, source_media_ids, selected_ids)
    empty_media_ids = tuple(
        media_id for media_id in source_media_ids if not remaining.get(media_id)
    )
    all_source_media_ids = tuple(
        db.scalars(
            select(LibraryVersion.id).where(
                LibraryVersion.work_id == source_work_id
            )
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
    writes.extend(
        _delete_writes(
            UserMediaHistory,
            UserMediaHistory.media_version_id,
            empty_media_ids,
        )
    )
    writes.extend(
        _delete_writes(LibraryMediaVersion, LibraryMediaVersion.id, empty_media_ids)
    )
    writes.extend(
        _delete_writes(LibraryVersion, LibraryVersion.id, empty_media_ids)
    )
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
        return _prepare_reparent_batch(
            db,
            actor_id=actor_id,
            source_work_id=source_work_id,
            target_work_id=source_work_id,
            contexts=contexts,
            target_kind=str(command.target_media_kind),
            now=now,
        )
    if command.action == "TRANSFER":
        _require_same_library(
            db,
            source_work_id=source_work_id,
            target_work_id=str(command.target_work_id),
        )
        return _prepare_reparent_batch(
            db,
            actor_id=actor_id,
            source_work_id=source_work_id,
            target_work_id=str(command.target_work_id),
            contexts=contexts,
            target_kind=None,
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
    return _prepare_delete_batch(
        db,
        actor_id=actor_id,
        source_work_id=source_work_id,
        contexts=contexts,
        now=now,
    )


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
