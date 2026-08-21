from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import ColumnElement, exists, false, select, true
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from app.models.auth import User, UserLibraryAccess, UserPreference
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)

ADMIN_ROLE = "admin"
MEMBER_ROLE = "member"
ACTIVE_STATUS = "active"


@dataclass(frozen=True)
class AuthorizationContext:
    user_id: str
    is_admin: bool
    can_manage_system: bool
    can_view_manual_imports: bool
    library_ids: tuple[str, ...]
    authz_version: int

    def to_view(self) -> dict[str, Any]:
        return {
            "isAdmin": self.is_admin,
            "canManageSystem": self.can_manage_system,
            "allLibraryScopes": self.is_admin,
            "libraryIds": list(self.library_ids),
            "canViewManualImports": self.is_admin or self.can_view_manual_imports,
            "authzVersion": self.authz_version,
        }


def is_admin(user: User) -> bool:
    return user.role == ADMIN_ROLE


def can_manage_system(user: User) -> bool:
    return is_admin(user) or bool(user.can_manage_system)


def authorization_context(db: Session, user: User) -> AuthorizationContext:
    library_ids: tuple[str, ...] = ()
    if not is_admin(user):
        rows = db.scalars(
            select(UserLibraryAccess.library_id)
            .where(UserLibraryAccess.user_id == user.id)
            .order_by(UserLibraryAccess.library_id)
        )
        library_ids = tuple(str(item) for item in rows)
    return AuthorizationContext(
        user_id=user.id,
        is_admin=is_admin(user),
        can_manage_system=can_manage_system(user),
        can_view_manual_imports=bool(user.can_view_manual_imports),
        library_ids=library_ids,
        authz_version=int(user.authz_version or 1),
    )


def library_visibility_predicate(
    context: AuthorizationContext,
    library_column: ColumnElement[str],
) -> ColumnElement[bool]:
    if context.is_admin:
        return true()
    if not context.library_ids:
        return false()
    return library_column.in_(context.library_ids)


def book_visibility_predicate(
    context: AuthorizationContext,
    book: type[LibraryBook] = LibraryBook,
) -> ColumnElement[bool]:
    if context.is_admin:
        return book.id.is_not(None)
    return library_visibility_predicate(
        context, cast(ColumnElement[str], book.library_id)
    )


def resource_visibility_predicate(
    context: AuthorizationContext,
    resource: type[LibraryReadableResource] = LibraryReadableResource,
) -> ColumnElement[bool]:
    state = (
        resource.enablement_state == "ENABLED",
        resource.import_state == "READY",
    )
    if context.is_admin:
        return resource.id.is_not(None) & state[0] & state[1]
    return (
        library_visibility_predicate(
            context, cast(ColumnElement[str], resource.library_id)
        )
        & state[0]
        & state[1]
    )


def asset_visibility_predicate(
    context: AuthorizationContext,
    asset: type[LibraryResourceAsset] = LibraryResourceAsset,
) -> ColumnElement[bool]:
    source_node = LibrarySourceNode
    return exists(
        select(LibraryReadableResource.id)
        .join(
            LibraryBook,
            LibraryBook.id == LibraryReadableResource.book_id,
        )
        .join(
            source_node,
            source_node.id == asset.source_node_id,
        )
        .where(
            LibraryReadableResource.id == asset.resource_id,
            asset.import_state == "READY",
            source_node.physical_kind == "REGULAR_FILE",
            resource_visibility_predicate(context),
        )
    )


def can_access_library(db: Session, user: User, library_id: str | None) -> bool:
    if is_admin(user):
        return True
    if not library_id:
        return False
    return (
        db.scalar(
            select(UserLibraryAccess.user_id).where(
                UserLibraryAccess.user_id == user.id,
                UserLibraryAccess.library_id == library_id,
            )
        )
        is not None
    )


def can_access_book(db: Session, user: User, book_id: str) -> bool:
    context = authorization_context(db, user)
    return (
        db.scalar(
            select(LibraryBook.id).where(
                LibraryBook.id == book_id,
                book_visibility_predicate(context),
            )
        )
        is not None
    )


def can_access_resource(db: Session, user: User, resource_id: str) -> bool:
    context = authorization_context(db, user)
    return (
        db.scalar(
            select(LibraryReadableResource.id).where(
                LibraryReadableResource.id == resource_id,
                resource_visibility_predicate(context),
            )
        )
        is not None
    )


def can_access_asset(db: Session, user: User, asset_id: str) -> bool:
    context = authorization_context(db, user)
    return (
        db.scalar(
            select(LibraryResourceAsset.id).where(
                LibraryResourceAsset.id == asset_id,
                asset_visibility_predicate(context, LibraryResourceAsset),
            )
        )
        is not None
    )


def read_user_preferences(db: Session, user_id: str) -> dict[str, Any]:
    rows = db.execute(
        select(UserPreference.key, UserPreference.value).where(
            UserPreference.user_id == user_id
        )
    ).all()
    preferences: dict[str, Any] = {}
    for row in rows:
        raw = row.value
        try:
            preferences[str(row.key)] = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            preferences[str(row.key)] = raw
    return preferences


def prepare_user_preference_write(
    user_id: str,
    key: str,
    value: object,
) -> Insert:
    encoded_value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    statement = sqlite_insert(UserPreference)
    return statement.values(
        user_id=user_id,
        key=key,
        value=encoded_value,
    ).on_conflict_do_update(
        index_elements=[UserPreference.user_id, UserPreference.key],
        set_={"value": encoded_value},
    )


def write_prepared_user_preference(db: Session, statement: Insert) -> None:
    db.execute(statement)


def write_user_preference(db: Session, user_id: str, key: str, value: object) -> None:
    write_prepared_user_preference(
        db,
        prepare_user_preference_write(user_id, key, value),
    )
