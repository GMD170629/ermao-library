"""SQLAlchemy adapter for Auth user-administration use cases."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bootstrap.system import prepare_system_event
from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import User, cuid, db_timestamp
from app.modules.auth.application.user_management import (
    AdminUserView,
    Locale,
    PreparedUserCreate,
    PreparedUserUpdate,
    UserAdministrationError,
    UserAuthorizationView,
    UserRole,
    UserStatus,
)
from app.modules.auth.infrastructure.transactions import (
    persist_admin_password_reset,
    persist_admin_user_create,
    persist_admin_user_delete,
    persist_admin_user_update,
    validate_library_ids,
)
from app.modules.auth.infrastructure.user_management_queries import (
    active_admin_count,
    email_in_use,
    get_user,
    list_users,
    user_view,
)


def _view(db: Session, user: User) -> AdminUserView:
    record = user_view(db, user)
    authorization = record["authorization"]
    if not isinstance(authorization, dict):
        raise TypeError("invalid authorization projection")
    return AdminUserView(
        id=str(record["id"]),
        email=str(record["email"]),
        name=str(record["name"]),
        role=cast(UserRole, str(record["role"])),
        status=cast(UserStatus, str(record["status"])),
        can_manage_system=bool(record["canManageSystem"]),
        can_view_manual_imports=bool(record["canViewManualImports"]),
        authz_version=int(record["authzVersion"]),
        avatar_url=(
            str(record["avatarUrl"]) if record.get("avatarUrl") is not None else None
        ),
        locale=cast(Locale, str(record["locale"])),
        library_ids=tuple(str(value) for value in record["libraryIds"]),
        authorization=UserAuthorizationView(
            is_admin=bool(authorization["isAdmin"]),
            can_manage_system=bool(authorization["canManageSystem"]),
            all_library_scopes=bool(authorization["allLibraryScopes"]),
            library_ids=tuple(str(value) for value in authorization["libraryIds"]),
            can_view_manual_imports=bool(authorization["canViewManualImports"]),
            authz_version=int(authorization["authzVersion"]),
        ),
        created_at=cast(datetime, record["createdAt"]),
        updated_at=cast(datetime, record["updatedAt"]),
    )


class SqlAlchemyUserAdministrationGateway:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def list_users(self) -> tuple[AdminUserView, ...]:
        return tuple(_view(self._db, user) for user in list_users(self._db))

    def get_user(self, user_id: str) -> AdminUserView | None:
        user = get_user(self._db, user_id)
        return _view(self._db, user) if user is not None else None

    def email_in_use(self, email: str, excluding_user_id: str | None = None) -> bool:
        return email_in_use(self._db, email, excluding_user_id=excluding_user_id)

    def active_admin_count(self, excluding_user_id: str | None = None) -> int:
        return active_admin_count(self._db, excluding_user_id=excluding_user_id)

    def validate_library_ids(self, library_ids: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_library_ids(self._db, list(library_ids)))

    def new_user_id(self) -> str:
        return cuid()

    def hash_password(self, password: str) -> str:
        return hash_password(password)

    def now(self) -> datetime:
        return db_timestamp()

    def create_user(self, prepared: PreparedUserCreate) -> AdminUserView:
        user = User(
            id=prepared.user_id,
            email=prepared.email,
            name=prepared.name,
            password_hash=prepared.password_hash,
            role=prepared.role,
            status="active",
            can_manage_system=prepared.can_manage_system,
            can_view_manual_imports=prepared.can_view_manual_imports,
            authz_version=1,
        )
        event = prepare_system_event(
            source="authorization",
            action="user.created",
            message="管理员创建了用户",
            actor_type="admin",
            actor_id=prepared.actor_id,
            target_type="user",
            target_id=prepared.user_id,
            metadata={
                "role": prepared.role,
                "canManageSystem": prepared.can_manage_system,
            },
        )
        try:
            persist_admin_user_create(
                self._db,
                user=user,
                locale=prepared.locale,
                folder_ids=list(prepared.library_ids),
                prepared_at=prepared.prepared_at,
                event=event,
            )
        except IntegrityError as exc:
            raise UserAdministrationError("EMAIL_IN_USE", "该邮箱已被使用") from exc
        persisted = get_user(self._db, prepared.user_id)
        if persisted is None:
            raise RuntimeError("created user was not persisted")
        return _view(self._db, persisted)

    def update_user(self, prepared: PreparedUserUpdate) -> AdminUserView:
        event = prepare_system_event(
            source="authorization",
            action="user.authorization.updated",
            message="管理员更新了用户与权限",
            actor_type="admin",
            actor_id=prepared.actor_id,
            target_type="user",
            target_id=prepared.user_id,
            metadata={
                "role": prepared.role,
                "status": prepared.status,
                "canManageSystem": prepared.can_manage_system,
                "authzVersion": prepared.authz_version,
            },
        )
        try:
            persist_admin_user_update(
                self._db,
                user_id=prepared.user_id,
                user_values={
                    "email": prepared.email,
                    "name": prepared.name,
                    "role": prepared.role,
                    "status": prepared.status,
                    "can_manage_system": prepared.can_manage_system,
                    "can_view_manual_imports": prepared.can_view_manual_imports,
                    "authz_version": prepared.authz_version,
                    "updated_at": prepared.updated_at,
                },
                folder_ids=(
                    list(prepared.library_ids)
                    if prepared.library_ids is not None
                    else None
                ),
                locale=prepared.locale,
                updated_at=prepared.updated_at,
                disable_sessions=prepared.disable_sessions,
                event=event,
            )
        except IntegrityError as exc:
            raise UserAdministrationError("EMAIL_IN_USE", "该邮箱已被使用") from exc
        persisted = get_user(self._db, prepared.user_id)
        if persisted is None:
            raise RuntimeError("updated user was not persisted")
        self._db.refresh(persisted)
        return _view(self._db, persisted)

    def reset_password(
        self, *, user_id: str, password_hash: str, updated_at: datetime, actor_id: str
    ) -> None:
        event = prepare_system_event(
            source="authorization",
            action="user.password.reset",
            message="管理员重置了用户密码并撤销会话",
            actor_type="admin",
            actor_id=actor_id,
            target_type="user",
            target_id=user_id,
        )
        persist_admin_password_reset(
            self._db,
            user_id=user_id,
            password_hash=password_hash,
            updated_at=updated_at,
            event=event,
        )

    def delete_user(
        self, *, user_id: str, anonymous_user_id: str, actor_id: str
    ) -> None:
        user = get_user(self._db, user_id)
        if user is None:
            raise UserAdministrationError("USER_NOT_FOUND", "用户不存在")
        avatar_path = None
        if user.avatar_path:
            candidate = (
                self._settings.resolved_storage_root / user.avatar_path
            ).resolve()
            try:
                candidate.relative_to(self._settings.resolved_storage_root)
                avatar_path = candidate
            except ValueError:
                pass
        event = prepare_system_event(
            source="authorization",
            action="user.deleted",
            message="管理员永久删除了用户及其个人数据",
            actor_type="admin",
            actor_id=actor_id,
            target_type="user",
            target_id=anonymous_user_id,
            metadata={"formerRole": user.role, "deidentified": True},
        )
        persist_admin_user_delete(
            self._db,
            user_id=user_id,
            anonymous_user_id=anonymous_user_id,
            event=event,
        )
        if avatar_path is not None:
            avatar_path.unlink(missing_ok=True)
            try:
                avatar_path.parent.rmdir()
            except OSError:
                pass
