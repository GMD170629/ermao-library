"""SQLAlchemy adapter for volume-scoped library commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.common import cuid
from app.models.import_pipeline import ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.library.application.volume_commands import (
    LibraryActor,
    NewWorkInput,
    VolumeContext,
    VolumeDeleteOutcome,
    VolumeMoveOutcome,
    VolumeSplitOutcome,
)
from app.modules.library.infrastructure import operations as operation_store
from app.modules.library.infrastructure.deletion import delete_volume_scope
from app.modules.library.infrastructure.structural_operations import (
    move_volume_to_work,
    reorder_volume as reorder_volume_within_media_version,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
    normalize_identity_part,
)

QueueImportTask = Callable[..., tuple[ImportTaskDTO, bool]]


class SqlAlchemyVolumeStructure:
    def __init__(self, db: Session, queue_import_task: QueueImportTask) -> None:
        self._db = db
        self._queue_import_task = queue_import_task

    @staticmethod
    def _authorization_context(actor: LibraryActor) -> AuthorizationContext:
        return AuthorizationContext(
            user_id=actor.user_id,
            is_admin=actor.is_admin,
            can_manage_system=actor.can_manage_system,
            can_view_manual_imports=actor.can_view_manual_imports,
            monitor_folder_ids=actor.monitor_folder_ids,
            authz_version=1,
        )

    def can_access_work(self, *, actor: LibraryActor, work_id: str) -> bool:
        context = self._authorization_context(actor)
        return (
            self._db.scalar(
                select(LibraryWork.id).where(
                    LibraryWork.id == work_id,
                    work_visibility_predicate(context),
                )
            )
            is not None
        )

    def get_volume_context(
        self, *, actor: LibraryActor, work_id: str, volume_id: str
    ) -> VolumeContext | None:
        authorization = self._authorization_context(actor)
        row = self._db.execute(
            select(LibraryVolume, LibraryWork)
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .join(LibraryWork, LibraryWork.id == LibraryMediaVersion.work_id)
            .where(
                LibraryVolume.id == volume_id,
                LibraryWork.id == work_id,
                LibraryVolume.hidden.is_(False),
                volume_visibility_predicate(authorization),
            )
        ).one_or_none()
        if row is None:
            return None
        volume, work = row
        source_path = self._db.scalar(
            select(LibraryFile.path)
            .where(LibraryFile.volume_id == volume_id)
            .order_by(LibraryFile.sort_order.asc(), LibraryFile.id.asc())
            .limit(1)
        )
        media_version = self._db.get(LibraryMediaVersion, volume.media_version_id)
        if media_version is None:
            return None
        return VolumeContext(
            id=volume.id,
            work_id=work.id,
            media_version_id=volume.media_version_id,
            media_kind=media_version.media_kind,
            title=volume.title,
            format=volume.format,
            monitor_folder_id=volume.monitor_folder_id,
            author=work.author,
            source_path=Path(source_path).expanduser() if source_path else None,
        )

    def update_volume(
        self, *, volume_id: str, changes: dict[str, object], now: datetime
    ) -> None:
        volume = self._db.get(LibraryVolume, volume_id)
        if volume is None:
            raise ValueError("卷册不存在")
        for attribute, value in changes.items():
            setattr(volume, attribute, value)
        volume.updated_at = now
        self._db.flush()

    def _move_inverse(
        self,
        *,
        source_work_id: str,
        volume_id: str,
    ) -> dict[str, object]:
        volume = self._db.get(LibraryVolume, volume_id)
        if volume is None:
            raise ValueError("Volume does not exist")
        source_media = self._db.get(LibraryMediaVersion, volume.media_version_id)
        if source_media is None or source_media.work_id != source_work_id:
            raise ValueError("Volume does not belong to work")
        source_volume_count = int(
            self._db.scalar(
                select(func.count(LibraryVolume.id)).where(
                    LibraryVolume.media_version_id == source_media.id
                )
            )
            or 0
        )
        source_media_count = int(
            self._db.scalar(
                select(func.count(LibraryMediaVersion.id)).where(
                    LibraryMediaVersion.work_id == source_work_id
                )
            )
            or 0
        )
        histories = self._db.scalars(
            select(UserMediaHistory).where(
                UserMediaHistory.media_version_id == source_media.id
            )
        ).all()
        source_work = self._db.get(LibraryWork, source_work_id)
        deletes_source_work = source_volume_count == 1 and source_media_count == 1
        return {
            "sourceWork": (
                entity_as_legacy_dict(source_work)
                if source_work is not None and deletes_source_work
                else None
            ),
            "sourceWorkDependents": (
                operation_store.snapshot_work_dependents(
                    self._db,
                    source_work_id,
                )
                if deletes_source_work
                else {}
            ),
            "sourceMediaVersion": entity_as_legacy_dict(source_media),
            "volume": entity_as_legacy_dict(volume),
            "mediaHistories": [entity_as_legacy_dict(row) for row in histories],
        }

    def move_volume(
        self,
        *,
        actor_id: str,
        source_work_id: str,
        volume_id: str,
        target_work_id: str,
        now: datetime,
    ) -> VolumeMoveOutcome:
        if source_work_id == target_work_id:
            raise ValueError("Source and target work must differ")
        inverse = self._move_inverse(
            source_work_id=source_work_id,
            volume_id=volume_id,
        )
        volume_row = inverse.get("volume")
        volume_title = (
            str(volume_row.get("title") or volume_id)
            if isinstance(volume_row, dict)
            else volume_id
        )
        result = move_volume_to_work(
            self._db,
            source_work_id=source_work_id,
            volume_id=volume_id,
            target_work_id=target_work_id,
            now=now,
        )
        inverse.update(
            {
                "targetWorkId": target_work_id,
                "targetMediaVersionId": result.target_media_version_id,
                "targetMediaVersionCreated": (
                    result.transfer_mode == "CREATED_MEDIA_VERSION"
                ),
            }
        )
        operation = operation_store.create_operation(
            self._db,
            user_id=actor_id,
            action="MOVE_VOLUME",
            target_type="volume",
            target_id=volume_id,
            summary=f"Moved volume {volume_title}",
            payload={
                "sourceWorkId": source_work_id,
                "targetWorkId": target_work_id,
                "volumeId": volume_id,
            },
            inverse=inverse,
            now=now,
        )
        return VolumeMoveOutcome(
            move=result,
            operation=operation_store.operation_summary(operation),
        )

    def reorder_volume(
        self,
        *,
        volume_id: str,
        media_version_id: str,
        direction: Literal["up", "down"],
        now: datetime,
    ) -> bool:
        return reorder_volume_within_media_version(
            self._db,
            volume_id=volume_id,
            media_version_id=media_version_id,
            direction=direction,
            now=now,
        )

    def create_work_from_volume(
        self,
        *,
        source_work_id: str,
        new_work: NewWorkInput,
        now: datetime,
    ) -> str:
        source = self._db.get(LibraryWork, source_work_id)
        if source is None:
            raise ValueError("作品不存在")
        author = str(new_work.author or source.author or UNKNOWN_AUTHOR).strip()
        author = author or UNKNOWN_AUTHOR
        work_id = cuid()
        self._db.add(
            LibraryWork(
                id=work_id,
                monitor_folder_id=source.monitor_folder_id,
                origin=source.origin,
                title=new_work.title,
                normalized_title=normalize_identity_part(new_work.title),
                author=author,
                normalized_author=normalize_identity_part(author),
                description=source.description,
                work_type=source.work_type,
                tags=source.tags,
                cover_status="PENDING",
                merge_key=identity_merge_key(new_work.title, author),
                created_at=now,
                updated_at=now,
            )
        )
        self._db.flush()
        return work_id

    def split_volume(
        self,
        *,
        actor_id: str,
        source_work_id: str,
        volume_id: str,
        new_work: NewWorkInput,
        now: datetime,
    ) -> VolumeSplitOutcome:
        inverse = self._move_inverse(
            source_work_id=source_work_id,
            volume_id=volume_id,
        )
        target_work_id = self.create_work_from_volume(
            source_work_id=source_work_id,
            new_work=new_work,
            now=now,
        )
        move = move_volume_to_work(
            self._db,
            source_work_id=source_work_id,
            volume_id=volume_id,
            target_work_id=target_work_id,
            now=now,
        )
        inverse.update(
            {
                "targetWorkId": target_work_id,
                "targetMediaVersionId": move.target_media_version_id,
                "targetMediaVersionCreated": True,
                "newWorkId": target_work_id,
            }
        )
        operation = operation_store.create_operation(
            self._db,
            user_id=actor_id,
            action="SPLIT_VOLUME",
            target_type="volume",
            target_id=volume_id,
            summary=f"Split volume into {new_work.title}",
            payload={
                "sourceWorkId": source_work_id,
                "newWorkId": target_work_id,
                "volumeId": volume_id,
            },
            inverse=inverse,
            now=now,
        )
        return VolumeSplitOutcome(
            target_work_id=target_work_id,
            move=move,
            operation=operation_store.operation_summary(operation),
        )

    def delete_volume(
        self,
        *,
        actor_id: str,
        work_id: str,
        volume_id: str,
        now: datetime,
    ) -> VolumeDeleteOutcome:
        snapshot = operation_store.capture_volume_delete_snapshot(
            self._db,
            work_id=work_id,
            volume_id=volume_id,
        )
        volume = snapshot["LibraryVolume"][0]
        title = str(volume.get("title") or volume_id)
        deleted_media_version = bool(snapshot.get("LibraryMediaVersion"))
        deleted_work = bool(snapshot.get("LibraryWork"))
        if delete_volume_scope(self._db, volume_id) != 1:
            raise ValueError("Volume does not exist")
        operation = operation_store.create_operation(
            self._db,
            user_id=actor_id,
            action="DELETE_VOLUME",
            target_type="volume",
            target_id=volume_id,
            summary=f"Deleted volume {title}",
            payload={"workId": work_id, "volumeId": volume_id},
            inverse={"snapshot": snapshot},
            now=now,
        )
        return VolumeDeleteOutcome(
            work_id=work_id,
            volume_id=volume_id,
            deleted_media_version=deleted_media_version,
            deleted_work=deleted_work,
            operation=operation_store.operation_summary(operation),
        )

    def queue_epub_conversion(
        self, *, context: VolumeContext, now: datetime
    ) -> tuple[object, bool]:
        if context.source_path is None:
            raise ValueError("原始文件不存在")
        task, created = self._queue_import_task(
            self._db,
            context.source_path,
            origin="DEFERRED_CONVERSION",
            original_name=context.source_path.name,
            requested_title=context.title,
            requested_author=context.author,
            work_id=context.work_id,
            monitor_folder_id=context.monitor_folder_id,
            message="已加入 EPUB 转换队列",
            allow_terminal_requeue=True,
        )
        row = self._db.get(ImportTask, task.id)
        if row is not None:
            row.volume_id = context.id
        self._db.flush()
        return task, created
