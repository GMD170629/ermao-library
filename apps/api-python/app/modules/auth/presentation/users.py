from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.typed_route import TypedContractRoute
from app.bootstrap.auth import (
    list_library_ids,
    persist_admin_password_reset,
    persist_admin_user_create,
    persist_admin_user_delete,
    persist_admin_user_update,
    persist_user_preferences,
    validate_library_ids,
)
from app.contracts.http_errors import ErrorResponses
from app.core.auth import get_current_user, hash_password
from app.core.authorization import (
    authorization_context,
    is_admin,
    read_user_preferences,
)
from app.core.config import Settings, get_settings
from app.core.i18n import configured_locale
from app.db.session import get_db
from app.models.auth import User, cuid, db_timestamp
from app.modules.auth.presentation.requests import (
    AdminCreateUserRequest,
    AdminDeleteUserRequest,
    AdminSetPasswordRequest,
    AdminUpdateUserRequest,
    UpdateUserPreferencesRequest,
)
from app.modules.auth.presentation.user_schemas import (
    AdminPasswordChangedPayload,
    AdminPasswordChangedResponse,
    AdminUser,
    AdminUserPayload,
    AdminUserResponse,
    CodedMessageBody,
    PreferencesPayload,
    PreferencesResponse,
    UnsupportedPreferenceBody,
    UnsupportedPreferenceDetails,
    UnsupportedPreferenceError,
    UserBadRequestError,
    UserConflictError,
    UserDeletedPayload,
    UserDeletedResponse,
    UserForbiddenError,
    UserNotFoundError,
    UsersPayload,
    UsersResponse,
    UserUnauthorizedError,
)
from app.modules.system.public import PreparedSystemEvent
from app.services.system_events import prepare_system_event

router = APIRouter(route_class=TypedContractRoute)
preferences_router = APIRouter(route_class=TypedContractRoute)
EMAIL_ADAPTER = TypeAdapter(EmailStr)

ALLOWED_PREFERENCE_KEYS = {
    "locale",
    "library.view",
    "library.sort",
    "library.sortDirection",
    "audio.playbackRate",
    "kindle.email",
}


def _current_user(
    db: Session,
    request: Request,
    settings: Settings,
) -> User:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        raise UserUnauthorizedError(
            CodedMessageBody(message="UNAUTHORIZED", code="UNAUTHORIZED")
        )
    return user


def _admin_user(
    db: Session,
    request: Request,
    settings: Settings,
) -> User:
    user = _current_user(db, request, settings)
    if not is_admin(user):
        raise UserForbiddenError(
            CodedMessageBody(
                message="仅管理员可以管理用户与权限",
                code="ADMIN_REQUIRED",
            )
        )
    return user


def _folder_ids(db: Session, user_id: str) -> list[str]:
    return list_library_ids(db, user_id)


def _user_view(db: Session, user: User) -> dict[str, Any]:
    preferences = read_user_preferences(db, user.id)
    locale = preferences.get("locale")
    if locale not in {"zh-CN", "en-US"}:
        locale = configured_locale(db)
    return {
        **user.to_auth_view(),
        "locale": locale,
        "libraryIds": [] if is_admin(user) else _folder_ids(db, user.id),
        "authorization": authorization_context(db, user).to_view(),
        "createdAt": user.created_at,
        "updatedAt": user.updated_at,
    }


def _validate_folder_ids(db: Session, folder_ids: list[str]) -> list[str]:
    return validate_library_ids(db, folder_ids)


def _validate_preference(key: str, value: object) -> object:
    if key == "locale":
        if value not in {"zh-CN", "en-US"}:
            raise ValueError("不支持的界面语言")
        return value
    if key == "library.view":
        if value not in {"grid", "list"}:
            raise ValueError("不支持的书库视图")
        return value
    if key == "library.sort":
        if value not in {
            "recent_read",
            "recent_import",
            "title",
            "author",
            "publisher",
            "series",
        }:
            raise ValueError("不支持的书库排序方式")
        return value
    if key == "library.sortDirection":
        if value not in {"asc", "desc"}:
            raise ValueError("不支持的书库排序方向")
        return value
    if key == "audio.playbackRate":
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0.5 <= float(value) <= 3
        ):
            raise ValueError("音频播放速度必须在 0.5 到 3 之间")
        return round(float(value), 2)
    if key == "kindle.email":
        if not isinstance(value, str):
            raise ValueError("Kindle 邮箱格式不正确")
        normalized = value.strip()
        if not normalized:
            return ""
        try:
            return str(EMAIL_ADAPTER.validate_python(normalized)).lower()
        except ValidationError as exc:
            raise ValueError("Kindle 邮箱格式不正确") from exc
    raise ValueError("包含不支持的用户偏好")


