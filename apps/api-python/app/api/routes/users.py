from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, hash_password
from app.core.authorization import authorization_context, is_admin, read_user_preferences, write_user_preference
from app.core.config import Settings, get_settings
from app.core.i18n import configured_locale
from app.db.session import get_db
from app.models.auth import Session as UserSession
from app.models.auth import User, cuid, db_timestamp
from app.modules.auth.infrastructure.user_data import (
    delete_personal_user_data,
    list_monitor_folder_ids,
    replace_monitor_folder_access,
    validate_monitor_folder_ids,
)
from app.schemas.auth import (
    AdminCreateUserRequest,
    AdminDeleteUserRequest,
    AdminSetPasswordRequest,
    AdminUpdateUserRequest,
    UpdateUserPreferencesRequest,
)
from app.schemas.responses import fail, ok
from app.services.system_events import record_system_event

router = APIRouter()
preferences_router = APIRouter()
EMAIL_ADAPTER = TypeAdapter(EmailStr)

ALLOWED_PREFERENCE_KEYS = {
    "locale",
    "library.view",
    "audio.playbackRate",
    "kindle.email",
}


def _current_user(
    db: Session,
    request: Request,
    settings: Settings,
) -> tuple[User | None, Any | None]:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        return None, fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
    return user, None


def _admin_user(
    db: Session,
    request: Request,
    settings: Settings,
) -> tuple[User | None, Any | None]:
    user, error = _current_user(db, request, settings)
    if error is not None:
        return None, error
    if user is None or not is_admin(user):
        return None, fail("仅管理员可以管理用户与权限", status_code=403, code="ADMIN_REQUIRED")
    return user, None


def _folder_ids(db: Session, user_id: str) -> list[str]:
    return list_monitor_folder_ids(db, user_id)


def _user_view(db: Session, user: User) -> dict[str, Any]:
    preferences = read_user_preferences(db, user.id)
    locale = preferences.get("locale")
    if locale not in {"zh-CN", "en-US"}:
        locale = configured_locale(db)
    return {
        **user.to_auth_view(),
        "locale": locale,
        "monitorFolderIds": [] if is_admin(user) else _folder_ids(db, user.id),
        "authorization": authorization_context(db, user).to_view(),
        "createdAt": user.created_at,
        "updatedAt": user.updated_at,
    }


def _validate_folder_ids(db: Session, folder_ids: list[str]) -> list[str]:
    return validate_monitor_folder_ids(db, folder_ids)


def _replace_folder_access(db: Session, user_id: str, folder_ids: list[str]) -> None:
    replace_monitor_folder_access(db, user_id, folder_ids, db_timestamp())


def _save_preference(db: Session, user_id: str, key: str, value: object) -> None:
    write_user_preference(db, user_id, key, value)


def _validate_preference(key: str, value: object) -> object:
    if key == "locale":
        if value not in {"zh-CN", "en-US"}:
            raise ValueError("不支持的界面语言")
        return value
    if key == "library.view":
        if value not in {"grid", "list"}:
            raise ValueError("不支持的书库视图")
        return value
    if key == "audio.playbackRate":
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.5 <= float(value) <= 3:
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


