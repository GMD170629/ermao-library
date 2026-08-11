from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api.typed_route import TypedContractRoute
from app.bootstrap.auth import (
    persist_account_avatar,
    persist_account_email,
    persist_account_name,
    persist_account_password,
    persist_confirmed_password_reset,
    persist_initial_setup,
    persist_login_session,
    persist_logout,
    persist_password_reset_request,
    persist_session_refresh,
    prepare_account_avatar_publication,
    remove_password_reset_request,
)
from app.contracts.http import MessageError
from app.contracts.http_errors import ErrorResponses
from app.core.auth import (
    delete_session_cookie,
    get_current_user,
    hash_password,
    hash_token,
    prepare_session,
    session_expiry,
    set_session_cookie,
    utcnow,
    verify_password,
)
from app.core.authorization import authorization_context, read_user_preferences
from app.core.config import Settings, get_settings
from app.core.database_errors import (
    is_database_busy_error,
    is_database_operation_timeout,
)
from app.core.i18n import configured_locale
from app.db.session import get_db, get_short_write_db
from app.models.auth import PasswordResetToken, User, cuid, db_timestamp
from app.modules.auth.application.password_authentication import normalize_login_email
from app.modules.auth.presentation.requests import (
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SetupRequest,
    UpdateEmailRequest,
    UpdateNameRequest,
    UpdatePasswordRequest,
)
from app.modules.auth.presentation.schemas import (
    AccountDisabledBody,
    AccountDisabledError,
    AuthUser,
    AvatarFileResponse,
    AvatarUpdateDeferredBody,
    AvatarUpdateDeferredError,
    BasicBadRequestError,
    BasicConflictError,
    BasicInternalError,
    BasicNotFoundError,
    BasicUnauthorizedError,
    CapabilitiesPayload,
    CapabilitiesResponse,
    LoggedOutPayload,
    LoggedOutResponse,
    PasswordChangedPayload,
    PasswordChangedResponse,
    PasswordResetPayload,
    PasswordResetRequestPayload,
    PasswordResetRequestResponse,
    PasswordResetResponse,
    PayloadTooLargeError,
    SessionPayload,
    SessionRefreshDeferredBody,
    SessionRefreshDeferredError,
    SessionResponse,
    SessionUnauthorizedError,
    SetupPayload,
    SetupRequiredBody,
    SetupRequiredDetails,
    SetupRequiredError,
    SetupResponse,
    SetupStatusPayload,
    SetupStatusResponse,
    UserPayload,
    UserResponse,
)
from app.services.password_reset_file import (
    password_reset_file_path,
    password_reset_url,
    write_password_reset_file,
)

router = APIRouter(route_class=TypedContractRoute)
LOGGER = logging.getLogger(__name__)

MAX_AVATAR_BYTES = 5 * 1024 * 1024
RESET_TOKEN_MIN_INTERVAL = timedelta(seconds=60)
RESET_TOKEN_DAILY_LIMIT = 5
RESET_TOKEN_TTL = timedelta(minutes=30)
RESET_REQUEST_MESSAGE = "如果该邮箱已绑定账户，密码重置文件已在本地目录创建。"
ALLOWED_AVATAR_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _normalized_email(value: object) -> str:
    return normalize_login_email(str(value))


def _authenticated_user(
    db: Session, request: Request, settings: Settings
) -> User | None:
    user, _token, _refreshed_expires_at = get_current_user(db, request, settings)
    return user


def _user_locale(db: Session, user: User) -> str:
    preferences = read_user_preferences(db, user.id)
    locale = preferences.get("locale")
    return str(locale) if locale in {"zh-CN", "en-US"} else configured_locale(db)


def _session_payload(db: Session, user: User) -> dict[str, object]:
    preferences = read_user_preferences(db, user.id)
    locale = preferences.get("locale")
    if locale not in {"zh-CN", "en-US"}:
        locale = configured_locale(db)
        preferences["locale"] = locale
    return {
        "user": {**user.to_auth_view(), "locale": locale},
        "authorization": authorization_context(db, user).to_view(),
        "preferences": preferences,
    }


def _request_app_base_url(request: Request) -> str:
    referer = request.headers.get("referer", "").strip()
    if referer:
        from urllib.parse import urlsplit, urlunsplit

        parsed = urlsplit(referer)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            path = parsed.path.rstrip("/")
            path = path.removesuffix("/forgot-password")
            return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    forwarded_proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    forwarded_host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    forwarded_prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    return f"{forwarded_proto}://{forwarded_host}{forwarded_prefix}"