def _active_admin_count(db: Session, *, exclude_user_id: str | None = None) -> int:
    query = db.query(User).filter(User.role == "admin", User.status == "active")
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    return query.count()


def _prepare_user_change_event(
    actor: User | None,
    action: str,
    target_id: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> PreparedSystemEvent:
    return prepare_system_event(
        source="authorization",
        action=action,
        message=message,
        actor_type="admin",
        actor_id=actor.id if actor else None,
        target_type="user",
        target_id=target_id,
        metadata=metadata,
    )


@router.get("/users")
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    UsersResponse,
    ErrorResponses(UserUnauthorizedError, UserForbiddenError),
]:
    _admin_user(db, request, settings)
    users = db.query(User).order_by(User.created_at.asc(), User.id.asc()).all()
    return UsersResponse(
        data=UsersPayload(
            users=[AdminUser.model_validate(_user_view(db, user)) for user in users]
        )
    )


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    AdminUserResponse,
    ErrorResponses(
        UserUnauthorizedError,
        UserForbiddenError,
        UserNotFoundError,
    ),
]:
    _admin_user(db, request, settings)
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(
            CodedMessageBody(message="用户不存在", code="USER_NOT_FOUND")
        )
    return AdminUserResponse(
        data=AdminUserPayload(user=AdminUser.model_validate(_user_view(db, user)))
    )