def _audit_user_change(
    db: Session,
    actor: User | None,
    action: str,
    target_id: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_system_event(
        db,
        source="authorization",
        action=action,
        message=message,
        actor_type="admin",
        actor_id=actor.id if actor else None,
        target_type="user",
        target_id=target_id,
        metadata=metadata,
    )


def _delete_personal_user_data(db: Session, user_id: str, anonymous_user_id: str) -> None:
    delete_personal_user_data(db, user_id, anonymous_user_id)


@router.get("/users")
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _actor, error = _admin_user(db, request, settings)
    if error is not None:
        return error
    users = db.query(User).order_by(User.created_at.asc(), User.id.asc()).all()
    return ok({"users": [_user_view(db, user) for user in users]})


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _actor, error = _admin_user(db, request, settings)
    if error is not None:
        return error
    user = db.get(User, user_id)
    if user is None:
        return fail("用户不存在", status_code=404, code="USER_NOT_FOUND")
    return ok({"user": _user_view(db, user)})


@router.post("/users", status_code=201)
def create_user(
    payload: AdminCreateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    actor, error = _admin_user(db, request, settings)
    if error is not None:
        return error
    email = str(payload.email).strip().lower()
    if db.query(User.id).filter(func.lower(User.email) == email).first() is not None:
        return fail("该邮箱已被使用", status_code=409, code="EMAIL_IN_USE")
    try:
        folder_ids = [] if payload.role == "admin" else _validate_folder_ids(db, payload.monitor_folder_ids)
    except ValueError as exc:
        return fail(str(exc), status_code=400, code="INVALID_FOLDER_ACCESS")
    user = User(
        id=cuid(),
        email=email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        status="active",
        can_manage_system=payload.can_manage_system if payload.role == "member" else False,
        can_view_manual_imports=payload.can_view_manual_imports if payload.role == "member" else False,
        authz_version=1,
    )
    db.add(user)
    db.flush()
    _replace_folder_access(db, user.id, folder_ids)
    _save_preference(db, user.id, "locale", payload.locale)
    _audit_user_change(
        db,
        actor,
        "user.created",
        user.id,
        "管理员创建了用户",
        {"role": user.role, "canManageSystem": user.can_manage_system},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return fail("该邮箱已被使用", status_code=409, code="EMAIL_IN_USE")
    db.refresh(user)
    return ok({"user": _user_view(db, user), "createdBy": actor.id if actor else None}, status_code=201)


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    payload: AdminUpdateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    actor, error = _admin_user(db, request, settings)
    if error is not None:
        return error
    user = db.get(User, user_id)
    if user is None:
        return fail("用户不存在", status_code=404, code="USER_NOT_FOUND")
    fields_set = payload.model_fields_set
    next_role = payload.role if "role" in fields_set else user.role
    next_status = payload.status if "status" in fields_set else user.status
    removing_active_admin = user.role == "admin" and user.status == "active" and (
        next_role != "admin" or next_status != "active"
    )
    if actor is not None and actor.id == user.id and removing_active_admin:
        return fail("不能停用或降级当前登录的管理员", status_code=400, code="CANNOT_CHANGE_SELF_ADMIN")
    if removing_active_admin and _active_admin_count(db, exclude_user_id=user.id) == 0:
        return fail("系统必须至少保留一个有效管理员", status_code=409, code="LAST_ADMIN_REQUIRED")
    if "email" in fields_set and payload.email is not None:
        email = str(payload.email).strip().lower()
        duplicate = db.query(User.id).filter(func.lower(User.email) == email, User.id != user.id).first()
        if duplicate is not None:
            return fail("该邮箱已被使用", status_code=409, code="EMAIL_IN_USE")
        user.email = email
    if "name" in fields_set and payload.name is not None:
        user.name = payload.name
    user.role = next_role
    user.status = next_status
    if next_role == "admin":
        user.can_manage_system = False
        user.can_view_manual_imports = False
        _replace_folder_access(db, user.id, [])
    else:
        if "can_manage_system" in fields_set and payload.can_manage_system is not None:
            user.can_manage_system = payload.can_manage_system
        if "can_view_manual_imports" in fields_set and payload.can_view_manual_imports is not None:
            user.can_view_manual_imports = payload.can_view_manual_imports
        if "monitor_folder_ids" in fields_set and payload.monitor_folder_ids is not None:
            try:
                _replace_folder_access(db, user.id, _validate_folder_ids(db, payload.monitor_folder_ids))
            except ValueError as exc:
                db.rollback()
                return fail(str(exc), status_code=400, code="INVALID_FOLDER_ACCESS")
    if "locale" in fields_set and payload.locale is not None:
        _save_preference(db, user.id, "locale", payload.locale)
    user.authz_version = int(user.authz_version or 1) + 1
    user.updated_at = db_timestamp()
    db.add(user)
    if next_status == "disabled":
        db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
    _audit_user_change(
        db,
        actor,
        "user.authorization.updated",
        user.id,
        "管理员更新了用户与权限",
        {
            "role": user.role,
            "status": user.status,
            "canManageSystem": user.can_manage_system,
            "authzVersion": user.authz_version,
        },
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return fail("该邮箱已被使用", status_code=409, code="EMAIL_IN_USE")
    db.refresh(user)
    return ok({"user": _user_view(db, user)})


@router.put("/users/{user_id}/password")
def set_user_password(
    user_id: str,
    payload: AdminSetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    actor, error = _admin_user(db, request, settings)
    if error is not None:
        return error
    user = db.get(User, user_id)
    if user is None:
        return fail("用户不存在", status_code=404, code="USER_NOT_FOUND")
    user.password_hash = hash_password(payload.password)
    user.updated_at = db_timestamp()
    db.add(user)
    db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
    _audit_user_change(db, actor, "user.password.reset", user.id, "管理员重置了用户密码并撤销会话")
    db.commit()
    return ok({"passwordChanged": True, "sessionsRevoked": True})


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    payload: AdminDeleteUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    actor, error = _admin_user(db, request, settings)
    if error is not None:
        return error
    user = db.get(User, user_id)
    if user is None:
        return fail("用户不存在", status_code=404, code="USER_NOT_FOUND")
    if actor is not None and actor.id == user.id:
        return fail("不能删除当前登录的管理员", status_code=400, code="CANNOT_DELETE_SELF")
    if payload.confirmation.strip().lower() != user.email.lower():
        return fail("确认邮箱不匹配", status_code=400, code="DELETE_CONFIRMATION_MISMATCH")
    if user.role == "admin" and user.status == "active" and _active_admin_count(db, exclude_user_id=user.id) == 0:
        return fail("系统必须至少保留一个有效管理员", status_code=409, code="LAST_ADMIN_REQUIRED")
    deleted_user_id = user.id
    anonymous_target = hashlib.sha256(f"deleted-user:{user.id}".encode("utf-8")).hexdigest()[:24]
    avatar_path = None
    if user.avatar_path:
        candidate = (settings.resolved_storage_root / user.avatar_path).resolve()
        try:
            candidate.relative_to(settings.resolved_storage_root)
            avatar_path = candidate
        except ValueError:
            avatar_path = None
    _audit_user_change(
        db,
        actor,
        "user.deleted",
        anonymous_target,
        "管理员永久删除了用户及其个人数据",
        {"formerRole": user.role, "deidentified": True},
    )
    _delete_personal_user_data(db, user.id, anonymous_target)
    db.delete(user)
    db.commit()
    if avatar_path is not None:
        avatar_path.unlink(missing_ok=True)
        try:
            avatar_path.parent.rmdir()
        except OSError:
            pass
    return ok({"deleted": True, "userId": deleted_user_id})


@preferences_router.get("/preferences")
def get_preferences(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, error = _current_user(db, request, settings)
    if error is not None:
        return error
    preferences = read_user_preferences(db, user.id)
    if preferences.get("locale") not in {"zh-CN", "en-US"}:
        preferences["locale"] = configured_locale(db)
    return ok({"preferences": preferences})


@preferences_router.patch("/preferences")
def update_preferences(
    payload: UpdateUserPreferencesRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, error = _current_user(db, request, settings)
    if error is not None:
        return error
    unsupported = sorted(set(payload.preferences) - ALLOWED_PREFERENCE_KEYS)
    if unsupported:
        return fail(
            "包含不支持的用户偏好",
            status_code=400,
            code="UNSUPPORTED_USER_PREFERENCE",
            details={"keys": unsupported},
        )
    try:
        normalized = {
            key: _validate_preference(key, value)
            for key, value in payload.preferences.items()
        }
    except ValueError as exc:
        return fail(str(exc), status_code=400, code="INVALID_USER_PREFERENCE")
    for key, value in normalized.items():
        _save_preference(db, user.id, key, value)
    db.commit()
    response = ok({"preferences": read_user_preferences(db, user.id)})
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
    return response
