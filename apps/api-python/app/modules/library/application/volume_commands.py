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
    monitor_folder_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VolumeContext:
    id: str
    work_id: str
    media_version_id: str
    media_kind: str
    title: str
    format: str
    monitor_folder_id: str | None
    author: str | None
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


class VolumeStructurePort(Protocol):
    def can_access_work(self, *, actor: LibraryActor, work_id: str) -> bool: ...

    def get_volume_context(
        self, *, actor: LibraryActor, work_id: str, volume_id: str
    ) -> VolumeContext | None: ...

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

    def queue_epub_conversion(
        self, *, context: VolumeContext, now: datetime
    ) -> tuple[object, bool]: ...


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


class VolumeConversionUnsupportedError(Exception):
    pass


class VolumeSourceMissingError(Exception):
    pass


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


def queue_volume_epub_conversion(
    port: VolumeStructurePort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    work_id: str,
    volume_id: str,
    now: datetime,
) -> tuple[object, bool]:
    _require_work_access(port, actor=actor, work_id=work_id)
    _require_manager(actor)
    context = _require_volume(
        port,
        actor=actor,
        work_id=work_id,
        volume_id=volume_id,
    )
    if context.format.lower() not in {"txt", "mobi", "azw", "azw3", "prc", "fb2"}:
        raise VolumeConversionUnsupportedError
    if context.source_path is None or not context.source_path.is_file():
        raise VolumeSourceMissingError
    try:
        result = port.queue_epub_conversion(context=context, now=now)
        unit_of_work.commit()
        return result
    except Exception:
        unit_of_work.rollback()
        raise
