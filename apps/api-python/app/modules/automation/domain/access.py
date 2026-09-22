"""Fixed grants, intersected with current user and deployment permissions."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Scope(StrEnum):
    SYSTEM_READ = "system:read"
    SYSTEM_MANAGE = "system:manage"
    BOOKS_WRITE = "books:write"
    SHELVES_WRITE = "shelves:write"
    FILES_UPLOAD = "files:upload"
    FILES_MODIFY = "files:modify"


class WritebackTarget(StrEnum):
    SIDECAR = "sidecar"
    EMBEDDED = "embedded"


MEMBER_SCOPES = frozenset({Scope.SYSTEM_READ, Scope.SHELVES_WRITE})
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
    library_scope: Literal["all", "selected"] = "selected"


def validate_permissions(permissions: GrantPermissions, actor: AutomationActor) -> None:
    if not actor.active:
        raise AutomationAccessError("UNAUTHORIZED")
    if not permissions.scopes <= ALL_SCOPES:
        raise AutomationAccessError("INVALID_SCOPES")
    if Scope.SYSTEM_READ not in permissions.scopes:
        raise AutomationAccessError("SYSTEM_READ_REQUIRED")
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


@dataclass(frozen=True, slots=True)
class EffectiveAccess:
    grant_id: str
    user_id: str
    permissions: GrantPermissions
    can_manage_system: bool = False
    is_admin: bool = False

    def require(
        self, *scopes: Scope, library_ids: frozenset[str] = frozenset()
    ) -> None:
        if not set(scopes) <= self.permissions.scopes:
            raise AutomationAccessError("SCOPE_REQUIRED")
        if not library_ids <= self.permissions.library_ids:
            raise AutomationAccessError("RESOURCE_NOT_FOUND")

    def require_move(self, source_library: str, target_library: str) -> None:
        self.require(
            Scope.SYSTEM_READ,
            Scope.FILES_MODIFY,
            library_ids=frozenset({source_library, target_library}),
        )

    def require_writeback(self, target: WritebackTarget, library_id: str) -> None:
        self.require(
            Scope.SYSTEM_READ,
            Scope.FILES_MODIFY,
            library_ids=frozenset({library_id}),
        )

    def require_metadata(
        self, *, changes_tags: bool, overrides_protection: bool
    ) -> None:
        self.require(Scope.BOOKS_WRITE)


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
    if Scope.SYSTEM_READ not in scopes:
        raise AutomationAccessError("SCOPE_REQUIRED")
    return EffectiveAccess(
        grant_id=grant_id,
        user_id=user_id,
        can_manage_system=actor.can_manage_system,
        is_admin=actor.is_admin,
        permissions=GrantPermissions(
            scopes=scopes,
            library_ids=actor.library_ids
            if permissions.library_scope == "all"
            else permissions.library_ids & actor.library_ids,
        ),
    )