@router.post("/users", status_code=201)
def create_user(
    payload: AdminCreateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    AdminUserResponse,
    ErrorResponses(
        UserUnauthorizedError,
        UserForbiddenError,
        UserBadRequestError,
        UserConflictError,
    ),
]:
    actor = _admin_user(db, request, settings)
    email = str(payload.email).strip().lower()
    if db.query(User.id).filter(func.lower(User.email) == email).first() is not None:
        raise UserConflictError(
            CodedMessageBody(message="该邮箱已被使用", code="EMAIL_IN_USE")
        )
    try:
        folder_ids = (
            []
            if payload.role == "admin"
            else _validate_folder_ids(db, payload.library_ids)
        )
    except ValueError as exc:
        raise UserBadRequestError(
            CodedMessageBody(
                message=str(exc),
                code="INVALID_FOLDER_ACCESS",
            )
        ) from exc
    user = User(
        id=cuid(),
        email=email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        status="active",
        can_manage_system=payload.can_manage_system
        if payload.role == "member"
        else False,
        can_view_manual_imports=payload.can_view_manual_imports
        if payload.role == "member"
        else False,
        authz_version=1,
    )
    now = db_timestamp()
    prepared_event = _prepare_user_change_event(
        actor,
        "user.created",
        user.id,
        "管理员创建了用户",
        {"role": user.role, "canManageSystem": user.can_manage_system},
    )

    try:
        persist_admin_user_create(
            db,
            user=user,
            locale=payload.locale,
            folder_ids=folder_ids,
            prepared_at=now,
            event=prepared_event,
        )
    except IntegrityError:
        raise UserConflictError(
            CodedMessageBody(message="该邮箱已被使用", code="EMAIL_IN_USE")
        )
    user = db.get(User, user.id)
    if user is None:
        raise RuntimeError("created user was not persisted")
    return AdminUserResponse(
        data=AdminUserPayload(
            user=AdminUser.model_validate(_user_view(db, user)),
            createdBy=actor.id,
        )
    )


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    payload: AdminUpdateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    AdminUserResponse,
    ErrorResponses(
        UserUnauthorizedError,
        UserForbiddenError,
        UserNotFoundError,
        UserBadRequestError,
        UserConflictError,
    ),
]:
    actor = _admin_user(db, request, settings)
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(
            CodedMessageBody(message="用户不存在", code="USER_NOT_FOUND")
        )
    fields_set = payload.model_fields_set
    next_role = payload.role if "role" in fields_set else user.role
    next_status = payload.status if "status" in fields_set else user.status
    prepared_folder_ids: list[str] | None = None
    prepared_locale: str | None = None
    removing_active_admin = (
        user.role == "admin"
        and user.status == "active"
        and (next_role != "admin" or next_status != "active")
    )
    if actor is not None and actor.id == user.id and removing_active_admin:
        raise UserBadRequestError(
            CodedMessageBody(
                message="不能停用或降级当前登录的管理员",
                code="CANNOT_CHANGE_SELF_ADMIN",
            )
        )
    if removing_active_admin and _active_admin_count(db, exclude_user_id=user.id) == 0:
        raise UserConflictError(
            CodedMessageBody(
                message="系统必须至少保留一个有效管理员",
                code="LAST_ADMIN_REQUIRED",
            )
        )
    next_email = user.email
    next_name = user.name
    next_can_manage_system = user.can_manage_system
    next_can_view_manual_imports = user.can_view_manual_imports
    if "email" in fields_set and payload.email is not None:
        next_email = str(payload.email).strip().lower()
        duplicate = (
            db.query(User.id)
            .filter(func.lower(User.email) == next_email, User.id != user.id)
            .first()
        )
        if duplicate is not None:
            raise UserConflictError(
                CodedMessageBody(message="该邮箱已被使用", code="EMAIL_IN_USE")
            )
    if "name" in fields_set and payload.name is not None:
        next_name = payload.name
    if next_role == "admin":
        next_can_manage_system = False
        next_can_view_manual_imports = False
        prepared_folder_ids = []
    else:
        if "can_manage_system" in fields_set and payload.can_manage_system is not None:
            next_can_manage_system = payload.can_manage_system
        if (
            "can_view_manual_imports" in fields_set
            and payload.can_view_manual_imports is not None
        ):
            next_can_view_manual_imports = payload.can_view_manual_imports
        if "library_ids" in fields_set and payload.library_ids is not None:
            try:
                prepared_folder_ids = _validate_folder_ids(db, payload.library_ids)
            except ValueError as exc:
                raise UserBadRequestError(
                    CodedMessageBody(
                        message=str(exc),
                        code="INVALID_FOLDER_ACCESS",
                    )
                ) from exc
    if "locale" in fields_set and payload.locale is not None:
        prepared_locale = payload.locale
    next_authz_version = int(user.authz_version or 1) + 1
    updated_at = db_timestamp()
    prepared_user_values: dict[str, object] = {
        "email": next_email,
        "name": next_name,
        "role": next_role,
        "status": next_status,
        "can_manage_system": next_can_manage_system,
        "can_view_manual_imports": next_can_view_manual_imports,
        "authz_version": next_authz_version,
        "updated_at": updated_at,
    }
    prepared_event = _prepare_user_change_event(
        actor,
        "user.authorization.updated",
        user.id,
        "管理员更新了用户与权限",
        {
            "role": next_role,
            "status": next_status,
            "canManageSystem": next_can_manage_system,
            "authzVersion": next_authz_version,
        },
    )

    try:
        persist_admin_user_update(
            db,
            user_id=user.id,
            user_values=prepared_user_values,
            folder_ids=prepared_folder_ids,
            locale=prepared_locale,
            updated_at=updated_at,
            disable_sessions=next_status == "disabled",
            event=prepared_event,
        )
    except IntegrityError:
        raise UserConflictError(
            CodedMessageBody(message="该邮箱已被使用", code="EMAIL_IN_USE")
        )
    db.refresh(user)
    return AdminUserResponse(
        data=AdminUserPayload(user=AdminUser.model_validate(_user_view(db, user)))
    )


