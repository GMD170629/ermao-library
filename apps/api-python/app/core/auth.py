from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from secrets import token_hex
from typing import Any, cast

from fastapi import Request, Response
from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete, Update

from app.core.config import Settings
from app.models.auth import Session as UserSession
from app.models.auth import User, cuid

COOKIE_NAME = "shuku_session"
SESSION_DAYS = 30
SESSION_REFRESH_DAYS = 7


@dataclass(frozen=True)
class PreparedSessionWrite:
    session_values: dict[str, object]
    invalid_sessions_statement: Delete


@dataclass(frozen=True)
class PreparedSessionRefresh:
    refresh_statement: Update
    invalid_sessions_statement: Delete
    expires_at: datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def session_expiry() -> datetime:
    return utcnow() + timedelta(days=SESSION_DAYS)


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1, dklen=64
    ).hex()
    return f"{salt}:{digest}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split(":", 1)
    if len(parts) != 2:
        return False
    salt, expected = parts
    if not salt or not expected:
        return False
    try:
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=16384,
            r=8,
            p=1,
            dklen=64,
        ).hex()
    except ValueError:
        return False
    return compare_digest(candidate, expected)


def set_session_cookie(
    response: Response, token: str, expires_at: datetime, settings: Settings
) -> None:
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
    user_session, token = prepare_session(user_id)
    current_time = utcnow()
    prepared = prepare_session_write(user_session, current_time=current_time)
    write_prepared_session(db, prepared)
    return user_session, token


def prepare_session(
    user_id: str,
    *,
    current_time: datetime | None = None,
    expires_at: datetime | None = None,
) -> tuple[UserSession, str]:
    prepared_at = current_time or utcnow()
    token = token_hex(32)
    user_session = UserSession(
        id=cuid(),
        token_hash=hash_token(token),
        user_id=user_id,
        expires_at=expires_at or prepared_at + timedelta(days=SESSION_DAYS),
        created_at=prepared_at,
        updated_at=prepared_at,
    )
    return user_session, token


def prepare_session_write(
    user_session: UserSession,
    *,
    current_time: datetime,
) -> PreparedSessionWrite:
    session_values = {
        "id": user_session.id,
        "token_hash": user_session.token_hash,
        "user_id": user_session.user_id,
        "expires_at": user_session.expires_at,
        "created_at": user_session.created_at,
        "updated_at": user_session.updated_at,
    }
    return PreparedSessionWrite(
        session_values=session_values,
        invalid_sessions_statement=prepare_invalid_sessions_delete(
            current_time=current_time
        ),
    )


def write_prepared_session(db: Session, prepared: PreparedSessionWrite) -> None:
    db.execute(prepared.invalid_sessions_statement)
    db.execute(insert(UserSession).values(prepared.session_values))


def delete_invalid_sessions(
    db: Session,
    *,
    current_time: datetime,
    exclude_token_hash: str | None = None,
) -> int:
    statement = prepare_invalid_sessions_delete(
        current_time=current_time,
        exclude_token_hash=exclude_token_hash,
    )
    result = cast(CursorResult[Any], db.execute(statement))
    return int(result.rowcount or 0)


def prepare_invalid_sessions_delete(
    *,
    current_time: datetime,
    exclude_token_hash: str | None = None,
) -> Delete:
    invalid_user_ids = select(User.id).where(User.status != "active")
    conditions = [
        or_(
            UserSession.expires_at <= current_time,
            UserSession.user_id.in_(invalid_user_ids),
        )
    ]
    if exclude_token_hash is not None:
        conditions.append(UserSession.token_hash != exclude_token_hash)
    return (
        delete(UserSession)
        .where(*conditions)
        .execution_options(synchronize_session=False)
    )


def _normalize_db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def get_current_user(
    db: Session, request: Request, settings: Settings
) -> tuple[User | None, str | None, datetime | None]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None, None, None

    user_session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == hash_token(token))
        .one_or_none()
    )
    now = utcnow()
    normalized_expiry = (
        _normalize_db_datetime(user_session.expires_at)
        if user_session is not None
        else None
    )
    if user_session is None or normalized_expiry is None or normalized_expiry <= now:
        return None, None, None
    if getattr(user_session.user, "status", "active") != "active":
        return None, None, None

    refresh_required_at = None
    if normalized_expiry - now < timedelta(days=SESSION_REFRESH_DAYS):
        refresh_required_at = normalized_expiry

    return user_session.user, token, refresh_required_at


def refresh_current_session(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
    expires_at: datetime | None = None,
) -> datetime | None:
    """Refresh one active session and prune invalid sessions in one SQL-only write."""

    prepared = prepare_session_refresh(
        token,
        current_time=now or utcnow(),
        expires_at=expires_at or session_expiry(),
    )
    return write_prepared_session_refresh(db, prepared)


def prepare_session_refresh(
    token: str,
    *,
    current_time: datetime,
    expires_at: datetime,
) -> PreparedSessionRefresh:
    token_digest = hash_token(token)
    active_user_ids = select(User.id).where(User.status == "active")
    refresh_statement = (
        update(UserSession)
        .where(
            UserSession.token_hash == token_digest,
            UserSession.expires_at > current_time,
            UserSession.user_id.in_(active_user_ids),
        )
        .values(expires_at=expires_at, updated_at=current_time)
        .returning(UserSession.id)
        .execution_options(synchronize_session=False)
    )
    return PreparedSessionRefresh(
        refresh_statement=refresh_statement,
        invalid_sessions_statement=prepare_invalid_sessions_delete(
            current_time=current_time,
            exclude_token_hash=token_digest,
        ),
        expires_at=expires_at,
    )


def write_prepared_session_refresh(
    db: Session,
    prepared: PreparedSessionRefresh,
) -> datetime | None:
    refreshed_id = db.scalar(prepared.refresh_statement)
    db.execute(prepared.invalid_sessions_statement)
    return prepared.expires_at if refreshed_id is not None else None


def clear_session_cookie(db: Session, request: Request, settings: Settings) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.query(UserSession).filter(
            UserSession.token_hash == hash_token(token)
        ).delete()


def delete_session_by_token_hash(db: Session, token_hash: str | None) -> None:
    if token_hash is None:
        return
    db.execute(delete(UserSession).where(UserSession.token_hash == token_hash))


def delete_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path=settings.cookie_path,
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
