"""SQLAlchemy adapter for volume metadata and content classification."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.library import LibraryVersion, LibraryVolume, LibraryWork
from app.modules.library.application.volume_commands import (
    LibraryActor,
    SetVolumeMediaKindsOutcome,
    VolumeContext,
    VolumeMetadataChanges,
    VolumeReclassifyOutcome,
)
from app.modules.library.domain.media_kinds import media_kind_of
from app.modules.library.infrastructure import operations as operation_store


def _classification_snapshot(volume: LibraryVolume) -> dict[str, object]:
    return {
        "id": volume.id,
        "classificationSource": volume.classification_source,
        "classificationReason": volume.classification_reason,
        "suggestedMediaKind": volume.suggested_media_kind,
        "updatedAt": volume.updated_at,
    }


class SqlAlchemyVolumeMetadata:
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
        rows = self._db.execute(
            select(LibraryVolume, LibraryWork)
            .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
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
                sort_order=volume.sort_order,
            )
            for volume, work in rows
        }
        return tuple(
            contexts[volume_id] for volume_id in volume_ids if volume_id in contexts
        )

    def update_volume(
        self,
        *,
        volume_id: str,
        changes: VolumeMetadataChanges,
        now: datetime,
    ) -> None:
        result = self._db.execute(
            update(LibraryVolume)
            .where(LibraryVolume.id == volume_id)
            .values(**changes, updated_at=now)
        )
        if result.rowcount != 1:
            raise ValueError("卷册不存在")

    def set_media_kinds(
        self,
        *,
        actor_id: str,
        work_id: str,
        contexts: tuple[VolumeContext, ...],
        target_media_kind: str,
        now: datetime,
    ) -> SetVolumeMediaKindsOutcome:
        volume_ids = tuple(context.id for context in contexts)
        volumes = list(
            self._db.scalars(
                select(LibraryVolume).where(LibraryVolume.id.in_(volume_ids))
            ).all()
        )
        by_id = {volume.id: volume for volume in volumes}
        if set(by_id) != set(volume_ids):
            raise ValueError("Volume does not exist")

        operation_ids: list[str] = []
        for context in contexts:
            volume = by_id[context.id]
            operation = operation_store.prepare_operation_write(
                user_id=actor_id,
                action="RECLASSIFY_VOLUME",
                target_type="volume",
                target_id=context.id,
                summary=f"Reclassified volume as {target_media_kind}",
                payload={
                    "workId": work_id,
                    "volumeId": context.id,
                    "targetMediaKind": target_media_kind,
                },
                inverse={"volumes": [_classification_snapshot(volume)]},
                now=now,
            )
            volume.classification_source = "USER"
            volume.classification_reason = "USER_OVERRIDE"
            volume.suggested_media_kind = target_media_kind
            volume.updated_at = now
            operation_store.write_prepared_operation(self._db, operation)
            operation_ids.append(str(operation.record["id"]))
        return SetVolumeMediaKindsOutcome(
            affected_volume_ids=volume_ids,
            operation_ids=tuple(operation_ids),
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
                    .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
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
            inverse={"volumes": [_classification_snapshot(row) for row in selected]},
            now=now,
        )
        for selected_volume in selected:
            selected_volume.classification_source = "USER"
            selected_volume.classification_reason = "USER_OVERRIDE"
            selected_volume.suggested_media_kind = target_media_kind
            selected_volume.updated_at = now
        operation_store.write_prepared_operation(self._db, operation)
        return VolumeReclassifyOutcome(
            moved_volume_ids=tuple(row.id for row in selected),
            operation=operation_store.operation_summary(operation.record),
        )