def _resolved_avatar_path(user: User, settings: Settings) -> Path | None:
    if not user.avatar_path:
        return None
    storage_root = settings.resolved_storage_root
    candidate = (storage_root / user.avatar_path).resolve()
    try:
        candidate.relative_to(storage_root)
    except ValueError:
        return None
    return candidate


def _raise_avatar_update_deferred(error: OperationalError) -> None:
    if not (is_database_busy_error(error) or is_database_operation_timeout(error)):
        raise error
    raise AvatarUpdateDeferredError(
        AvatarUpdateDeferredBody(message="AVATAR_UPDATE_DEFERRED")
    ) from error


def _remove_unreferenced_avatar(path: Path, *, user_id: str) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        LOGGER.warning(
            "auth.avatar.cleanup outcome=deferred user_id=%s",
            user_id,
        )


@router.get("/capabilities")
def capabilities(
    settings: Settings = Depends(get_settings),
) -> CapabilitiesResponse:
    return CapabilitiesResponse(
        data=CapabilitiesPayload(
            localPasswordReset=True,
            passwordResetFilePath=str(password_reset_file_path(settings)),
        )
    )


@router.get("/setup/status")
def setup_status(
    response: Response,
    db: Session = Depends(get_db),
) -> SetupStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    return SetupStatusResponse(
        data=SetupStatusPayload(initialized=db.query(User.id).first() is not None)
    )


@router.post("/setup", status_code=201)
def setup(
    payload: SetupRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SetupResponse,
    ErrorResponses(BasicConflictError, BasicInternalError),
]:
    if db.query(User.id).first() is not None:
        raise BasicConflictError(MessageError(message="系统已经完成初始化，请直接登录"))
    email = _normalized_email(payload.email)
    user_id = cuid()
    now = db_timestamp()
    user = User(
        id=user_id,
        email=email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role="admin",
        created_at=now,
        updated_at=now,
    )
    user_session, token = prepare_session(user_id, current_time=now)
    try:
        persist_initial_setup(
            db,
            user=user,
            preferences={"locale": payload.locale},
            prepared_at=now,
            user_session=user_session,
        )
    except IntegrityError:
        raise BasicConflictError(MessageError(message="系统已经完成初始化，请直接登录"))
    user = db.get(User, user_id)
    if user is None:
        raise BasicInternalError(MessageError(message="账户创建失败"))

    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        "shuku_locale",
        payload.locale,
        path=settings.cookie_path,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
        secure=settings.secure_cookies,
    )
    set_session_cookie(response, token, user_session.expires_at, settings)
    return SetupResponse(
        data=SetupPayload.model_validate(
            {"initialized": True, **_session_payload(db, user)}
        )
    )


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SessionResponse,
    ErrorResponses(
        SetupRequiredError,
        BasicUnauthorizedError,
        AccountDisabledError,
    ),
]:
    email = _normalized_email(payload.email)
    user = db.query(User).filter(func.lower(User.email) == email).one_or_none()
    if user is None and db.query(User.id).first() is None:
        raise SetupRequiredError(
            SetupRequiredBody(
                message="系统尚未初始化",
                details=SetupRequiredDetails(),
            )
        )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise BasicUnauthorizedError(MessageError(message="邮箱或密码不正确"))
    if user.status != "active":
        raise AccountDisabledError(
            AccountDisabledBody(message="账户已停用，请联系管理员")
        )

    user_session, token = prepare_session(user.id)
    persist_login_session(
        db,
        user_session=user_session,
        prepared_at=user_session.created_at,
    )
    set_session_cookie(response, token, user_session.expires_at, settings)
    return SessionResponse(
        data=SessionPayload.model_validate(_session_payload(db, user))
    )


@router.get("/me")
def me(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SessionResponse,
    ErrorResponses(SessionUnauthorizedError),
]:
    user, token, refreshed_expires_at = get_current_user(db, request, settings)
    if user is None:
        raise SessionUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    if token is not None and refreshed_expires_at is not None:
        response.headers["X-Shuku-Session-Refresh"] = "required"
    return SessionResponse(
        data=SessionPayload.model_validate(_session_payload(db, user))
    )


