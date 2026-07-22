from __future__ import annotations

from datetime import timedelta
from io import BytesIO
import logging
import os
from pathlib import Path
from secrets import token_hex, token_urlsafe

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import (
    clear_session_cookie,
    create_session,
    delete_session_cookie,
    get_current_user,
    hash_password,
    hash_token,
    set_session_cookie,
    verify_password,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import PasswordResetToken, Session as UserSession, User, cuid, db_timestamp
from app.schemas.auth import (
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SetupRequest,
    UpdateEmailRequest,
    UpdatePasswordRequest,
)
from app.schemas.responses import fail, ok
from app.services.password_reset_file import password_reset_file_path, password_reset_url, write_password_reset_file

router = APIRouter()
LOGGER = logging.getLogger(__name__)

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 25_000_000
AVATAR_SIZE = 512
RESET_TOKEN_MIN_INTERVAL = timedelta(seconds=60)
RESET_TOKEN_DAILY_LIMIT = 5
RESET_TOKEN_TTL = timedelta(minutes=30)
RESET_REQUEST_MESSAGE = "如果该邮箱已绑定账户，密码重置文件已在本地目录创建。"
ALLOWED_AVATAR_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_AVATAR_FORMATS = {"JPEG", "PNG", "WEBP"}


def _normalized_email(value: object) -> str:
    return str(value).strip().lower()


def _authenticated_user(db: Session, request: Request, settings: Settings) -> User | None:
    user, _token, _refreshed_expires_at = get_current_user(db, request, settings)
    return user


def _request_app_base_url(request: Request) -> str:
    referer = request.headers.get("referer", "").strip()
    if referer:
        from urllib.parse import urlsplit, urlunsplit

        parsed = urlsplit(referer)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            path = parsed.path.rstrip("/")
            if path.endswith("/forgot-password"):
                path = path[: -len("/forgot-password")]
            return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    forwarded_proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
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


def _process_avatar(data: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(data)) as probe:
            if probe.format not in ALLOWED_AVATAR_FORMATS:
                raise ValueError("不支持的头像格式")
            if probe.width * probe.height > MAX_AVATAR_PIXELS:
                raise ValueError("头像像素尺寸过大")
            probe.verify()
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_AVATAR_PIXELS:
                raise ValueError("头像像素尺寸过大")
            normalized = ImageOps.exif_transpose(source).convert("RGB")
            return ImageOps.fit(
                normalized,
                (AVATAR_SIZE, AVATAR_SIZE),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError("头像文件不是有效的图片") from exc


@router.get("/capabilities")
def capabilities(settings: Settings = Depends(get_settings)):
    return ok({"localPasswordReset": True, "passwordResetFilePath": str(password_reset_file_path(settings))})


@router.get("/setup/status")
def setup_status(db: Session = Depends(get_db)):
    response = ok({"initialized": db.query(User.id).first() is not None})
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/setup", status_code=201)
def setup(payload: SetupRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    email = _normalized_email(payload.email)
    user_id = cuid()
    now = db_timestamp()
    inserted = db.execute(
        text(
            """
            INSERT INTO `User` (`id`, `email`, `name`, `passwordHash`, `role`, `createdAt`, `updatedAt`)
            SELECT :id, :email, :name, :password_hash, 'admin', :now, :now
            WHERE NOT EXISTS (SELECT 1 FROM `User` LIMIT 1)
            """
        ),
        {
            "id": user_id,
            "email": email,
            "name": "管理员",
            "password_hash": hash_password(payload.password),
            "now": now,
        },
    )
    if inserted.rowcount != 1:
        db.rollback()
        return fail("系统已经完成初始化，请直接登录", status_code=409)

    db.commit()
    user = db.get(User, user_id)
    if user is None:
        return fail("账户创建失败", status_code=500)

    user_session, token = create_session(db, user.id)
    response = ok({"initialized": True, "user": user.to_auth_view()}, status_code=201)
    response.headers["Cache-Control"] = "no-store"
    set_session_cookie(response, token, user_session.expires_at, settings)
    return response


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    email = _normalized_email(payload.email)
    user = db.query(User).filter(func.lower(User.email) == email).one_or_none()
    if user is None and db.query(User.id).first() is None:
        return fail("系统尚未初始化", status_code=409, details={"code": "SETUP_REQUIRED"})
    if user is None or not verify_password(payload.password, user.password_hash):
        return fail("邮箱或密码不正确", status_code=401)

    user_session, token = create_session(db, user.id)
    response = ok({"user": user.to_auth_view()})
    set_session_cookie(response, token, user_session.expires_at, settings)
    return response


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, token, refreshed_expires_at = get_current_user(db, request, settings)
    if user is None:
        response = fail("UNAUTHORIZED", status_code=401)
        delete_session_cookie(response, settings)
        return response
    response = ok({"user": user.to_auth_view()})
    if token is not None and refreshed_expires_at is not None:
        set_session_cookie(response, token, refreshed_expires_at, settings)
    return response


@router.patch("/account/email")
def update_email(
    payload: UpdateEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = _authenticated_user(db, request, settings)
    if user is None:
        return fail("UNAUTHORIZED", status_code=401)
    if not verify_password(payload.current_password, user.password_hash):
        return fail("当前密码不正确", status_code=400)

    email = _normalized_email(payload.email)
    duplicate = db.query(User).filter(func.lower(User.email) == email, User.id != user.id).first()
    if duplicate is not None:
        return fail("该邮箱已被使用", status_code=409)

    user.email = email
    user.updated_at = db_timestamp()
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return fail("该邮箱已被使用", status_code=409)
    db.refresh(user)
    return ok({"user": user.to_auth_view()})


@router.patch("/account/password")
def update_password(
    payload: UpdatePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = _authenticated_user(db, request, settings)
    if user is None:
        return fail("UNAUTHORIZED", status_code=401)
    if not verify_password(payload.current_password, user.password_hash):
        return fail("当前密码不正确", status_code=400)
    if verify_password(payload.new_password, user.password_hash):
        return fail("新密码不能与当前密码相同", status_code=400)

    user.password_hash = hash_password(payload.new_password)
    user.updated_at = db_timestamp()
    db.add(user)
    db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    response = ok({"passwordChanged": True, "requiresLogin": True})
    delete_session_cookie(response, settings)
    return response


@router.post("/avatar")
async def upload_avatar(
    request: Request,
    avatar: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = _authenticated_user(db, request, settings)
    if user is None:
        return fail("UNAUTHORIZED", status_code=401)
    if (avatar.content_type or "").lower() not in ALLOWED_AVATAR_CONTENT_TYPES:
        return fail("仅支持 JPEG、PNG 或 WebP 头像", status_code=400)

    try:
        data = await avatar.read(MAX_AVATAR_BYTES + 1)
    finally:
        await avatar.close()
    if not data:
        return fail("头像文件为空", status_code=400)
    if len(data) > MAX_AVATAR_BYTES:
        return fail("头像不能超过 5 MB", status_code=413)
    try:
        processed = _process_avatar(data)
    except ValueError as exc:
        return fail(str(exc), status_code=400)

    target_dir = settings.resolved_storage_root / "profiles" / user.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "avatar.webp"
    temporary = target_dir / f".avatar-{token_hex(6)}.webp"
    try:
        processed.save(temporary, format="WEBP", quality=88, method=6)
        os.replace(temporary, target)
    finally:
        processed.close()
        temporary.unlink(missing_ok=True)

    user.avatar_path = str(target.relative_to(settings.resolved_storage_root))
    user.updated_at = db_timestamp()
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok({"user": user.to_auth_view()})


@router.get("/avatar")
def get_avatar(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user = _authenticated_user(db, request, settings)
    if user is None:
        return fail("UNAUTHORIZED", status_code=401)
    path = _resolved_avatar_path(user, settings)
    if path is None or not path.is_file():
        return fail("头像不存在", status_code=404)
    response = FileResponse(path, media_type="image/webp")
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.delete("/avatar")
def delete_avatar(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user = _authenticated_user(db, request, settings)
    if user is None:
        return fail("UNAUTHORIZED", status_code=401)
    path = _resolved_avatar_path(user, settings)
    if path is not None:
        path.unlink(missing_ok=True)
    user.avatar_path = None
    user.updated_at = db_timestamp()
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok({"user": user.to_auth_view()})


@router.post("/password-reset/request", status_code=202)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = _normalized_email(payload.email)
    user = db.query(User).filter(func.lower(User.email) == email).one_or_none()
    if user is not None:
        now = db_timestamp()
        recent_cutoff = now - RESET_TOKEN_MIN_INTERVAL
        day_cutoff = now - timedelta(days=1)
        sent_recently = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at >= recent_cutoff,
        ).first()
        sent_today = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at >= day_cutoff,
        ).count()
        if sent_recently is None and sent_today < RESET_TOKEN_DAILY_LIMIT:
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
            raw_token = token_urlsafe(32)
            reset_token = PasswordResetToken(
                token_hash=hash_token(raw_token),
                user_id=user.id,
                expires_at=now + RESET_TOKEN_TTL,
            )
            db.add(reset_token)
            db.commit()
            reset_url = password_reset_url(_request_app_base_url(request), raw_token)
            try:
                write_password_reset_file(settings, reset_url)
            except OSError:
                LOGGER.exception("failed to write local password reset file")
                db.delete(reset_token)
                db.commit()
                return fail("无法在本地目录创建密码重置文件", status_code=500)
    return ok(
        {
            "accepted": True,
            "message": RESET_REQUEST_MESSAGE,
            "filePath": str(password_reset_file_path(settings)),
        },
        status_code=202,
    )


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    now = db_timestamp()
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_token(payload.token)).one_or_none()
    if reset_token is None or reset_token.used_at is not None or reset_token.expires_at <= now:
        return fail("重置链接无效或已过期", status_code=400)

    user = db.query(User).filter(User.id == reset_token.user_id).one_or_none()
    if user is None:
        return fail("重置链接无效或已过期", status_code=400)
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = now
    db.add(user)
    reset_token.used_at = now
    db.add(reset_token)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.id != reset_token.id,
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    try:
        password_reset_file_path(settings).unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("failed to remove used local password reset file", exc_info=True)
    response = ok({"passwordReset": True})
    delete_session_cookie(response, settings)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    clear_session_cookie(db, request, settings)
    response = ok({"loggedOut": True})
    delete_session_cookie(response, settings)
    return response
