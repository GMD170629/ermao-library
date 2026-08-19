"""SQLAlchemy adapter for volume-scoped library commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.common import cuid
from app.models.library import (
    LibraryFile,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.application.volume_commands import (
    BatchVolumeCommand,
    BatchVolumeOutcome,
    LibraryActor,
    NewWorkInput,
    VolumeContext,
    VolumeDeleteOutcome,
    VolumeReclassifyOutcome,
    VolumeSplitOutcome,
)
from app.modules.library.domain.media_kinds import media_kind_of
from app.modules.library.infrastructure import operations as operation_store
from app.modules.library.infrastructure.batch_volume_commands import (
    execute_batch_volume_mutation,
    prepare_batch_volume_mutation,
)
from app.modules.library.infrastructure.deletion import (
    execute_prepared_volume_scope_deletion,
    prepare_delete_volume_scope,
)
from app.modules.library.infrastructure.structural_operations import (
    execute_prepared_volume_move,
    prepare_split_volume_move,
)
from app.modules.library.infrastructure.structural_operations import (
    reorder_volume as reorder_volume_within_version,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
    normalize_identity_part,
)


class SqlAlchemyVolumeStructure:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _authorization_context(actor: LibraryActor) -> AuthorizationContext:
        return AuthorizationContext(
            user_id=actor.user_id,
            is_admin=actor.is_admin,
            can_manage_system=actor.can_manage_system,
            can_view_manual_imports=actor.can_view_manual_imports,
            library_ids=actor.library_ids,
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

    def work_library_id(self, *, work_id: str) -> str | None:
        work = self._db.get(LibraryWork, work_id)
        if work is None:
            return None
        return str(work.library_id)

    def apply_batch(
        self,
        *,
        actor_id: str,
        source_work_id: str,
        contexts: tuple[VolumeContext, ...],
        command: BatchVolumeCommand,
        now: datetime,
    ) -> BatchVolumeOutcome:
        prepared = prepare_batch_volume_mutation(
            self._db,
            actor_id=actor_id,
            source_work_id=source_work_id,
            contexts=contexts,
            command=command,
            now=now,
        )
        return execute_batch_volume_mutation(self._db, prepared)

    def get_volume_context(
        self, *, actor: LibraryActor, work_id: str, volume_id: str
    ) -> VolumeContext | None:
        contexts = self.get_volume_contexts(
            actor=actor,
            work_id=work_id,
            volume_ids=(volume_id,),
        )
        return contexts[0] if contexts else None

    def get_volume_contexts(
        self,
        *,
        actor: LibraryActor,
        work_id: str,
        volume_ids: tuple[str, ...],
    ) -> tuple[VolumeContext, ...]:
        if not volume_ids:
            return ()
        authorization = self._authorization_context(actor)
        source_path = (
            select(LibraryFile.path)
            .where(LibraryFile.volume_id == LibraryVolume.id)
            .order_by(LibraryFile.sort_order.asc(), LibraryFile.id.asc())
            .limit(1)
            .scalar_subquery()
        )
        rows = self._db.execute(
            select(LibraryVolume, LibraryWork, LibraryVersion, source_path)
            .join(
                LibraryVersion,
                LibraryVersion.id == LibraryVolume.version_id,
            )
            .join(LibraryWork, LibraryWork.id == LibraryVersion.work_id)
            .where(
                LibraryVolume.id.in_(volume_ids),
                LibraryWork.id == work_id,
                LibraryVolume.hidden.is_(False),
                volume_visibility_predicate(authorization),
            )
        ).all()
        contexts = {
            volume.id: VolumeContext(
                id=volume.id,
                work_id=work.id,
                version_id=volume.version_id,
                media_kind=media_kind_of(volume),
                title=volume.title,
                sort_order=volume.sort_order,
                format=volume.format,
                library_id=work.library_id,
                author=work.author,
                work_title=work.title,
                source_path=(Path(path_value).expanduser() if path_value else None),
            )
            for volume, work, version, path_value in rows
        }
        return tuple(
            contexts[volume_id] for volume_id in volume_ids if volume_id in contexts
        )

    def update_volume(
        self, *, volume_id: str, changes: dict[str, object], now: datetime
    ) -> None:
        result = self._db.execute(
            update(LibraryVolume)
            .where(LibraryVolume.id == volume_id)
            .values(**changes, updated_at=now)
        )
        if result.rowcount != 1:
            raise ValueError("卷册不存在")

    def _move_inverse(
        self,
        *,
        source_work_id: str,
        volume_id: str,
    ) -> dict[str, object]:
        volume = self._db.get(LibraryVolume, volume_id)
        if volume is None:
            raise ValueError("Volume does not exist")
        source_version = self._db.get(LibraryVersion, volume.version_id)
        if source_version is None or source_version.work_id != source_work_id:
            raise ValueError("Volume does not belong to work")
        source_volume_count = int(
            self._db.scalar(
                select(func.count(LibraryVolume.id)).where(
                    LibraryVolume.version_id == source_version.id
                )
            )
            or 0
        )
        source_version_count = int(
            self._db.scalar(
                select(func.count(LibraryVersion.id)).where(
                    LibraryVersion.work_id == source_work_id
                )
            )
            or 0
        )
        source_work = self._db.get(LibraryWork, source_work_id)
        deletes_source_work = source_volume_count == 1 and source_version_count == 1
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
            "sourceVersion": entity_as_legacy_dict(source_version),
            "volume": entity_as_legacy_dict(volume),
        }

    def reorder_volume(
        self,
        *,
        volume_id: str,
        version_id: str,
        direction: Literal["up", "down"],
        now: datetime,
    ) -> bool:
        return reorder_volume_within_version(
            self._db,
            volume_id=volume_id,
            version_id=version_id,
            direction=direction,
            now=now,
        )

    def reclassify_volume(
        self,
        *,
        actor_id: str,
        work_id: str,
        volume_id: str,
        target_media_kind: str,
        apply_to: Literal["VOLUME", "SAME_MEDIA_KIND"],
        now: datetime,
    ) -> VolumeReclassifyOutcome:
        volume = self._db.get(LibraryVolume, volume_id)
        if volume is None:
            raise ValueError("Volume does not exist")
        source_version = self._db.get(LibraryVersion, volume.version_id)
        if source_version is None or source_version.work_id != work_id:
            raise ValueError("Volume does not belong to work")
        current_kind = media_kind_of(volume)
        if apply_to == "SAME_MEDIA_KIND":
            work_volumes = list(
                self._db.scalars(
                    select(LibraryVolume)
                    .join(
                        LibraryVersion,
                        LibraryVersion.id == LibraryVolume.version_id,
                    )
                    .where(LibraryVersion.work_id == work_id)
                    .order_by(
                        LibraryVolume.sort_order.asc(),
                        LibraryVolume.created_at.asc(),
                        LibraryVolume.id.asc(),
                    )
                ).all()
            )
            selected = [
                row for row in work_volumes if media_kind_of(row) == current_kind
            ]
        else:
            selected = [volume]
        inverse = {
            "volumes": [entity_as_legacy_dict(row) for row in selected],
        }
        selected_update_rows = [
            {
                "id": selected_volume.id,
                "classification_source": "USER",
                "classification_reason": "USER_OVERRIDE",
                "suggested_media_kind": target_media_kind,
                "updated_at": now,
            }
            for selected_volume in selected
        ]
        operation = operation_store.prepare_operation_write(
            user_id=actor_id,
            action="RECLASSIFY_VOLUME",
            target_type="volume",
            target_id=volume_id,
            summary=f"Reclassified {len(selected)} volume(s) as {target_media_kind}",
            payload={
                "workId": work_id,
                "volumeId": volume_id,
                "targetMediaKind": target_media_kind,
                "applyTo": apply_to,
            },
            inverse=inverse,
            now=now,
        )
        outcome = VolumeReclassifyOutcome(
            moved_volume_ids=tuple(row.id for row in selected),
            operation=operation_store.operation_summary(operation.record),
        )
        if selected_update_rows:
            self._db.execute(update(LibraryVolume), selected_update_rows)
        operation_store.write_prepared_operation(self._db, operation)
        return outcome

    def _prepare_work_from_volume(
        self,
        *,
        source_work_id: str,
        new_work: NewWorkInput,
        now: datetime,
    ) -> tuple[str, dict[str, object]]:
        source = self._db.get(LibraryWork, source_work_id)
        if source is None:
            raise ValueError("作品不存在")
        author = str(new_work.author or source.author or UNKNOWN_AUTHOR).strip()
        author = author or UNKNOWN_AUTHOR
        work_id = cuid()
        return work_id, {
            "id": work_id,
            "library_id": source.library_id,
            "origin": source.origin,
            "title": new_work.title,
            "normalized_title": normalize_identity_part(new_work.title),
            "author": author,
            "normalized_author": normalize_identity_part(author),
            "description": source.description,
            "tags": source.tags,
            "cover_status": "PENDING",
            "merge_key": identity_merge_key(new_work.title, author),
            "created_at": now,
            "updated_at": now,
        }

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
        target_work_id, work_row = self._prepare_work_from_volume(
            source_work_id=source_work_id,
            new_work=new_work,
            now=now,
        )
        prepared_move = prepare_split_volume_move(
            self._db,
            source_work_id=source_work_id,
            volume_id=volume_id,
            target_work_id=target_work_id,
            now=now,
        )
        inverse.update(
            {
                "targetWorkId": target_work_id,
                "targetVersionId": prepared_move.result.target_version_id,
                "targetVersionCreated": True,
                "newWorkId": target_work_id,
            }
        )
        operation = operation_store.prepare_operation_write(
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
        outcome = VolumeSplitOutcome(
            target_work_id=target_work_id,
            move=prepared_move.result,
            operation=operation_store.operation_summary(operation.record),
        )
        self._db.execute(insert(LibraryWork), [work_row])
        execute_prepared_volume_move(self._db, prepared_move)
        operation_store.write_prepared_operation(self._db, operation)
        return outcome

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
        deleted_version = bool(snapshot.get("LibraryVersion"))
        deleted_work = bool(snapshot.get("LibraryWork"))
        prepared_deletion = prepare_delete_volume_scope(self._db, volume_id)
        if prepared_deletion is None:
            raise ValueError("Volume does not exist")
        operation = operation_store.prepare_operation_write(
            user_id=actor_id,
            action="DELETE_VOLUME",
            target_type="volume",
            target_id=volume_id,
            summary=f"Deleted volume {title}",
            payload={"workId": work_id, "volumeId": volume_id},
            inverse={"snapshot": snapshot},
            now=now,
        )
        outcome = VolumeDeleteOutcome(
            work_id=work_id,
            volume_id=volume_id,
            deleted_version=deleted_version,
            deleted_work=deleted_work,
            operation=operation_store.operation_summary(operation.record),
        )
        if execute_prepared_volume_scope_deletion(self._db, prepared_deletion) != 1:
            raise ValueError("Volume does not exist")
        operation_store.write_prepared_operation(self._db, operation)
        return outcome
