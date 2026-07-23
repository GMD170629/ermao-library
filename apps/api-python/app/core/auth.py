from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_hex
from hmac import compare_digest
import hashlib

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.auth import Session as UserSession
from app.models.auth import User

COOKIE_NAME = "shuku_session"
SESSION_DAYS = 30
SESSION_REFRESH_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def session_expiry() -> datetime:
    return utcnow() + timedelta(days=SESSION_DAYS)


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1, dklen=64).hex()
    return f"{salt}:{digest}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split(":", 1)
    if len(parts) != 2:
        return False
    salt, expected = parts
    if not salt or not expected:
        return False
    try:
        candidate = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1, dklen=64).hex()
    except ValueError:
        return False
    return compare_digest(candidate, expected)


def set_session_cookie(response: Response, token: str, expires_at: datetime, settings: Settings) -> None:
    normalized_expires_at = _normalize_db_datetime(expires_at)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path=settings.cookie_path,
        expires=normalized_expires_at,
    )


def create_session(db: Session, user_id: str) -> tuple[UserSession, str]:
    token = token_hex(32)
    expires_at = session_expiry()
    user_session = UserSession(token_hash=hash_token(token), user_id=user_id, expires_at=expires_at)
    db.add(user_session)
    db.commit()
    db.refresh(user_session)
    return user_session, token


def _normalize_db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def get_current_user(db: Session, request: Request, settings: Settings) -> tuple[User | None, str | None, datetime | None]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None, None, None

    user_session = db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).one_or_none()
    if user_session is None or _normalize_db_datetime(user_session.expires_at) <= utcnow():
        return None, None, None
    if getattr(user_session.user, "status", "active") != "active":
        db.delete(user_session)
        db.commit()
        return None, None, None

    refreshed_expires_at = None
    if _normalize_db_datetime(user_session.expires_at) - utcnow() < timedelta(days=SESSION_REFRESH_DAYS):
        user_session.expires_at = session_expiry()
        db.add(user_session)
        db.commit()
        refreshed_expires_at = user_session.expires_at

    return user_session.user, token, refreshed_expires_at


def clear_session_cookie(db: Session, request: Request, settings: Settings) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).delete()
        db.commit()


def delete_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE_NAME, path=settings.cookie_path, secure=settings.secure_cookies, httponly=True, samesite="lax")
