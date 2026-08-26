from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.api.typed_route import TypedContractRoute
from app.bootstrap.auth import (
    build_user_administration_use_cases,
    persist_user_preferences,
)
from app.contracts.http_errors import ErrorResponses
from app.core.auth import get_current_user
from app.core.authorization import (
    read_user_preferences,
)
from app.core.config import Settings, get_settings
from app.core.i18n import configured_locale
from app.db.session import get_db
from app.models.auth import User, db_timestamp
from app.modules.auth.application.user_management import (
    AdminUserView,
    CreateUserCommand,
    UpdateUserCommand,
    UserAdministrationActor,
    UserAdministrationError,
)
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


def _actor(user: User) -> UserAdministrationActor:
    return UserAdministrationActor(id=user.id, role=user.role)


def _admin_user_payload(user: AdminUserView) -> AdminUser:
    return AdminUser.model_validate(
        {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "status": user.status,
            "canManageSystem": user.can_manage_system,
            "canViewManualImports": user.can_view_manual_imports,
            "authzVersion": user.authz_version,
            "avatarUrl": user.avatar_url,
            "locale": user.locale,
            "libraryIds": list(user.library_ids),
            "authorization": {
                "isAdmin": user.authorization.is_admin,
                "canManageSystem": user.authorization.can_manage_system,
                "allLibraryScopes": user.authorization.all_library_scopes,
                "libraryIds": list(user.authorization.library_ids),
                "canViewManualImports": (user.authorization.can_view_manual_imports),
                "authzVersion": user.authorization.authz_version,
            },
            "createdAt": user.created_at,
            "updatedAt": user.updated_at,
        }
    )


def _raise_user_administration_error(error: UserAdministrationError) -> None:
    body = CodedMessageBody(message=error.message, code=error.code)
    if error.code == "ADMIN_REQUIRED":
        raise UserForbiddenError(body) from error
    if error.code == "USER_NOT_FOUND":
        raise UserNotFoundError(body) from error
    if error.code in {"EMAIL_IN_USE", "LAST_ADMIN_REQUIRED"}:
        raise UserConflictError(body) from error
    raise UserBadRequestError(body) from error


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


@router.get("/users")
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    UsersResponse,
    ErrorResponses(UserUnauthorizedError, UserForbiddenError),
]:
    actor = _current_user(db, request, settings)
    try:
        users = build_user_administration_use_cases(db, settings).list_users.execute(
            _actor(actor)
        )
    except UserAdministrationError as exc:
        _raise_user_administration_error(exc)
    return UsersResponse(
        data=UsersPayload(users=[_admin_user_payload(user) for user in users])
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
    actor = _current_user(db, request, settings)
    try:
        user = build_user_administration_use_cases(db, settings).get_user.execute(
            _actor(actor), user_id
        )
    except UserAdministrationError as exc:
        _raise_user_administration_error(exc)
    return AdminUserResponse(data=AdminUserPayload(user=_admin_user_payload(user)))


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
    actor = _current_user(db, request, settings)
    try:
        user = build_user_administration_use_cases(db, settings).create_user.execute(
            _actor(actor),
            CreateUserCommand(
                name=payload.name,
                email=str(payload.email),
                password=payload.password,
                role=payload.role,
                can_manage_system=payload.can_manage_system,
                can_view_manual_imports=payload.can_view_manual_imports,
                library_ids=tuple(payload.library_ids),
                locale=payload.locale,
            ),
        )
    except UserAdministrationError as exc:
        _raise_user_administration_error(exc)
    return AdminUserResponse(
        data=AdminUserPayload(
            user=_admin_user_payload(user),
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
    actor = _current_user(db, request, settings)
    try:
        user = build_user_administration_use_cases(db, settings).update_user.execute(
            _actor(actor),
            UpdateUserCommand(
                user_id=user_id,
                changed_fields=frozenset(payload.model_fields_set),
                name=payload.name,
                email=str(payload.email) if payload.email is not None else None,
                role=payload.role,
                status=payload.status,
                can_manage_system=payload.can_manage_system,
                can_view_manual_imports=payload.can_view_manual_imports,
                library_ids=(
                    tuple(payload.library_ids)
                    if payload.library_ids is not None
                    else None
                ),
                locale=payload.locale,
            ),
        )
    except UserAdministrationError as exc:
        _raise_user_administration_error(exc)
    return AdminUserResponse(data=AdminUserPayload(user=_admin_user_payload(user)))


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
    actor = _current_user(db, request, settings)
    try:
        build_user_administration_use_cases(db, settings).reset_password.execute(
            _actor(actor), user_id, payload.password
        )
    except UserAdministrationError as exc:
        _raise_user_administration_error(exc)
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
    actor = _current_user(db, request, settings)
    try:
        deleted_user_id = build_user_administration_use_cases(
            db, settings
        ).delete_user.execute(_actor(actor), user_id, payload.confirmation)
    except UserAdministrationError as exc:
        _raise_user_administration_error(exc)
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
