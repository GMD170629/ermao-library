from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, false, or_, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from app.models.auth import User, UserMonitorFolderAccess, UserPreference
from app.models.library import LibraryEdition, LibraryFile, LibraryVolume, LibraryWork


ADMIN_ROLE = "admin"
MEMBER_ROLE = "member"
ACTIVE_STATUS = "active"


@dataclass(frozen=True)
class AuthorizationContext:
    user_id: str
    is_admin: bool
    can_manage_system: bool
    can_view_manual_imports: bool
    monitor_folder_ids: tuple[str, ...]
    authz_version: int

    def to_view(self) -> dict[str, Any]:
        return {
            "isAdmin": self.is_admin,
            "canManageSystem": self.can_manage_system,
            "allLibraryScopes": self.is_admin,
            "monitorFolderIds": list(self.monitor_folder_ids),
            "canViewManualImports": self.is_admin or self.can_view_manual_imports,
            "authzVersion": self.authz_version,
        }


def is_admin(user: User) -> bool:
    return user.role == ADMIN_ROLE


def can_manage_system(user: User) -> bool:
    return is_admin(user) or bool(user.can_manage_system)


def authorization_context(db: Session, user: User) -> AuthorizationContext:
    folder_ids: tuple[str, ...] = ()
    if not is_admin(user):
        rows = db.scalars(
            select(UserMonitorFolderAccess.monitor_folder_id)
            .where(UserMonitorFolderAccess.user_id == user.id)
            .order_by(UserMonitorFolderAccess.monitor_folder_id)
        )
        folder_ids = tuple(str(item) for item in rows)
    return AuthorizationContext(
        user_id=user.id,
        is_admin=is_admin(user),
        can_manage_system=can_manage_system(user),
        can_view_manual_imports=bool(user.can_view_manual_imports),
        monitor_folder_ids=folder_ids,
        authz_version=int(user.authz_version or 1),
    )


def monitor_folder_visibility_predicate(
    context: AuthorizationContext,
    monitor_folder_column: ColumnElement[str | None],
) -> ColumnElement[bool]:
    """Build a typed authorization predicate for a monitor-folder column."""

    if context.is_admin:
        return monitor_folder_column.is_(monitor_folder_column)
    clauses: list[ColumnElement[bool]] = []
    if context.monitor_folder_ids:
        clauses.append(monitor_folder_column.in_(context.monitor_folder_ids))
    if context.can_view_manual_imports:
        clauses.append(monitor_folder_column.is_(None))
    return or_(*clauses) if clauses else false()


def edition_visibility_predicate(
    context: AuthorizationContext,
    edition: type[LibraryEdition] = LibraryEdition,
) -> ColumnElement[bool]:
    if context.is_admin:
        return edition.id.is_not(None)
    return monitor_folder_visibility_predicate(context, edition.monitor_folder_id)


def work_visibility_predicate(
    context: AuthorizationContext,
    work: type[LibraryWork] = LibraryWork,
) -> ColumnElement[bool]:
    """Scope works through visible editions, falling back to the work origin."""

    if context.is_admin:
        return work.id.is_not(None)
    accessible_edition = aliased(LibraryEdition)
    any_visible_edition = aliased(LibraryEdition)
    has_accessible_edition = exists(
        select(accessible_edition.id).where(
            accessible_edition.work_id == work.id,
            accessible_edition.hidden.is_(False),
            edition_visibility_predicate(context, accessible_edition),
        )
    )
    has_any_visible_edition = exists(
        select(any_visible_edition.id).where(
            any_visible_edition.work_id == work.id,
            any_visible_edition.hidden.is_(False),
        )
    )
    return or_(
        has_accessible_edition,
        and_(
            ~has_any_visible_edition,
            monitor_folder_visibility_predicate(context, work.monitor_folder_id),
        ),
    )


def can_access_monitor_folder(db: Session, user: User, monitor_folder_id: str | None) -> bool:
    if is_admin(user):
        return True
    if monitor_folder_id is None:
        return bool(user.can_view_manual_imports)
    return db.scalar(
        select(UserMonitorFolderAccess.user_id).where(
            UserMonitorFolderAccess.user_id == user.id,
            UserMonitorFolderAccess.monitor_folder_id == monitor_folder_id,
        )
    ) is not None


def can_access_work(db: Session, user: User, work_id: str) -> bool:
    context = authorization_context(db, user)
    return db.scalar(
        select(LibraryWork.id).where(
            LibraryWork.id == work_id,
            work_visibility_predicate(context),
        )
    ) is not None


def can_access_edition(db: Session, user: User, edition_id: str) -> bool:
    context = authorization_context(db, user)
    return db.scalar(
        select(LibraryEdition.id).where(
            LibraryEdition.id == edition_id,
            LibraryEdition.hidden.is_(False),
            edition_visibility_predicate(context),
        )
    ) is not None


def can_access_volume(db: Session, user: User, volume_id: str) -> bool:
    if is_admin(user):
        return True
    context = authorization_context(db, user)
    return db.scalar(
        select(LibraryVolume.id)
        .join(LibraryEdition, LibraryEdition.id == LibraryVolume.edition_id)
        .where(
            LibraryVolume.id == volume_id,
            LibraryEdition.hidden.is_(False),
            edition_visibility_predicate(context),
        )
    ) is not None


def can_access_file(db: Session, user: User, file_id: str) -> bool:
    if is_admin(user):
        return True
    context = authorization_context(db, user)
    return db.scalar(
        select(LibraryFile.id)
        .join(LibraryEdition, LibraryEdition.id == LibraryFile.edition_id)
        .where(
            LibraryFile.id == file_id,
            LibraryEdition.hidden.is_(False),
            edition_visibility_predicate(context),
        )
    ) is not None


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


def write_user_preference(db: Session, user_id: str, key: str, value: object) -> None:
    db.execute(
        sqlite_insert(UserPreference)
        .values(
            user_id=user_id,
            key=key,
            value=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
        .on_conflict_do_update(
            index_elements=[UserPreference.user_id, UserPreference.key],
            set_={"value": json.dumps(value, ensure_ascii=False, separators=(",", ":"))},
        )
    )
