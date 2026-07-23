from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.auth import User


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
        rows = db.execute(
            text(
                "SELECT `monitorFolderId` FROM `UserMonitorFolderAccess` "
                "WHERE `userId` = :user_id ORDER BY `monitorFolderId`"
            ),
            {"user_id": user.id},
        ).scalars()
        folder_ids = tuple(str(item) for item in rows)
    return AuthorizationContext(
        user_id=user.id,
        is_admin=is_admin(user),
        can_manage_system=can_manage_system(user),
        can_view_manual_imports=bool(user.can_view_manual_imports),
        monitor_folder_ids=folder_ids,
        authz_version=int(user.authz_version or 1),
    )


def _folder_scope_sql(
    context: AuthorizationContext,
    expression: str,
    *,
    prefix: str,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if context.monitor_folder_ids:
        placeholders: list[str] = []
        for index, folder_id in enumerate(context.monitor_folder_ids):
            key = f"{prefix}_folder_{index}"
            placeholders.append(f":{key}")
            params[key] = folder_id
        clauses.append(f"{expression} IN ({', '.join(placeholders)})")
    if context.can_view_manual_imports:
        clauses.append(f"{expression} IS NULL")
    return (f"({' OR '.join(clauses)})" if clauses else "0 = 1"), params


def monitor_folder_visibility_sql(
    context: AuthorizationContext,
    expression: str,
    *,
    prefix: str = "access",
) -> tuple[str, dict[str, Any]]:
    if context.is_admin:
        return "1 = 1", {}
    return _folder_scope_sql(context, expression, prefix=prefix)


def work_visibility_sql(
    context: AuthorizationContext,
    *,
    alias: str = "LibraryWork",
    prefix: str = "access",
) -> tuple[str, dict[str, Any]]:
    if context.is_admin:
        return "1 = 1", {}
    edition_scope, params = _folder_scope_sql(
        context,
        "access_edition.`monitorFolderId`",
        prefix=f"{prefix}_edition",
    )
    work_scope, work_params = _folder_scope_sql(
        context,
        f"`{alias}`.`monitorFolderId`",
        prefix=f"{prefix}_work",
    )
    params.update(work_params)
    sql = (
        "("
        "EXISTS ("
        "SELECT 1 FROM `LibraryEdition` access_edition "
        f"WHERE access_edition.`workId` = `{alias}`.`id` "
        "AND COALESCE(access_edition.`hidden`, 0) = 0 "
        f"AND {edition_scope}"
        ") "
        "OR ("
        "NOT EXISTS ("
        "SELECT 1 FROM `LibraryEdition` access_any_edition "
        f"WHERE access_any_edition.`workId` = `{alias}`.`id` "
        "AND COALESCE(access_any_edition.`hidden`, 0) = 0"
        ") "
        f"AND {work_scope}"
        ")"
        ")"
    )
    return sql, params


def edition_visibility_sql(
    context: AuthorizationContext,
    *,
    alias: str = "LibraryEdition",
    prefix: str = "access",
) -> tuple[str, dict[str, Any]]:
    if context.is_admin:
        return "1 = 1", {}
    return _folder_scope_sql(
        context,
        f"`{alias}`.`monitorFolderId`",
        prefix=f"{prefix}_edition",
    )


def can_access_monitor_folder(db: Session, user: User, monitor_folder_id: str | None) -> bool:
    if is_admin(user):
        return True
    if monitor_folder_id is None:
        return bool(user.can_view_manual_imports)
    return db.execute(
        text(
            "SELECT 1 FROM `UserMonitorFolderAccess` "
            "WHERE `userId` = :user_id AND `monitorFolderId` = :folder_id LIMIT 1"
        ),
        {"user_id": user.id, "folder_id": monitor_folder_id},
    ).first() is not None


def can_access_work(db: Session, user: User, work_id: str) -> bool:
    context = authorization_context(db, user)
    predicate, params = work_visibility_sql(context, alias="w", prefix="work_check")
    params["work_id"] = work_id
    return db.execute(
        text(f"SELECT 1 FROM `LibraryWork` w WHERE w.`id` = :work_id AND {predicate} LIMIT 1"),
        params,
    ).first() is not None


def can_access_edition(db: Session, user: User, edition_id: str) -> bool:
    context = authorization_context(db, user)
    predicate, params = edition_visibility_sql(context, alias="e", prefix="edition_check")
    params["edition_id"] = edition_id
    return db.execute(
        text(
            f"SELECT 1 FROM `LibraryEdition` e WHERE e.`id` = :edition_id "
            f"AND COALESCE(e.`hidden`, 0) = 0 AND {predicate} LIMIT 1"
        ),
        params,
    ).first() is not None


def can_access_volume(db: Session, user: User, volume_id: str) -> bool:
    if is_admin(user):
        return True
    context = authorization_context(db, user)
    predicate, params = edition_visibility_sql(context, alias="e", prefix="volume_check")
    params["volume_id"] = volume_id
    return db.execute(
        text(
            "SELECT 1 FROM `LibraryVolume` v "
            "JOIN `LibraryEdition` e ON e.`id` = v.`editionId` "
            f"WHERE v.`id` = :volume_id AND COALESCE(e.`hidden`, 0) = 0 AND {predicate} LIMIT 1"
        ),
        params,
    ).first() is not None


def can_access_file(db: Session, user: User, file_id: str) -> bool:
    if is_admin(user):
        return True
    context = authorization_context(db, user)
    predicate, params = edition_visibility_sql(context, alias="e", prefix="file_check")
    params["file_id"] = file_id
    return db.execute(
        text(
            "SELECT 1 FROM `LibraryFile` f "
            "JOIN `LibraryEdition` e ON e.`id` = f.`editionId` "
            f"WHERE f.`id` = :file_id AND COALESCE(e.`hidden`, 0) = 0 AND {predicate} LIMIT 1"
        ),
        params,
    ).first() is not None


def read_user_preferences(db: Session, user_id: str) -> dict[str, Any]:
    rows = db.execute(
        text("SELECT `key`, `value` FROM `UserPreference` WHERE `userId` = :user_id"),
        {"user_id": user_id},
    ).mappings()
    preferences: dict[str, Any] = {}
    for row in rows:
        raw = row["value"]
        try:
            preferences[str(row["key"])] = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            preferences[str(row["key"])] = raw
    return preferences


def write_user_preference(db: Session, user_id: str, key: str, value: object) -> None:
    db.execute(
        text(
            "INSERT INTO `UserPreference` (`userId`, `key`, `value`, `createdAt`, `updatedAt`) "
            "VALUES (:user_id, :key, :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (`userId`, `key`) DO UPDATE SET "
            "`value` = excluded.`value`, `updatedAt` = excluded.`updatedAt`"
        ),
        {
            "user_id": user_id,
            "key": key,
            "value": json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        },
    )