@router.post("/session/refresh")
def refresh_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_short_write_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SessionResponse,
    ErrorResponses(SessionUnauthorizedError, SessionRefreshDeferredError),
]:
    user, token, _refresh_required_at = get_current_user(db, request, settings)
    if user is None or token is None:
        raise SessionUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    refresh_time = utcnow()
    next_expiry = session_expiry()
    try:
        expires_at = persist_session_refresh(
            db,
            token=token,
            current_time=refresh_time,
            expires_at=next_expiry,
        )
    except OperationalError as exc:
        if not (is_database_busy_error(exc) or is_database_operation_timeout(exc)):
            raise
        raise SessionRefreshDeferredError(
            SessionRefreshDeferredBody(
                message="SESSION_REFRESH_DEFERRED",
            )
        ) from exc
    if expires_at is None:
        raise SessionUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    set_session_cookie(response, token, expires_at, settings)
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(
        data=SessionPayload.model_validate(_session_payload(db, user))
    )


@router.patch("/account/email")
def update_email(
    payload: UpdateEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    UserResponse,
    ErrorResponses(
        BasicUnauthorizedError,
        BasicBadRequestError,
        BasicConflictError,
    ),
]:
    user = _authenticated_user(db, request, settings)
    if user is None:
        raise BasicUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    if not verify_password(payload.current_password, user.password_hash):
        raise BasicBadRequestError(MessageError(message="当前密码不正确"))

    email = _normalized_email(payload.email)
    duplicate = (
        db.query(User)
        .filter(func.lower(User.email) == email, User.id != user.id)
        .first()
    )
    if duplicate is not None:
        raise BasicConflictError(MessageError(message="该邮箱已被使用"))

    updated_at = db_timestamp()
    try:
        persist_account_email(
            db,
            user_id=user.id,
            email=email,
            updated_at=updated_at,
        )
    except IntegrityError:
        raise BasicConflictError(MessageError(message="该邮箱已被使用"))
    db.refresh(user)
    return UserResponse(
        data=UserPayload(user=AuthUser.model_validate(user.to_auth_view()))
    )


@router.patch("/account/name")
def update_name(
    payload: UpdateNameRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    UserResponse,
    ErrorResponses(BasicUnauthorizedError),
]:
    user = _authenticated_user(db, request, settings)
    if user is None:
        raise BasicUnauthorizedError(MessageError(message="UNAUTHORIZED"))

    persist_account_name(
        db,
        user_id=user.id,
        name=payload.name,
        updated_at=db_timestamp(),
    )
    db.refresh(user)
    return UserResponse(
        data=UserPayload(user=AuthUser.model_validate(user.to_auth_view()))
    )


@router.patch("/account/password")
def update_password(
    payload: UpdatePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    PasswordChangedResponse,
    ErrorResponses(BasicUnauthorizedError, BasicBadRequestError),
]:
    user = _authenticated_user(db, request, settings)
    if user is None:
        raise BasicUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    if not verify_password(payload.current_password, user.password_hash):
        raise BasicBadRequestError(MessageError(message="当前密码不正确"))
    if verify_password(payload.new_password, user.password_hash):
        raise BasicBadRequestError(MessageError(message="新密码不能与当前密码相同"))

    password_hash = hash_password(payload.new_password)
    persist_account_password(
        db,
        user_id=user.id,
        password_hash=password_hash,
        updated_at=db_timestamp(),
    )
    delete_session_cookie(response, settings)
    return PasswordChangedResponse(data=PasswordChangedPayload())


