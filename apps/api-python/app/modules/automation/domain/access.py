"""Fixed grants, intersected with current user and deployment permissions."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Scope(StrEnum):
    LIBRARY_READ = "library:read"
    SHELVES_WRITE = "shelves:write"
    TAGS_WRITE = "tags:write"
    FILES_READ = "files:read"
    FILES_MOVE = "files:move"
    METADATA_WRITE = "metadata:write"
    METADATA_OVERRIDE = "metadata:override"
    METADATA_WRITEBACK = "metadata:writeback"


class WritebackTarget(StrEnum):
    SIDECAR = "sidecar"
    EMBEDDED = "embedded"


MEMBER_SCOPES = frozenset({Scope.LIBRARY_READ, Scope.SHELVES_WRITE})
ALL_SCOPES = frozenset(Scope)


class AutomationAccessError(ValueError):
    """A language-neutral rejection; no target data or secrets in the error."""


@dataclass(frozen=True, slots=True)
class AutomationActor:
    user_id: str
    active: bool
    can_manage_system: bool
    # Contains existing, currently accessible IDs, including for administrators.
    library_ids: frozenset[str]
    is_admin: bool = False


@dataclass(frozen=True, slots=True)
class GrantPermissions:
    scopes: frozenset[Scope]
    library_ids: frozenset[str]
    writeback_targets: frozenset[WritebackTarget] = frozenset()
    allow_cross_library: bool = False
    library_scope: Literal["all", "selected"] = "selected"


def validate_permissions(permissions: GrantPermissions, actor: AutomationActor) -> None:
    if not actor.active:
        raise AutomationAccessError("UNAUTHORIZED")
    if not permissions.scopes <= ALL_SCOPES:
        raise AutomationAccessError("INVALID_SCOPES")
    if Scope.LIBRARY_READ not in permissions.scopes:
        raise AutomationAccessError("LIBRARY_READ_REQUIRED")
    if not actor.can_manage_system and not permissions.scopes <= MEMBER_SCOPES:
        raise AutomationAccessError("SYSTEM_MANAGER_REQUIRED")
    if permissions.library_scope not in {"all", "selected"}:
        raise AutomationAccessError("INVALID_LIBRARY_SCOPE")
    if permissions.library_scope == "all":
        if permissions.library_ids:
            raise AutomationAccessError("INVALID_LIBRARY_SCOPE")
    elif (
        not permissions.library_ids or not permissions.library_ids <= actor.library_ids
    ):
        raise AutomationAccessError("LIBRARY_NOT_FOUND")
    if (
        permissions.scopes & {Scope.FILES_MOVE, Scope.METADATA_WRITEBACK}
        and Scope.FILES_READ not in permissions.scopes
    ):
        raise AutomationAccessError("FILES_READ_REQUIRED")
    if Scope.METADATA_OVERRIDE in permissions.scopes and not permissions.scopes & {
        Scope.METADATA_WRITE,
        Scope.TAGS_WRITE,
    }:
        raise AutomationAccessError("METADATA_WRITE_REQUIRED")
    if not permissions.writeback_targets <= frozenset(WritebackTarget):
        raise AutomationAccessError("INVALID_WRITEBACK_TARGET")
    if bool(permissions.writeback_targets) != (
        Scope.METADATA_WRITEBACK in permissions.scopes
    ):
        raise AutomationAccessError("WRITEBACK_TARGET_REQUIRED")
    if permissions.allow_cross_library and Scope.FILES_MOVE not in permissions.scopes:
        raise AutomationAccessError("FILES_MOVE_REQUIRED")


@dataclass(frozen=True, slots=True)
class EffectiveAccess:
    grant_id: str
    user_id: str
    permissions: GrantPermissions

    def require(
        self, *scopes: Scope, library_ids: frozenset[str] = frozenset()
    ) -> None:
        if not set(scopes) <= self.permissions.scopes:
            raise AutomationAccessError("SCOPE_REQUIRED")
        if not library_ids <= self.permissions.library_ids:
            raise AutomationAccessError("RESOURCE_NOT_FOUND")

    def require_move(self, source_library: str, target_library: str) -> None:
        self.require(
            Scope.FILES_READ,
            Scope.FILES_MOVE,
            library_ids=frozenset({source_library, target_library}),
        )
        if (
            source_library != target_library
            and not self.permissions.allow_cross_library
        ):
            raise AutomationAccessError("CROSS_LIBRARY_NOT_ALLOWED")

    def require_writeback(self, target: WritebackTarget, library_id: str) -> None:
        self.require(
            Scope.FILES_READ,
            Scope.METADATA_WRITEBACK,
            library_ids=frozenset({library_id}),
        )
        if target not in self.permissions.writeback_targets:
            raise AutomationAccessError("WRITEBACK_TARGET_NOT_ALLOWED")

    def require_metadata(
        self, *, changes_tags: bool, overrides_protection: bool
    ) -> None:
        self.require(Scope.METADATA_WRITE)
        if changes_tags:
            self.require(Scope.TAGS_WRITE)
        if overrides_protection:
            self.require(Scope.METADATA_OVERRIDE)


def effective_access(
    *,
    grant_id: str,
    user_id: str,
    permissions: GrantPermissions,
    actor: AutomationActor,
    enabled_scopes: frozenset[Scope],
) -> EffectiveAccess:
    if not actor.active or actor.user_id != user_id:
        raise AutomationAccessError("UNAUTHORIZED")
    allowed = ALL_SCOPES if actor.can_manage_system else MEMBER_SCOPES
    scopes = permissions.scopes & allowed & enabled_scopes
    if Scope.LIBRARY_READ not in scopes:
        raise AutomationAccessError("SCOPE_REQUIRED")
    if Scope.FILES_READ not in scopes:
        scopes = scopes - {Scope.FILES_MOVE, Scope.METADATA_WRITEBACK}
    if not scopes & {Scope.METADATA_WRITE, Scope.TAGS_WRITE}:
        scopes = scopes - {Scope.METADATA_OVERRIDE}
    return EffectiveAccess(
        grant_id=grant_id,
        user_id=user_id,
        permissions=GrantPermissions(
            scopes=scopes,
            library_ids=actor.library_ids
            if permissions.library_scope == "all"
            else permissions.library_ids & actor.library_ids,
            writeback_targets=permissions.writeback_targets
            if Scope.METADATA_WRITEBACK in scopes
            else frozenset(),
            allow_cross_library=permissions.allow_cross_library
            and Scope.FILES_MOVE in scopes,
        ),
    )