@router.put("/users/{user_id}/password")
def set_user_password(
    user_id: str,
    payload: AdminSetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    AdminPasswordChangedResponse,
    ErrorResponses(
        UserUnauthorizedError,
        UserForbiddenError,
        UserNotFoundError,
    ),
]:
    actor = _admin_user(db, request, settings)
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(
            CodedMessageBody(message="用户不存在", code="USER_NOT_FOUND")
        )
    password_hash = hash_password(payload.password)
    updated_at = db_timestamp()
    prepared_event = _prepare_user_change_event(
        actor,
        "user.password.reset",
        user.id,
        "管理员重置了用户密码并撤销会话",
    )

    persist_admin_password_reset(
        db,
        user_id=user.id,
        password_hash=password_hash,
        updated_at=updated_at,
        event=prepared_event,
    )
    return AdminPasswordChangedResponse(data=AdminPasswordChangedPayload())


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    payload: AdminDeleteUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    UserDeletedResponse,
    ErrorResponses(
        UserUnauthorizedError,
        UserForbiddenError,
        UserNotFoundError,
        UserBadRequestError,
        UserConflictError,
    ),
]:
    actor = _admin_user(db, request, settings)
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(
            CodedMessageBody(message="用户不存在", code="USER_NOT_FOUND")
        )
    if actor is not None and actor.id == user.id:
        raise UserBadRequestError(
            CodedMessageBody(
                message="不能删除当前登录的管理员",
                code="CANNOT_DELETE_SELF",
            )
        )
    if payload.confirmation.strip().lower() != user.email.lower():
        raise UserBadRequestError(
            CodedMessageBody(
                message="确认邮箱不匹配",
                code="DELETE_CONFIRMATION_MISMATCH",
            )
        )
    if (
        user.role == "admin"
        and user.status == "active"
        and _active_admin_count(db, exclude_user_id=user.id) == 0
    ):
        raise UserConflictError(
            CodedMessageBody(
                message="系统必须至少保留一个有效管理员",
                code="LAST_ADMIN_REQUIRED",
            )
        )
    deleted_user_id = user.id
    anonymous_target = hashlib.sha256(f"deleted-user:{user.id}".encode()).hexdigest()[
        :24
    ]
    avatar_path = None
    if user.avatar_path:
        candidate = (settings.resolved_storage_root / user.avatar_path).resolve()
        try:
            candidate.relative_to(settings.resolved_storage_root)
            avatar_path = candidate
        except ValueError:
            avatar_path = None
    prepared_event = _prepare_user_change_event(
        actor,
        "user.deleted",
        anonymous_target,
        "管理员永久删除了用户及其个人数据",
        {"formerRole": user.role, "deidentified": True},
    )

    persist_admin_user_delete(
        db,
        user_id=user.id,
        anonymous_user_id=anonymous_target,
        event=prepared_event,
    )
    if avatar_path is not None:
        avatar_path.unlink(missing_ok=True)
        try:
            avatar_path.parent.rmdir()
        except OSError:
            pass
    return UserDeletedResponse(
        data=UserDeletedPayload(deleted=True, userId=deleted_user_id)
    )


@preferences_router.get("/preferences")
def get_preferences(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    PreferencesResponse,
    ErrorResponses(UserUnauthorizedError),
]:
    user = _current_user(db, request, settings)
    preferences = read_user_preferences(db, user.id)
    if preferences.get("locale") not in {"zh-CN", "en-US"}:
        preferences["locale"] = configured_locale(db)
    return PreferencesResponse(
        data=PreferencesPayload.model_validate({"preferences": preferences})
    )


@preferences_router.patch("/preferences")
def update_preferences(
    payload: UpdateUserPreferencesRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    PreferencesResponse,
    ErrorResponses(
        UserUnauthorizedError,
        UnsupportedPreferenceError,
        UserBadRequestError,
    ),
]:
    user = _current_user(db, request, settings)
    unsupported = sorted(set(payload.preferences) - ALLOWED_PREFERENCE_KEYS)
    if unsupported:
        raise UnsupportedPreferenceError(
            UnsupportedPreferenceBody(
                message="包含不支持的用户偏好",
                details=UnsupportedPreferenceDetails(keys=unsupported),
            )
        )
    try:
        normalized = {
            key: _validate_preference(key, value)
            for key, value in payload.preferences.items()
        }
    except ValueError as exc:
        raise UserBadRequestError(
            CodedMessageBody(
                message=str(exc),
                code="INVALID_USER_PREFERENCE",
            )
        ) from exc
    preference_updated_at = db_timestamp()
    persist_user_preferences(
        db,
        user_id=user.id,
        preferences=normalized,
        updated_at=preference_updated_at,
    )
    locale = normalized.get("locale")
    if isinstance(locale, str):
        response.set_cookie(
            "shuku_locale",
            locale,
            path=settings.cookie_path,
            max_age=60 * 60 * 24 * 365,
            samesite="lax",
            secure=settings.secure_cookies,
        )
    preferences = read_user_preferences(db, user.id)
    if preferences.get("locale") not in {"zh-CN", "en-US"}:
        preferences["locale"] = configured_locale(db)
    return PreferencesResponse(
        data=PreferencesPayload.model_validate({"preferences": preferences})
    )
