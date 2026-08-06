"""SQLAlchemy adapter for merging several works into one new work."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite
from typing import TypeVar

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import BookConversionTask, ImportTask, KindleSendTask
from app.models.library import (
    LibraryMediaVersion,
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
from app.modules.library.application.commands import execute_library_write
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
from app.modules.library.infrastructure import operations
from app.modules.library.infrastructure.facets import sync_work_facets
from app.modules.library.infrastructure.works import entity_as_legacy_dict
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
    ) -> tuple[list[LibraryWork], list[LibraryMediaVersion], list[LibraryVolume]]:
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
                select(LibraryMediaVersion)
                .where(LibraryMediaVersion.work_id.in_(work_ids))
                .order_by(
                    LibraryMediaVersion.created_at.asc(), LibraryMediaVersion.id.asc()
                )
            ).all()
        )
        media_ids = [media.id for media in media_versions]
        volumes = list(
            self._db.scalars(
                select(LibraryVolume)
                .where(LibraryVolume.media_version_id.in_(media_ids))
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
        media_versions: list[LibraryMediaVersion],
        volumes: list[LibraryVolume],
    ) -> list[tuple[str, LibraryVolume]]:
        media_by_id = {media.id: media for media in media_versions}
        source_positions = {work_id: index for index, work_id in enumerate(work_ids)}
        return sorted(
            (
                (media_by_id[volume.media_version_id].media_kind, volume)
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
                source_positions[media_by_id[item[1].media_version_id].work_id],
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
            source_work = work_by_id[media_by_id[volume.media_version_id].work_id]
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

    def _merge_preferences(
        self,
        model: type[PreferenceT],
        work_ids: tuple[str, ...],
        new_work_id: str,
    ) -> None:
        rows = list(
            self._db.scalars(select(model).where(model.work_id.in_(work_ids))).all()
        )
        by_user: dict[str, list[PreferenceT]] = defaultdict(list)
        for row in rows:
            by_user[row.user_id].append(row)
        for candidates in by_user.values():
            winner = max(candidates, key=lambda row: (row.updated_at, row.id))
            for row in candidates:
                if row is not winner:
                    self._db.delete(row)
            self._db.flush()
            winner.work_id = new_work_id

    def _merge_progress_cursors(
        self, work_ids: tuple[str, ...], new_work_id: str
    ) -> None:
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
        for candidates in grouped.values():
            winner = max(
                candidates, key=lambda row: (row.high_water, row.updated_at, row.id)
            )
            for row in candidates:
                if row is not winner:
                    self._db.delete(row)
            self._db.flush()
            winner.work_id = new_work_id

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
        return execute_library_write(self._db, lambda: self._merge(command))

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
            media_by_id[selected_cover.media_version_id].work_id
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
        new_work = LibraryWork(
            monitor_folder_id=None,
            origin="MANUAL",
            title=command.metadata.title,
            normalized_title=normalize_identity_part(command.metadata.title),
            author=command.metadata.author or UNKNOWN_AUTHOR,
            normalized_author=normalize_identity_part(
                command.metadata.author or UNKNOWN_AUTHOR
            ),
            description=command.metadata.description,
            publication_status=first.publication_status,
            tracking_status=first.tracking_status,
            tags=json.dumps(command.metadata.tags, ensure_ascii=False),
            series_name=command.metadata.series_name,
            series_index=command.metadata.series_index,
            metadata_quality=100,
            organize_status="APPLIED",
            cover_path=cover_path,
            cover_status=cover_status,
            hidden=False,
            organized=True,
            merge_key=identity_merge_key(
                command.metadata.title, command.metadata.author or UNKNOWN_AUTHOR
            ),
            created_at=now,
            updated_at=now,
        )
        self._db.add(new_work)
        self._db.flush()

        new_media: dict[str, LibraryMediaVersion] = {}
        for kind in sorted(
            {media.media_kind for media in media_versions},
            key=lambda value: MEDIA_KIND_ORDER.get(value, 99),
        ):
            media = LibraryMediaVersion(
                work_id=new_work.id, media_kind=kind, created_at=now, updated_at=now
            )
            self._db.add(media)
            self._db.flush()
            new_media[kind] = media

        ordered = self._ordered_volumes(command.work_ids, media_versions, volumes)
        kind_positions: dict[str, int] = defaultdict(int)
        for kind, volume in ordered:
            volume.media_version_id = new_media[kind].id
            volume.sort_order = kind_positions[kind]
            volume.updated_at = now
            kind_positions[kind] += 1

        source_media_ids = [media.id for media in media_versions]
        histories = list(
            self._db.scalars(
                select(UserMediaHistory).where(
                    UserMediaHistory.media_version_id.in_(source_media_ids)
                )
            ).all()
        )
        history_groups: dict[tuple[str, str], list[UserMediaHistory]] = defaultdict(
            list
        )
        for history in histories:
            history_groups[
                (history.user_id, media_by_id[history.media_version_id].media_kind)
            ].append(history)
        for (_user_id, kind), candidates in history_groups.items():
            winner = max(candidates, key=lambda row: (row.updated_at, row.id))
            for history in candidates:
                if history is not winner:
                    self._db.delete(history)
            self._db.flush()
            winner.media_version_id = new_media[kind].id

        shelf_ids = set(
            self._db.scalars(
                select(ShelfWork.shelf_id).where(
                    ShelfWork.work_id.in_(command.work_ids)
                )
            )
        )
        self._db.execute(
            delete(ShelfWork).where(ShelfWork.work_id.in_(command.work_ids))
        )
        for shelf_id in shelf_ids:
            self._db.add(
                ShelfWork(shelf_id=shelf_id, work_id=new_work.id, created_at=now)
            )

        self._merge_preferences(WorkDetailPreference, command.work_ids, new_work.id)
        self._merge_preferences(ReaderBookPreference, command.work_ids, new_work.id)
        self._merge_progress_cursors(command.work_ids, new_work.id)

        self._db.execute(
            update(ImportTask)
            .where(ImportTask.work_id.in_(command.work_ids))
            .values(work_id=new_work.id)
        )
        self._db.execute(
            update(KindleSendTask)
            .where(KindleSendTask.work_id.in_(command.work_ids))
            .values(work_id=new_work.id)
        )
        lookup_rows = list(
            self._db.scalars(
                select(MetadataLookupTask).where(
                    MetadataLookupTask.work_id.in_(command.work_ids)
                )
            ).all()
        )
        for row in lookup_rows:
            row.work_id = new_work.id
            if row.media_version_id in media_by_id:
                row.media_version_id = new_media[
                    media_by_id[row.media_version_id].media_kind
                ].id
        writeback_rows = list(
            self._db.scalars(
                select(MetadataWritebackOperation).where(
                    MetadataWritebackOperation.work_id.in_(command.work_ids)
                )
            ).all()
        )
        for row in writeback_rows:
            row.work_id = new_work.id
            if row.media_version_id in media_by_id:
                row.media_version_id = new_media[
                    media_by_id[row.media_version_id].media_kind
                ].id

        self._db.flush()
        self._db.execute(
            delete(LibraryMediaVersion).where(
                LibraryMediaVersion.id.in_(source_media_ids)
            )
        )
        self._db.execute(
            delete(LibraryWork).where(LibraryWork.id.in_(command.work_ids))
        )
        sync_work_facets(self._db, new_work.id)

        writeback_enabled = self._writeback.enabled()
        writebacks: list[dict[str, object]] = []
        if writeback_enabled:
            for kind in ("EBOOK", "COMIC", "AUDIOBOOK"):
                target_media = new_media.get(kind)
                if target_media is None:
                    continue
                view = self._writeback.enqueue(
                    work_id=new_work.id,
                    media_version_id=target_media.id,
                )
                if view is not None:
                    writebacks.append(view)

        operation = operations.create_operation(
            self._db,
            user_id=command.actor_id,
            action="CREATE_MERGED_WORK",
            target_type="work",
            target_id=new_work.id,
            summary=f"已将 {len(works)} 本图书合并为《{new_work.title}》",
            payload={"workId": new_work.id, "sourceWorkIds": list(command.work_ids)},
            inverse={},
            now=now,
            undoable=False,
        )
        return MergeResult(
            work_id=new_work.id,
            source_work_ids=command.work_ids,
            media_versions=tuple(
                {
                    "id": media.id,
                    "mediaKind": kind,
                    "volumeCount": kind_positions[kind],
                }
                for kind, media in sorted(
                    new_media.items(),
                    key=lambda item: MEDIA_KIND_ORDER.get(item[0], 99),
                )
            ),
            metadata_writebacks=tuple(writebacks),
            operation=self._operation_view(operation),
        )
