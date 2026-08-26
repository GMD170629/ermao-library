"""User-administration use cases independent of HTTP and SQLAlchemy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

UserRole = Literal["admin", "member"]
UserStatus = Literal["active", "disabled"]
Locale = Literal["zh-CN", "en-US"]


class UserAdministrationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class UserAdministrationActor:
    id: str
    role: str


@dataclass(frozen=True, slots=True)
class UserAuthorizationView:
    is_admin: bool
    can_manage_system: bool
    all_library_scopes: bool
    library_ids: tuple[str, ...]
    can_view_manual_imports: bool
    authz_version: int


@dataclass(frozen=True, slots=True)
class AdminUserView:
    id: str
    email: str
    name: str
    role: UserRole
    status: UserStatus
    can_manage_system: bool
    can_view_manual_imports: bool
    authz_version: int
    avatar_url: str | None
    locale: Locale
    library_ids: tuple[str, ...]
    authorization: UserAuthorizationView
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CreateUserCommand:
    name: str
    email: str
    password: str
    role: UserRole
    can_manage_system: bool
    can_view_manual_imports: bool
    library_ids: tuple[str, ...]
    locale: Locale


@dataclass(frozen=True, slots=True)
class UpdateUserCommand:
    user_id: str
    changed_fields: frozenset[str]
    name: str | None = None
    email: str | None = None
    role: UserRole | None = None
    status: UserStatus | None = None
    can_manage_system: bool | None = None
    can_view_manual_imports: bool | None = None
    library_ids: tuple[str, ...] | None = None
    locale: Locale | None = None


@dataclass(frozen=True, slots=True)
class PreparedUserCreate:
    user_id: str
    email: str
    name: str
    password_hash: str
    role: UserRole
    can_manage_system: bool
    can_view_manual_imports: bool
    locale: Locale
    library_ids: tuple[str, ...]
    prepared_at: datetime
    actor_id: str


@dataclass(frozen=True, slots=True)
class PreparedUserUpdate:
    user_id: str
    email: str
    name: str
    role: UserRole
    status: UserStatus
    can_manage_system: bool
    can_view_manual_imports: bool
    authz_version: int
    library_ids: tuple[str, ...] | None
    locale: Locale | None
    disable_sessions: bool
    updated_at: datetime
    actor_id: str


class UserAdministrationGateway(Protocol):
    def list_users(self) -> tuple[AdminUserView, ...]: ...

    def get_user(self, user_id: str) -> AdminUserView | None: ...

    def email_in_use(
        self, email: str, excluding_user_id: str | None = None
    ) -> bool: ...

    def active_admin_count(self, excluding_user_id: str | None = None) -> int: ...

    def validate_library_ids(self, library_ids: tuple[str, ...]) -> tuple[str, ...]: ...

    def new_user_id(self) -> str: ...

    def hash_password(self, password: str) -> str: ...

    def now(self) -> datetime: ...

    def create_user(self, prepared: PreparedUserCreate) -> AdminUserView: ...

    def update_user(self, prepared: PreparedUserUpdate) -> AdminUserView: ...

    def reset_password(
        self, *, user_id: str, password_hash: str, updated_at: datetime, actor_id: str
    ) -> None: ...

    def delete_user(
        self, *, user_id: str, anonymous_user_id: str, actor_id: str
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class UserAdministrationUseCases:
    list_users: ListUsers
    get_user: GetUser
    create_user: CreateUser
    update_user: UpdateUser
    reset_password: ResetUserPassword
    delete_user: DeleteUser


def _require_admin(actor: UserAdministrationActor) -> None:
    if actor.role != "admin":
        raise UserAdministrationError("ADMIN_REQUIRED", "仅管理员可以管理用户与权限")


def _require_user(user: AdminUserView | None) -> AdminUserView:
    if user is None:
        raise UserAdministrationError("USER_NOT_FOUND", "用户不存在")
    return user


class ListUsers:
    def __init__(self, gateway: UserAdministrationGateway) -> None:
        self._gateway = gateway

    def execute(self, actor: UserAdministrationActor) -> tuple[AdminUserView, ...]:
        _require_admin(actor)
        return self._gateway.list_users()


class GetUser:
    def __init__(self, gateway: UserAdministrationGateway) -> None:
        self._gateway = gateway

    def execute(self, actor: UserAdministrationActor, user_id: str) -> AdminUserView:
        _require_admin(actor)
        return _require_user(self._gateway.get_user(user_id))


class CreateUser:
    def __init__(self, gateway: UserAdministrationGateway) -> None:
        self._gateway = gateway

    def execute(
        self, actor: UserAdministrationActor, command: CreateUserCommand
    ) -> AdminUserView:
        _require_admin(actor)
        email = command.email.strip().lower()
        if self._gateway.email_in_use(email):
            raise UserAdministrationError("EMAIL_IN_USE", "该邮箱已被使用")
        try:
            library_ids = (
                ()
                if command.role == "admin"
                else self._gateway.validate_library_ids(command.library_ids)
            )
        except ValueError as exc:
            raise UserAdministrationError("INVALID_FOLDER_ACCESS", str(exc)) from exc
        return self._gateway.create_user(
            PreparedUserCreate(
                user_id=self._gateway.new_user_id(),
                email=email,
                name=command.name,
                password_hash=self._gateway.hash_password(command.password),
                role=command.role,
                can_manage_system=(
                    command.can_manage_system if command.role == "member" else False
                ),
                can_view_manual_imports=(
                    command.can_view_manual_imports
                    if command.role == "member"
                    else False
                ),
                locale=command.locale,
                library_ids=library_ids,
                prepared_at=self._gateway.now(),
                actor_id=actor.id,
            )
        )


class UpdateUser:
    def __init__(self, gateway: UserAdministrationGateway) -> None:
        self._gateway = gateway

    def execute(
        self, actor: UserAdministrationActor, command: UpdateUserCommand
    ) -> AdminUserView:
        _require_admin(actor)
        user = _require_user(self._gateway.get_user(command.user_id))
        next_role = (
            command.role
            if "role" in command.changed_fields and command.role is not None
            else user.role
        )
        next_status = (
            command.status
            if "status" in command.changed_fields and command.status is not None
            else user.status
        )
        removing_active_admin = (
            user.role == "admin"
            and user.status == "active"
            and (next_role != "admin" or next_status != "active")
        )
        if actor.id == user.id and removing_active_admin:
            raise UserAdministrationError(
                "CANNOT_CHANGE_SELF_ADMIN", "不能停用或降级当前登录的管理员"
            )
        if removing_active_admin and self._gateway.active_admin_count(user.id) == 0:
            raise UserAdministrationError(
                "LAST_ADMIN_REQUIRED", "系统必须至少保留一个有效管理员"
            )

        next_email = user.email
        if "email" in command.changed_fields and command.email is not None:
            next_email = command.email.strip().lower()
            if self._gateway.email_in_use(next_email, user.id):
                raise UserAdministrationError("EMAIL_IN_USE", "该邮箱已被使用")
        next_name = (
            command.name
            if "name" in command.changed_fields and command.name is not None
            else user.name
        )
        library_ids: tuple[str, ...] | None = None
        next_can_manage_system = user.can_manage_system
        next_can_view_manual_imports = user.can_view_manual_imports
        if next_role == "admin":
            next_can_manage_system = False
            next_can_view_manual_imports = False
            library_ids = ()
        else:
            if (
                "can_manage_system" in command.changed_fields
                and command.can_manage_system is not None
            ):
                next_can_manage_system = command.can_manage_system
            if (
                "can_view_manual_imports" in command.changed_fields
                and command.can_view_manual_imports is not None
            ):
                next_can_view_manual_imports = command.can_view_manual_imports
            if (
                "library_ids" in command.changed_fields
                and command.library_ids is not None
            ):
                try:
                    library_ids = self._gateway.validate_library_ids(
                        command.library_ids
                    )
                except ValueError as exc:
                    raise UserAdministrationError(
                        "INVALID_FOLDER_ACCESS", str(exc)
                    ) from exc
        return self._gateway.update_user(
            PreparedUserUpdate(
                user_id=user.id,
                email=next_email,
                name=next_name,
                role=next_role,
                status=next_status,
                can_manage_system=next_can_manage_system,
                can_view_manual_imports=next_can_view_manual_imports,
                authz_version=user.authz_version + 1,
                library_ids=library_ids,
                locale=(command.locale if "locale" in command.changed_fields else None),
                disable_sessions=next_status == "disabled",
                updated_at=self._gateway.now(),
                actor_id=actor.id,
            )
        )


class ResetUserPassword:
    def __init__(self, gateway: UserAdministrationGateway) -> None:
        self._gateway = gateway

    def execute(
        self, actor: UserAdministrationActor, user_id: str, password: str
    ) -> None:
        _require_admin(actor)
        user = _require_user(self._gateway.get_user(user_id))
        self._gateway.reset_password(
            user_id=user.id,
            password_hash=self._gateway.hash_password(password),
            updated_at=self._gateway.now(),
            actor_id=actor.id,
        )


class DeleteUser:
    def __init__(self, gateway: UserAdministrationGateway) -> None:
        self._gateway = gateway

    def execute(
        self, actor: UserAdministrationActor, user_id: str, confirmation: str
    ) -> str:
        _require_admin(actor)
        user = _require_user(self._gateway.get_user(user_id))
        if actor.id == user.id:
            raise UserAdministrationError(
                "CANNOT_DELETE_SELF", "不能删除当前登录的管理员"
            )
        if confirmation.strip().lower() != user.email.lower():
            raise UserAdministrationError(
                "DELETE_CONFIRMATION_MISMATCH", "确认邮箱不匹配"
            )
        if (
            user.role == "admin"
            and user.status == "active"
            and self._gateway.active_admin_count(user.id) == 0
        ):
            raise UserAdministrationError(
                "LAST_ADMIN_REQUIRED", "系统必须至少保留一个有效管理员"
            )
        anonymous_id = hashlib.sha256(f"deleted-user:{user.id}".encode()).hexdigest()[
            :24
        ]
        self._gateway.delete_user(
            user_id=user.id,
            anonymous_user_id=anonymous_id,
            actor_id=actor.id,
        )
        return user.id
