"""Application use cases for authorized volume-scoped structure changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from app.modules.library.application.dto import MoveVolumeResult


@dataclass(frozen=True, slots=True)
class LibraryActor:
    user_id: str
    can_manage_system: bool
    is_admin: bool
    can_view_manual_imports: bool
    library_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VolumeContext:
    id: str
    work_id: str
    media_version_id: str
    media_kind: str
    title: str
    sort_order: int
    format: str
    library_id: str | None
    author: str | None
    work_title: str
    source_path: Path | None


@dataclass(frozen=True, slots=True)
class NewWorkInput:
    title: str
    author: str | None


@dataclass(frozen=True, slots=True)
class OperationSummary:
    id: str
    action: str
    status: str
    summary: str
    expires_at: datetime
    undo_available: bool


@dataclass(frozen=True, slots=True)
class VolumeMoveOutcome:
    move: MoveVolumeResult
    operation: OperationSummary


@dataclass(frozen=True, slots=True)
class VolumeSplitOutcome:
    target_work_id: str
    move: MoveVolumeResult
    operation: OperationSummary


@dataclass(frozen=True, slots=True)
class VolumeDeleteOutcome:
    work_id: str
    volume_id: str
    deleted_media_version: bool
    deleted_work: bool
    operation: OperationSummary


@dataclass(frozen=True, slots=True)
class VolumeReclassifyOutcome:
    target_media_version_id: str
    moved_volume_ids: tuple[str, ...]
    operation: OperationSummary


BatchVolumeAction = Literal["SET_MEDIA_KIND", "SPLIT", "TRANSFER", "DELETE"]


@dataclass(frozen=True, slots=True)
class BatchVolumeCommand:
    action: BatchVolumeAction
    volume_ids: tuple[str, ...]
    target_media_kind: str | None = None
    target_work_id: str | None = None


@dataclass(frozen=True, slots=True)
class BatchVolumeOutcome:
    work_id: str
    affected_volume_ids: tuple[str, ...]
    target_work_ids: tuple[str, ...]
    operation_ids: tuple[str, ...]
    deleted_work: bool


class VolumeStructurePort(Protocol):
    def can_access_work(self, *, actor: LibraryActor, work_id: str) -> bool: ...

    def get_volume_context(
        self, *, actor: LibraryActor, work_id: str, volume_id: str
    ) -> VolumeContext | None: ...

    def get_volume_contexts(
        self,
        *,
        actor: LibraryActor,
        work_id: str,
        volume_ids: tuple[str, ...],
    ) -> tuple[VolumeContext, ...]: ...

    def update_volume(
        self, *, volume_id: str, changes: dict[str, object], now: datetime
    ) -> None: ...

    def move_volume(
        self,
        *,
        actor_id: str,
        source_work_id: str,
        volume_id: str,
        target_work_id: str,
        now: datetime,
    ) -> VolumeMoveOutcome: ...

    def reorder_volume(
        self,
        *,
        volume_id: str,
        media_version_id: str,
        direction: Literal["up", "down"],
        now: datetime,
    ) -> bool: ...

    def split_volume(
        self,
        *,
        actor_id: str,
        source_work_id: str,
        volume_id: str,
        new_work: NewWorkInput,
        now: datetime,
    ) -> VolumeSplitOutcome: ...

    def delete_volume(
        self,
        *,
        actor_id: str,
        work_id: str,
        volume_id: str,
        now: datetime,
    ) -> VolumeDeleteOutcome: ...

    def reclassify_volume(
        self,
        *,
        actor_id: str,
        work_id: str,
        volume_id: str,
        target_media_kind: str,
        apply_to: Literal["VOLUME", "MEDIA_VERSION"],
        now: datetime,
    ) -> VolumeReclassifyOutcome: ...

    def apply_batch(
        self,
        *,
        actor_id: str,
        source_work_id: str,
        contexts: tuple[VolumeContext, ...],
        command: BatchVolumeCommand,
        now: datetime,
    ) -> BatchVolumeOutcome: ...


class UnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class VolumeNotFoundError(Exception):
    pass


class WorkNotFoundError(Exception):
    pass


class LibraryAuthorizationError(Exception):
    pass


class InvalidVolumeChangeError(Exception):
    pass


def batch_volume_resources(
    port: VolumeStructurePort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    work_id: str,
    command: BatchVolumeCommand,
    now: datetime,
) -> BatchVolumeOutcome:
    """Apply one volume-management intention atomically to an explicit selection."""
    _require_work_access(port, actor=actor, work_id=work_id)
    _require_manager(actor)
    if not command.volume_ids:
        raise InvalidVolumeChangeError("VOLUME_SELECTION_REQUIRED")
    if len(set(command.volume_ids)) != len(command.volume_ids):
        raise InvalidVolumeChangeError("DUPLICATE_VOLUME_IDS")

    contexts = list(
        port.get_volume_contexts(
            actor=actor,
            work_id=work_id,
            volume_ids=command.volume_ids,
        )
    )
    if {context.id for context in contexts} != set(command.volume_ids):
        raise VolumeNotFoundError
    contexts.sort(
        key=lambda value: (value.media_version_id, value.sort_order, value.id)
    )

    target_media_kind = (command.target_media_kind or "").strip().upper()
    target_work_id = (command.target_work_id or "").strip()
    if command.action == "SET_MEDIA_KIND" and target_media_kind not in {
        "EBOOK",
        "COMIC",
        "AUDIOBOOK",
    }:
        raise InvalidVolumeChangeError("INVALID_MEDIA_KIND")
    if command.action == "TRANSFER":
        if not target_work_id or target_work_id == work_id:
            raise InvalidVolumeChangeError("INVALID_TARGET_WORK")
        _require_work_access(port, actor=actor, work_id=target_work_id)

    try:
        outcome = port.apply_batch(
            actor_id=actor.user_id,
            source_work_id=work_id,
            contexts=tuple(contexts),
            command=command,
            now=now,
        )
        unit_of_work.commit()
    except ValueError as exc:
        unit_of_work.rollback()
        raise VolumeNotFoundError(str(exc)) from exc
    except Exception:
        unit_of_work.rollback()
        raise
    return outcome


def reclassify_volume_resource(
    port: VolumeStructurePort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    work_id: str,
    volume_id: str,
    target_media_kind: str,
    apply_to: str,
    now: datetime,
) -> VolumeReclassifyOutcome:
    _require_work_access(port, actor=actor, work_id=work_id)
    _require_manager(actor)
    _require_volume(port, actor=actor, work_id=work_id, volume_id=volume_id)
    if target_media_kind not in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        raise InvalidVolumeChangeError("INVALID_MEDIA_KIND")
    if apply_to not in {"VOLUME", "MEDIA_VERSION"}:
        raise InvalidVolumeChangeError("INVALID_RECLASSIFY_SCOPE")
    try:
        outcome = port.reclassify_volume(
            actor_id=actor.user_id,
            work_id=work_id,
            volume_id=volume_id,
            target_media_kind=target_media_kind,
            apply_to=apply_to,
            now=now,
        )
        unit_of_work.commit()
        return outcome
    except Exception:
        unit_of_work.rollback()
        raise


def _require_manager(actor: LibraryActor) -> None:
    if not actor.can_manage_system:
        raise LibraryAuthorizationError


def _require_work_access(
    port: VolumeStructurePort, *, actor: LibraryActor, work_id: str
) -> None:
    if not port.can_access_work(actor=actor, work_id=work_id):
        raise WorkNotFoundError


def _require_volume(
    port: VolumeStructurePort,
    *,
    actor: LibraryActor,
    work_id: str,
    volume_id: str,
) -> VolumeContext:
    context = port.get_volume_context(
        actor=actor,
        work_id=work_id,
        volume_id=volume_id,
    )
    if context is None:
        raise VolumeNotFoundError
    return context


def update_volume_resource(
    port: VolumeStructurePort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    work_id: str,
    volume_id: str,
    changes: dict[str, object],
    now: datetime,
) -> None:
    _require_work_access(port, actor=actor, work_id=work_id)
    _require_manager(actor)
    _require_volume(port, actor=actor, work_id=work_id, volume_id=volume_id)
    if "title" in changes and not str(changes["title"] or "").strip():
        raise InvalidVolumeChangeError("Volume title cannot be empty")
    try:
        port.update_volume(volume_id=volume_id, changes=changes, now=now)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise


def move_volume_resource(
    port: VolumeStructurePort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    source_work_id: str,
    volume_id: str,
    target_work_id: str,
    now: datetime,
) -> VolumeMoveOutcome:
    _require_work_access(port, actor=actor, work_id=source_work_id)
    _require_manager(actor)
    _require_volume(
        port,
        actor=actor,
        work_id=source_work_id,
        volume_id=volume_id,
    )
    _require_work_access(port, actor=actor, work_id=target_work_id)
    try:
        result = port.move_volume(
            actor_id=actor.user_id,
            source_work_id=source_work_id,
            volume_id=volume_id,
            target_work_id=target_work_id,
            now=now,
        )
        unit_of_work.commit()
        return result
    except ValueError as exc:
        unit_of_work.rollback()
        raise VolumeNotFoundError(str(exc)) from exc
    except Exception:
        unit_of_work.rollback()
        raise


def reorder_volume_resource(
    port: VolumeStructurePort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    work_id: str,
    volume_id: str,
    direction: Literal["up", "down"],
    now: datetime,
) -> bool:
    _require_work_access(port, actor=actor, work_id=work_id)
    _require_manager(actor)
    context = _require_volume(
        port,
        actor=actor,
        work_id=work_id,
        volume_id=volume_id,
    )
    try:
        changed = port.reorder_volume(
            volume_id=volume_id,
            media_version_id=context.media_version_id,
            direction=direction,
            now=now,
        )
        unit_of_work.commit()
        return changed
    except Exception:
        unit_of_work.rollback()
        raise


def split_volume_resource(
    port: VolumeStructurePort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    source_work_id: str,
    volume_id: str,
    new_work: NewWorkInput,
    now: datetime,
) -> VolumeSplitOutcome:
    _require_work_access(port, actor=actor, work_id=source_work_id)
    _require_manager(actor)
    _require_volume(
        port,
        actor=actor,
        work_id=source_work_id,
        volume_id=volume_id,
    )
    if not new_work.title.strip():
        raise InvalidVolumeChangeError("Work title cannot be empty")
    try:
        result = port.split_volume(
            actor_id=actor.user_id,
            source_work_id=source_work_id,
            volume_id=volume_id,
            new_work=new_work,
            now=now,
        )
        unit_of_work.commit()
        return result
    except Exception:
        unit_of_work.rollback()
        raise


def delete_volume_resource(
    port: VolumeStructurePort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    work_id: str,
    volume_id: str,
    now: datetime,
) -> VolumeDeleteOutcome:
    _require_work_access(port, actor=actor, work_id=work_id)
    _require_manager(actor)
    _require_volume(port, actor=actor, work_id=work_id, volume_id=volume_id)
    try:
        result = port.delete_volume(
            actor_id=actor.user_id,
            work_id=work_id,
            volume_id=volume_id,
            now=now,
        )
        unit_of_work.commit()
        return result
    except Exception:
        unit_of_work.rollback()
        raise
