"""SQLAlchemy adapter for merging several works into one new work."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite
from time import time_ns
from typing import TypeVar

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.common import cuid
from app.models.import_pipeline import BookConversionTask, ImportTask, KindleSendTask
from app.models.library import (
    LibraryMediaVersion,
    LibraryOperation,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
    WorkDetailPreference,
)
from app.models.organize import (
    MetadataLookupTask,
    MetadataWritebackOperation,
    OrganizeJob,
)
from app.models.settings import ReaderBookPreference, ReaderProgressCursor
from app.models.shelf import ShelfWork
from app.modules.library.application.facet_sync import (
    WorkFacetProjection,
    prepare_work_facet,
)
from app.modules.library.application.work_merge import (
    MEDIA_KIND_ORDER,
    MergeCommand,
    MergeMetadata,
    MergeMetadataWritebackPort,
    MergePreview,
    MergeResult,
    WorkMergeError,
    WorkMergeInProgressError,
    WorkMergeNotFoundError,
)
from app.modules.library.infrastructure.facet_sync import (
    execute_work_facet_write,
    prepare_work_facet_write,
)
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
    normalize_identity_part,
)

PreferenceT = TypeVar("PreferenceT", WorkDetailPreference, ReaderBookPreference)


def _now() -> datetime:
    return datetime.now(UTC)


def _tags(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return (
        [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, list)
        else []
    )


def _unique_tags(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.casefold()
        if normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return tuple(result)


class SqlAlchemyWorkMergeGateway:
    def __init__(self, db: Session, writeback: MergeMetadataWritebackPort) -> None:
        self._db = db
        self._writeback = writeback

    def _load(
        self, work_ids: tuple[str, ...]
    ) -> tuple[list[LibraryWork], list[LibraryVersion], list[LibraryVolume]]:
        works_by_id = {
            work.id: work
            for work in self._db.scalars(
                select(LibraryWork).where(
                    LibraryWork.id.in_(work_ids), LibraryWork.hidden.is_(False)
                )
            ).all()
        }
        if len(works_by_id) != len(work_ids):
            raise WorkMergeNotFoundError("部分作品不存在或不可合并")
        works = [works_by_id[work_id] for work_id in work_ids]
        media_versions = list(
            self._db.scalars(
                select(LibraryVersion)
                .where(LibraryVersion.work_id.in_(work_ids))
                .order_by(
                    LibraryVersion.created_at.asc(), LibraryVersion.id.asc()
                )
            ).all()
        )
        media_ids = [media.id for media in media_versions]
        volumes = list(
            self._db.scalars(
                select(LibraryVolume)
                .where(LibraryVolume.version_id.in_(media_ids))
                .order_by(
                    LibraryVolume.sort_order.asc(),
                    LibraryVolume.created_at.asc(),
                    LibraryVolume.id.asc(),
                )
            ).all()
        )
        if not volumes:
            raise WorkMergeError("所选作品没有可合并的卷册")
        return works, media_versions, volumes

    def _ordered_volumes(
        self,
        work_ids: tuple[str, ...],
        media_versions: list[LibraryVersion],
        volumes: list[LibraryVolume],
    ) -> list[tuple[str, LibraryVolume]]:
        media_by_id = {media.id: media for media in media_versions}
        source_positions = {work_id: index for index, work_id in enumerate(work_ids)}
        return sorted(
            (
                (media_by_id[volume.version_id].source_key, volume)
                for volume in volumes
            ),
            key=lambda item: (
                MEDIA_KIND_ORDER.get(item[0], 99),
                0
                if item[1].volume_index is not None and isfinite(item[1].volume_index)
                else 1,
                item[1].volume_index
                if item[1].volume_index is not None and isfinite(item[1].volume_index)
                else 0,
                source_positions[media_by_id[item[1].version_id].work_id],
                item[1].sort_order,
                item[1].created_at,
                item[1].id,
            ),
        )

    def preview(self, work_ids: tuple[str, ...]) -> MergePreview:
        works, media_versions, volumes = self._load(work_ids)
        ordered = self._ordered_volumes(work_ids, media_versions, volumes)
        media_by_id = {media.id: media for media in media_versions}
        work_by_id = {work.id: work for work in works}
        groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        default_cover_volume_id = ordered[0][1].id
        for media_kind, volume in ordered:
            source_work = work_by_id[media_by_id[volume.version_id].work_id]
            has_cover = bool(volume.cover_path or source_work.cover_path)
            if has_cover and not any(
                item.get("hasCover") for values in groups.values() for item in values
            ):
                default_cover_volume_id = volume.id
            groups[media_kind].append(
                {
                    "id": volume.id,
                    "title": volume.title,
                    "volumeIndex": volume.volume_index,
                    "format": volume.format,
                    "sourceWorkId": source_work.id,
                    "sourceWorkTitle": source_work.title,
                    "coverUrl": f"/api/volumes/{volume.id}/cover?size=small",
                    "hasCover": has_cover,
                }
            )
        first = works[0]
        suggested = MergeMetadata(
            title=first.title,
            author=first.author or UNKNOWN_AUTHOR,
            description=first.description,
            series_name=first.series_name,
            series_index=first.series_index,
            tags=_unique_tags([tag for work in works for tag in _tags(work.tags)]),
        )
        return MergePreview(
            works=tuple(
                {
                    "id": work.id,
                    "title": work.title,
                    "author": work.author or UNKNOWN_AUTHOR,
                }
                for work in works
            ),
            media_groups=tuple(
                {"mediaKind": kind, "volumes": groups[kind]}
                for kind in ("EBOOK", "COMIC", "AUDIOBOOK")
                if groups.get(kind)
            ),
            suggested_metadata=suggested,
            default_cover_volume_id=default_cover_volume_id,
            write_metadata_to_files=self._writeback.enabled(),
        )

    def _assert_idle(self, work_ids: tuple[str, ...], volume_ids: list[str]) -> None:
        checks = (
            select(ImportTask.id).where(
                ImportTask.work_id.in_(work_ids),
                ImportTask.status.in_(("PENDING", "PARSING")),
            ),
            select(BookConversionTask.id).where(
                BookConversionTask.source_volume_id.in_(volume_ids),
                BookConversionTask.status.in_(("QUEUED", "RUNNING", "RETRY_WAIT")),
            ),
            select(OrganizeJob.id).where(
                OrganizeJob.work_id.in_(work_ids),
                OrganizeJob.status.in_(
                    ("LOOKUP_PENDING", "PENDING", "QUEUED", "RUNNING", "RETRY_WAIT")
                ),
            ),
            select(MetadataLookupTask.id).where(
                MetadataLookupTask.work_id.in_(work_ids),
                MetadataLookupTask.status.in_(("PENDING", "RUNNING", "RETRY_WAIT")),
            ),
            select(MetadataWritebackOperation.id).where(
                MetadataWritebackOperation.work_id.in_(work_ids),
                MetadataWritebackOperation.status.in_(("PENDING", "RUNNING")),
            ),
        )
        if any(self._db.scalar(statement.limit(1)) is not None for statement in checks):
            raise WorkMergeInProgressError("所选作品仍有后台任务正在处理，请稍后重试")

    def _prepare_merge_preferences(
        self,
        model: type[PreferenceT],
        work_ids: tuple[str, ...],
        new_work_id: str,
    ) -> tuple[Executable, ...]:
        rows = list(
            self._db.scalars(select(model).where(model.work_id.in_(work_ids))).all()
        )
        by_user: dict[str, list[PreferenceT]] = defaultdict(list)
        for row in rows:
            by_user[row.user_id].append(row)
        loser_ids: list[str] = []
        winner_ids: list[str] = []
        for candidates in by_user.values():
            winner = max(candidates, key=lambda row: (row.updated_at, row.id))
            loser_ids.extend(row.id for row in candidates if row is not winner)
            winner_ids.append(winner.id)
        statements: list[Executable] = []
        for chunk in sqlite_parameter_chunks(tuple(loser_ids), parameters_per_row=1):
            statements.append(delete(model).where(model.id.in_(chunk)))
        for chunk in sqlite_parameter_chunks(tuple(winner_ids), parameters_per_row=1):
            statements.append(
                update(model).where(model.id.in_(chunk)).values(work_id=new_work_id)
            )
        return tuple(statements)

    def _prepare_merge_progress_cursors(
        self, work_ids: tuple[str, ...], new_work_id: str
    ) -> tuple[Executable, ...]:
        rows = list(
            self._db.scalars(
                select(ReaderProgressCursor).where(
                    ReaderProgressCursor.work_id.in_(work_ids)
                )
            ).all()
        )
        grouped: dict[tuple[str, str], list[ReaderProgressCursor]] = defaultdict(list)
        for row in rows:
            grouped[(row.user_id, row.client_id)].append(row)
        loser_ids: list[str] = []
        winner_ids: list[str] = []
        for candidates in grouped.values():
            winner = max(
                candidates, key=lambda row: (row.high_water, row.updated_at, row.id)
            )
            loser_ids.extend(row.id for row in candidates if row is not winner)
            winner_ids.append(winner.id)
        statements: list[Executable] = []
        for chunk in sqlite_parameter_chunks(tuple(loser_ids), parameters_per_row=1):
            statements.append(
                delete(ReaderProgressCursor).where(ReaderProgressCursor.id.in_(chunk))
            )
        for chunk in sqlite_parameter_chunks(tuple(winner_ids), parameters_per_row=1):
            statements.append(
                update(ReaderProgressCursor)
                .where(ReaderProgressCursor.id.in_(chunk))
                .values(work_id=new_work_id)
            )
        return tuple(statements)

    def _operation_view(self, operation: dict[str, object]) -> dict[str, object]:
        return {
            "id": str(operation["id"]),
            "action": str(operation["action"]),
            "status": str(operation["status"]),
            "summary": str(operation["summary"]),
            "targetType": operation.get("targetType"),
            "targetId": operation.get("targetId"),
            "expiresAt": operation.get("expiresAt"),
            "undoneAt": operation.get("undoneAt"),
            "createdAt": operation.get("createdAt"),
            "updatedAt": operation.get("updatedAt"),
            "undoAvailable": operation.get("status") == "COMPLETED",
        }

    def merge(self, command: MergeCommand) -> MergeResult:
        return self._merge(command)

    def _merge(self, command: MergeCommand) -> MergeResult:
        works, media_versions, volumes = self._load(command.work_ids)
        volume_ids = [volume.id for volume in volumes]
        self._assert_idle(command.work_ids, volume_ids)
        selected_cover = next(
            (volume for volume in volumes if volume.id == command.cover_volume_id), None
        )
        if selected_cover is None:
            raise WorkMergeError("封面卷册不属于所选作品")
        now = _now()
        media_by_id = {media.id: media for media in media_versions}
        source_work_by_id = {work.id: work for work in works}
        selected_source_work = source_work_by_id[
            media_by_id[selected_cover.version_id].work_id
        ]
        cover_path = selected_cover.cover_path or selected_source_work.cover_path
        cover_status = (
            selected_cover.cover_status
            if selected_cover.cover_path
            else selected_source_work.cover_status
            if selected_source_work.cover_path
            else "PENDING"
        )
        first = works[0]
        new_work_id = cuid()
        author = command.metadata.author or UNKNOWN_AUTHOR
        tags_source = json.dumps(command.metadata.tags, ensure_ascii=False)
        work_row = {
            "id": new_work_id,
            "library_id": first.library_id,
            "origin": "MANUAL",
            "title": command.metadata.title,
            "normalized_title": normalize_identity_part(command.metadata.title),
            "author": author,
            "normalized_author": normalize_identity_part(author),
            "description": command.metadata.description,
            "publication_status": first.publication_status,
            "tracking_status": first.tracking_status,
            "tags": tags_source,
            "series_name": command.metadata.series_name,
            "series_index": command.metadata.series_index,
            "metadata_quality": 100,
            "organize_status": "APPLIED",
            "cover_path": cover_path,
            "cover_status": cover_status,
            "hidden": False,
            "organized": True,
            "merge_key": identity_merge_key(command.metadata.title, author),
            "created_at": now,
            "updated_at": now,
        }
        media_kinds = tuple(
            sorted(
                {media.source_key for media in media_versions},
                key=lambda value: MEDIA_KIND_ORDER.get(value, 99),
            )
        )
        new_media_ids = {kind: cuid() for kind in media_kinds}
        version_rows = tuple(
            {
                "id": new_media_ids[kind],
                "work_id": new_work_id,
                "source_key": kind,
                "created_at": now,
                "updated_at": now,
            }
            for kind in media_kinds
        )
        media_rows = tuple(
            {
                "id": new_media_ids[kind],
                "work_id": new_work_id,
                "media_kind": kind,
                "created_at": now,
                "updated_at": now,
            }
            for kind in media_kinds
        )

        ordered = self._ordered_volumes(command.work_ids, media_versions, volumes)
        kind_positions: dict[str, int] = defaultdict(int)
        volume_update_rows: list[dict[str, object]] = []
        for kind, volume in ordered:
            volume_update_rows.append(
                {
                    "id": volume.id,
                    "version_id": new_media_ids[kind],
                    "sort_order": kind_positions[kind],
                    "updated_at": now,
                }
            )
            kind_positions[kind] += 1

        source_media_ids = [media.id for media in media_versions]
        histories: list[UserMediaHistory] = []
        for chunk in sqlite_parameter_chunks(
            tuple(source_media_ids), parameters_per_row=1
        ):
            histories.extend(
                self._db.scalars(
                    select(UserMediaHistory).where(
                        UserMediaHistory.media_version_id.in_(chunk)
                    )
                ).all()
            )
        history_groups: dict[tuple[str, str], list[UserMediaHistory]] = defaultdict(
            list
        )
        for history in histories:
            history_groups[
                (history.user_id, media_by_id[history.media_version_id].source_key)
            ].append(history)
        history_loser_ids: list[str] = []
        history_winner_rows: list[dict[str, object]] = []
        for (_user_id, kind), candidates in history_groups.items():
            winner = max(candidates, key=lambda row: (row.updated_at, row.id))
            history_loser_ids.extend(
                history.id for history in candidates if history is not winner
            )
            history_winner_rows.append(
                {"id": winner.id, "media_version_id": new_media_ids[kind]}
            )

        shelf_ids = tuple(
            set(
                self._db.scalars(
                    select(ShelfWork.shelf_id).where(
                        ShelfWork.work_id.in_(command.work_ids)
                    )
                )
            )
        )
        preference_statements = (
            *self._prepare_merge_preferences(
                WorkDetailPreference, command.work_ids, new_work_id
            ),
            *self._prepare_merge_preferences(
                ReaderBookPreference, command.work_ids, new_work_id
            ),
            *self._prepare_merge_progress_cursors(command.work_ids, new_work_id),
        )

        lookup_rows = tuple(
            {
                "id": row.id,
                "work_id": new_work_id,
                "media_version_id": (
                    new_media_ids[media_by_id[row.media_version_id].source_key]
                    if row.media_version_id in media_by_id
                    else row.media_version_id
                ),
            }
            for row in self._db.scalars(
                select(MetadataLookupTask).where(
                    MetadataLookupTask.work_id.in_(command.work_ids)
                )
            ).all()
        )
        writeback_rows = tuple(
            {
                "id": row.id,
                "work_id": new_work_id,
                "media_version_id": (
                    new_media_ids[media_by_id[row.media_version_id].source_key]
                    if row.media_version_id in media_by_id
                    else row.media_version_id
                ),
            }
            for row in self._db.scalars(
                select(MetadataWritebackOperation).where(
                    MetadataWritebackOperation.work_id.in_(command.work_ids)
                )
            ).all()
        )
        facet_write = prepare_work_facet_write(
            (
                prepare_work_facet(
                    WorkFacetProjection(
                        work_id=new_work_id,
                        author=author,
                        tags_source=tags_source,
                        series_name=command.metadata.series_name,
                    )
                ),
            ),
            now=now,
        )
        operation_id = f"op_{time_ns()}"
        operation_view = {
            "id": operation_id,
            "action": "CREATE_MERGED_WORK",
            "status": "FINALIZED",
            "summary": f"已将 {len(works)} 本图书合并为《{command.metadata.title}》",
            "targetType": "work",
            "targetId": new_work_id,
            "expiresAt": None,
            "undoneAt": None,
            "createdAt": now,
            "updatedAt": now,
        }
        operation_row = {
            "id": operation_id,
            "user_id": command.actor_id,
            "action": operation_view["action"],
            "status": operation_view["status"],
            "target_type": "work",
            "target_id": new_work_id,
            "summary": operation_view["summary"],
            "payload_json": json.dumps(
                {
                    "workId": new_work_id,
                    "sourceWorkIds": list(command.work_ids),
                },
                ensure_ascii=False,
            ),
            "inverse_json": "{}",
            "expires_at": None,
            "created_at": now,
            "updated_at": now,
        }
        # Provider settings are read before the first DML. The current metadata
        # queue uses explicit post-commit preparations, so this merge returns no
        # synchronous writeback operation rows.
        self._writeback.enabled()

        history_delete_statements = tuple(
            delete(UserMediaHistory).where(UserMediaHistory.id.in_(chunk))
            for chunk in sqlite_parameter_chunks(
                tuple(history_loser_ids), parameters_per_row=1
            )
        )
        shelf_rows = tuple(
            {"shelf_id": shelf_id, "work_id": new_work_id, "created_at": now}
            for shelf_id in shelf_ids
        )
        shelf_insert_statements = tuple(
            insert(ShelfWork).values(list(chunk))
            for chunk in sqlite_parameter_chunks(shelf_rows, parameters_per_row=3)
        )
        source_media_delete_statements = tuple(
            (
                delete(LibraryMediaVersion).where(LibraryMediaVersion.id.in_(chunk)),
                delete(LibraryVersion).where(LibraryVersion.id.in_(chunk)),
            )
            for chunk in sqlite_parameter_chunks(
                tuple(source_media_ids), parameters_per_row=1
            )
        )
        source_media_delete_statements = tuple(
            statement
            for pair in source_media_delete_statements
            for statement in pair
        )
        result = MergeResult(
            work_id=new_work_id,
            source_work_ids=command.work_ids,
            media_versions=tuple(
                {
                    "id": new_media_ids[kind],
                    "mediaKind": kind,
                    "volumeCount": kind_positions[kind],
                }
                for kind in media_kinds
            ),
            metadata_writebacks=(),
            operation=self._operation_view(operation_view),
        )

        self._db.execute(insert(LibraryWork), [work_row])
        self._db.execute(insert(LibraryVersion), list(version_rows))
        self._db.execute(insert(LibraryMediaVersion), list(media_rows))
        self._db.execute(update(LibraryVolume), volume_update_rows)
        for statement in history_delete_statements:
            self._db.execute(statement)
        if history_winner_rows:
            self._db.execute(update(UserMediaHistory), history_winner_rows)

        self._db.execute(
            delete(ShelfWork).where(ShelfWork.work_id.in_(command.work_ids))
        )
        for statement in shelf_insert_statements:
            self._db.execute(statement)

        for statement in preference_statements:
            self._db.execute(statement)

        self._db.execute(
            update(ImportTask)
            .where(ImportTask.work_id.in_(command.work_ids))
            .values(work_id=new_work_id)
        )
        self._db.execute(
            update(KindleSendTask)
            .where(KindleSendTask.work_id.in_(command.work_ids))
            .values(work_id=new_work_id)
        )
        if lookup_rows:
            self._db.execute(update(MetadataLookupTask), list(lookup_rows))
        if writeback_rows:
            self._db.execute(update(MetadataWritebackOperation), list(writeback_rows))
        for statement in source_media_delete_statements:
            self._db.execute(statement)
        self._db.execute(
            delete(LibraryWork).where(LibraryWork.id.in_(command.work_ids))
        )
        execute_work_facet_write(self._db, facet_write)
        self._db.execute(insert(LibraryOperation), [operation_row])
        return result