@router.post("/avatar")
async def upload_avatar(
    request: Request,
    avatar: UploadFile = File(...),
    db: Session = Depends(get_short_write_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    UserResponse,
    ErrorResponses(
        BasicUnauthorizedError,
        BasicBadRequestError,
        PayloadTooLargeError,
        AvatarUpdateDeferredError,
    ),
]:
    user = _authenticated_user(db, request, settings)
    if user is None:
        raise BasicUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    if (avatar.content_type or "").lower() not in ALLOWED_AVATAR_CONTENT_TYPES:
        raise BasicBadRequestError(
            MessageError(message="仅支持 JPEG、PNG 或 WebP 头像")
        )

    try:
        data = await avatar.read(MAX_AVATAR_BYTES + 1)
    finally:
        await avatar.close()
    if not data:
        raise BasicBadRequestError(MessageError(message="头像文件为空"))
    if len(data) > MAX_AVATAR_BYTES:
        raise PayloadTooLargeError(MessageError(message="头像不能超过 5 MB"))
    target_dir = settings.resolved_storage_root / "profiles" / user.id
    previous_path = _resolved_avatar_path(user, settings)
    try:
        publication = prepare_account_avatar_publication(
            data,
            target_directory=target_dir,
        )
    except ValueError as exc:
        raise BasicBadRequestError(MessageError(message=str(exc))) from exc
    try:
        publication.publish()
        persist_account_avatar(
            db,
            user_id=user.id,
            avatar_path=str(
                publication.published_path.relative_to(settings.resolved_storage_root)
            ),
            updated_at=db_timestamp(),
        )
    except Exception as exc:
        publication.discard()
        if isinstance(exc, OperationalError):
            _raise_avatar_update_deferred(exc)
        raise
    if previous_path is not None and previous_path != publication.published_path:
        _remove_unreferenced_avatar(previous_path, user_id=user.id)
    db.refresh(user)
    return UserResponse(
        data=UserPayload(user=AuthUser.model_validate(user.to_auth_view()))
    )


@router.get("/avatar", response_class=AvatarFileResponse)
def get_avatar(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    AvatarFileResponse,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user = _authenticated_user(db, request, settings)
    if user is None:
        raise BasicUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    path = _resolved_avatar_path(user, settings)
    if path is None or not path.is_file():
        raise BasicNotFoundError(MessageError(message="头像不存在"))
    response = AvatarFileResponse(path, media_type="image/webp")
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.delete("/avatar")
def delete_avatar(
    request: Request,
    db: Session = Depends(get_short_write_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    UserResponse,
    ErrorResponses(BasicUnauthorizedError, AvatarUpdateDeferredError),
]:
    user = _authenticated_user(db, request, settings)
    if user is None:
        raise BasicUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    path = _resolved_avatar_path(user, settings)
    try:
        persist_account_avatar(
            db,
            user_id=user.id,
            avatar_path=None,
            updated_at=db_timestamp(),
        )
    except OperationalError as exc:
        _raise_avatar_update_deferred(exc)
    if path is not None:
        _remove_unreferenced_avatar(path, user_id=user.id)
    db.refresh(user)
    return UserResponse(
        data=UserPayload(user=AuthUser.model_validate(user.to_auth_view()))
    )


@router.post("/password-reset/request", status_code=202)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    PasswordResetRequestResponse,
    ErrorResponses(BasicInternalError),
]:
    email = _normalized_email(payload.email)
    user = db.query(User).filter(func.lower(User.email) == email).one_or_none()
    if user is not None:
        now = db_timestamp()
        recent_cutoff = now - RESET_TOKEN_MIN_INTERVAL
        day_cutoff = now - timedelta(days=1)
        sent_recently = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at >= recent_cutoff,
            )
            .first()
        )
        sent_today = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at >= day_cutoff,
            )
            .count()
        )
        if sent_recently is None and sent_today < RESET_TOKEN_DAILY_LIMIT:
            raw_token = token_urlsafe(32)
            reset_token_id = cuid()
            reset_locale = configured_locale(db)
            persist_password_reset_request(
                db,
                token_id=reset_token_id,
                token_hash=hash_token(raw_token),
                user_id=user.id,
                expires_at=now + RESET_TOKEN_TTL,
                created_at=now,
            )
            reset_url = password_reset_url(_request_app_base_url(request), raw_token)
            try:
                write_password_reset_file(settings, reset_url, reset_locale)
            except OSError:
                LOGGER.exception("failed to write local password reset file")
                remove_password_reset_request(db, token_id=reset_token_id)
                raise BasicInternalError(
                    MessageError(message="无法在本地目录创建密码重置文件")
                )
    return PasswordResetRequestResponse(
        data=PasswordResetRequestPayload(
            accepted=True,
            message=RESET_REQUEST_MESSAGE,
            filePath=str(password_reset_file_path(settings)),
        )
    )


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    PasswordResetResponse,
    ErrorResponses(BasicBadRequestError),
]:
    now = db_timestamp()
    reset_token = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == hash_token(payload.token))
        .one_or_none()
    )
    if (
        reset_token is None
        or reset_token.used_at is not None
        or reset_token.expires_at <= now
    ):
        raise BasicBadRequestError(MessageError(message="重置链接无效或已过期"))

    user = db.query(User).filter(User.id == reset_token.user_id).one_or_none()
    if user is None:
        raise BasicBadRequestError(MessageError(message="重置链接无效或已过期"))
    password_hash = hash_password(payload.new_password)
    persist_confirmed_password_reset(
        db,
        user_id=user.id,
        password_hash=password_hash,
        confirmed_at=now,
    )
    try:
        password_reset_file_path(settings).unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("failed to remove used local password reset file", exc_info=True)
    delete_session_cookie(response, settings)
    return PasswordResetResponse(data=PasswordResetPayload())


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoggedOutResponse:
    raw_token = request.cookies.get("shuku_session")
    token_hash = hash_token(raw_token) if raw_token else None
    persist_logout(db, token_hash=token_hash)
    delete_session_cookie(response, settings)
    return LoggedOutResponse(data=LoggedOutPayload())
