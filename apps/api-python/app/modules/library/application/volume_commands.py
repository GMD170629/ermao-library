"""Application use cases for volume metadata and content classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NotRequired, Protocol, TypedDict, cast


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
    version_id: str
    media_kind: str
    sort_order: int


class VolumeMetadataChanges(TypedDict):
    description: NotRequired[str | None]
    publisher: NotRequired[str | None]
    published_at: NotRequired[datetime | None]
    language: NotRequired[str | None]
    identifier: NotRequired[str | None]
    isbn: NotRequired[str | None]
    narrator: NotRequired[str | None]
    abridged: NotRequired[bool | None]


@dataclass(frozen=True, slots=True)
class OperationSummary:
    id: str
    action: str
    status: str
    summary: str
    expires_at: datetime
    undo_available: bool


@dataclass(frozen=True, slots=True)
class VolumeReclassifyOutcome:
    moved_volume_ids: tuple[str, ...]
    operation: OperationSummary


@dataclass(frozen=True, slots=True)
class SetVolumeMediaKindsCommand:
    volume_ids: tuple[str, ...]
    target_media_kind: str


@dataclass(frozen=True, slots=True)
class SetVolumeMediaKindsOutcome:
    affected_volume_ids: tuple[str, ...]
    operation_ids: tuple[str, ...]


class VolumeMetadataPort(Protocol):
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
        self, *, volume_id: str, changes: VolumeMetadataChanges, now: datetime
    ) -> None: ...

    def reclassify_volume(
        self,
        *,
        actor_id: str,
        work_id: str,
        volume_id: str,
        target_media_kind: str,
        apply_to: Literal["VOLUME", "SAME_MEDIA_KIND"],
        now: datetime,
    ) -> VolumeReclassifyOutcome: ...

    def set_media_kinds(
        self,
        *,
        actor_id: str,
        work_id: str,
        contexts: tuple[VolumeContext, ...],
        target_media_kind: str,
        now: datetime,
    ) -> SetVolumeMediaKindsOutcome: ...


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


def set_volume_media_kinds(
    port: VolumeMetadataPort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    work_id: str,
    command: SetVolumeMediaKindsCommand,
    now: datetime,
) -> SetVolumeMediaKindsOutcome:
    """Apply one content-classification override to explicit directory volumes."""
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
    contexts.sort(key=lambda value: (value.version_id, value.sort_order, value.id))

    target_media_kind = command.target_media_kind.strip().upper()
    if target_media_kind not in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        raise InvalidVolumeChangeError("INVALID_MEDIA_KIND")

    try:
        outcome = port.set_media_kinds(
            actor_id=actor.user_id,
            work_id=work_id,
            contexts=tuple(contexts),
            target_media_kind=target_media_kind,
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
    port: VolumeMetadataPort,
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
    if apply_to not in {"VOLUME", "SAME_MEDIA_KIND"}:
        raise InvalidVolumeChangeError("INVALID_RECLASSIFY_SCOPE")
    apply_to_scope = cast(Literal["VOLUME", "SAME_MEDIA_KIND"], apply_to)
    try:
        outcome = port.reclassify_volume(
            actor_id=actor.user_id,
            work_id=work_id,
            volume_id=volume_id,
            target_media_kind=target_media_kind,
            apply_to=apply_to_scope,
            now=now,
        )
        unit_of_work.commit()
        return outcome
    except Exception:
        unit_of_work.rollback()
        raise


def update_volume_resource(
    port: VolumeMetadataPort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    work_id: str,
    volume_id: str,
    changes: VolumeMetadataChanges,
    now: datetime,
) -> None:
    _require_work_access(port, actor=actor, work_id=work_id)
    _require_manager(actor)
    _require_volume(port, actor=actor, work_id=work_id, volume_id=volume_id)
    try:
        port.update_volume(volume_id=volume_id, changes=changes, now=now)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise


def _require_manager(actor: LibraryActor) -> None:
    if not actor.can_manage_system:
        raise LibraryAuthorizationError


def _require_work_access(
    port: VolumeMetadataPort, *, actor: LibraryActor, work_id: str
) -> None:
    if not port.can_access_work(actor=actor, work_id=work_id):
        raise WorkNotFoundError


def _require_volume(
    port: VolumeMetadataPort,
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
