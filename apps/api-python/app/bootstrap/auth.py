"""Authentication and user-management composition root."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, insert, update
from sqlalchemy.orm import Session

from app.core.auth import (
    prepare_invalid_sessions_delete,
    prepare_session_refresh,
    prepare_session_write,
    write_prepared_session,
    write_prepared_session_refresh,
)
from app.core.config import Settings
from app.models.auth import PasswordResetToken, User
from app.models.auth import Session as UserSession
from app.modules.auth.application.commands import AuthWriteTransaction
from app.modules.auth.application.password_authentication import AuthenticatePassword
from app.modules.auth.infrastructure.avatar_files import (
    PreparedAvatarPublication,
    prepare_avatar_publication,
)
from app.modules.auth.infrastructure.password_authentication import (
    BoundedPasswordVerificationGateway,
    SqlAlchemyUserCredentialReader,
)
from app.modules.auth.infrastructure.user_data import (
    list_library_ids,
    prepare_library_access,
    prepare_personal_user_deletion,
    prepare_user_preferences,
    prepare_user_with_preferences,
    validate_library_ids,
    write_prepared_library_access,
    write_prepared_personal_user_deletion,
    write_prepared_user_preferences,
    write_prepared_user_with_preferences,
)
from app.modules.system.public import PreparedSystemEvent
from app.services.system_events import write_prepared_system_events


def prepare_account_avatar_publication(
    data: bytes,
    *,
    target_directory: Path,
) -> PreparedAvatarPublication:
    """Compose the validated local avatar publication adapter."""

    return prepare_avatar_publication(data, target_directory=target_directory)


def persist_initial_setup(
    db: Session,
    *,
    user: User,
    preferences: dict[str, object],
    prepared_at: datetime,
    user_session: UserSession,
) -> None:
    prepared_user = prepare_user_with_preferences(
        user,
        preferences,
        prepared_at,
    )
    prepared_session = prepare_session_write(
        user_session,
        current_time=prepared_at,
    )
    with AuthWriteTransaction(db):
        write_prepared_user_with_preferences(db, prepared_user)
        write_prepared_session(db, prepared_session)


def persist_login_session(
    db: Session,
    *,
    user_session: UserSession,
    prepared_at: datetime,
) -> None:
    prepared_session = prepare_session_write(
        user_session,
        current_time=prepared_at,
    )
    with AuthWriteTransaction(db):
        write_prepared_session(db, prepared_session)


def persist_session_refresh(
    db: Session,
    *,
    token: str,
    current_time: datetime,
    expires_at: datetime,
) -> datetime | None:
    prepared_refresh = prepare_session_refresh(
        token,
        current_time=current_time,
        expires_at=expires_at,
    )
    with AuthWriteTransaction(db):
        refreshed = write_prepared_session_refresh(db, prepared_refresh)
    return refreshed


def persist_account_email(
    db: Session, *, user_id: str, email: str, updated_at: datetime
) -> None:
    statement = (
        update(User)
        .where(User.id == user_id)
        .values(email=email, updated_at=updated_at)
    )
    with AuthWriteTransaction(db):
        db.execute(statement)


def persist_account_name(
    db: Session, *, user_id: str, name: str, updated_at: datetime
) -> None:
    statement = (
        update(User).where(User.id == user_id).values(name=name, updated_at=updated_at)
    )
    with AuthWriteTransaction(db):
        db.execute(statement)


def persist_account_avatar(
    db: Session,
    *,
    user_id: str,
    avatar_path: str | None,
    updated_at: datetime,
) -> None:
    statement = (
        update(User)
        .where(User.id == user_id)
        .values(avatar_path=avatar_path, updated_at=updated_at)
    )
    with AuthWriteTransaction(db):
        db.execute(statement)


def persist_account_password(
    db: Session,
    *,
    user_id: str,
    password_hash: str,
    updated_at: datetime,
) -> None:
    user_statement = (
        update(User)
        .where(User.id == user_id)
        .values(password_hash=password_hash, updated_at=updated_at)
    )
    session_statement = delete(UserSession).where(UserSession.user_id == user_id)
    with AuthWriteTransaction(db):
        db.execute(user_statement)
        db.execute(session_statement)


def persist_password_reset_request(
    db: Session,
    *,
    token_id: str,
    token_hash: str,
    user_id: str,
    expires_at: datetime,
    created_at: datetime,
) -> None:
    expire_statement = (
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=created_at)
    )
    insert_statement = insert(PasswordResetToken).values(
        id=token_id,
        token_hash=token_hash,
        user_id=user_id,
        expires_at=expires_at,
        used_at=None,
        created_at=created_at,
    )
    with AuthWriteTransaction(db):
        db.execute(expire_statement)
        db.execute(insert_statement)


def remove_password_reset_request(db: Session, *, token_id: str) -> None:
    statement = delete(PasswordResetToken).where(PasswordResetToken.id == token_id)
    with AuthWriteTransaction(db):
        db.execute(statement)


def persist_confirmed_password_reset(
    db: Session,
    *,
    user_id: str,
    password_hash: str,
    confirmed_at: datetime,
) -> None:
    user_statement = (
        update(User)
        .where(User.id == user_id)
        .values(password_hash=password_hash, updated_at=confirmed_at)
    )
    token_statement = (
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=confirmed_at)
    )
    session_statement = delete(UserSession).where(UserSession.user_id == user_id)
    with AuthWriteTransaction(db):
        db.execute(user_statement)
        db.execute(token_statement)
        db.execute(session_statement)


def persist_logout(db: Session, *, token_hash: str | None) -> None:
    statement = (
        delete(UserSession).where(UserSession.token_hash == token_hash)
        if token_hash is not None
        else None
    )
    with AuthWriteTransaction(db):
        if statement is not None:
            db.execute(statement)


def delete_expired_or_disabled_sessions(
    db: Session,
    *,
    current_time: datetime,
) -> int:
    """Delete invalid sessions in one named maintenance transaction."""

    statement = prepare_invalid_sessions_delete(current_time=current_time)
    with AuthWriteTransaction(db):
        result = db.execute(statement)
    return int(result.rowcount or 0)


def persist_admin_user_create(
    db: Session,
    *,
    user: User,
    locale: str,
    folder_ids: list[str],
    prepared_at: datetime,
    event: PreparedSystemEvent,
) -> None:
    prepared_user = prepare_user_with_preferences(
        user,
        {"locale": locale},
        prepared_at,
    )
    prepared_folders = prepare_library_access(
        user.id,
        folder_ids,
        prepared_at,
    )
    with AuthWriteTransaction(db):
        write_prepared_user_with_preferences(db, prepared_user)
        write_prepared_library_access(db, prepared_folders)
        write_prepared_system_events(db, (event,))


def persist_admin_user_update(
    db: Session,
    *,
    user_id: str,
    user_values: dict[str, object],
    folder_ids: list[str] | None,
    locale: str | None,
    updated_at: datetime,
    disable_sessions: bool,
    event: PreparedSystemEvent,
) -> None:
    user_statement = update(User).where(User.id == user_id).values(**user_values)
    session_statement = delete(UserSession).where(UserSession.user_id == user_id)
    prepared_folders = (
        prepare_library_access(user_id, folder_ids, updated_at)
        if folder_ids is not None
        else None
    )
    prepared_preferences = (
        prepare_user_preferences(user_id, {"locale": locale}, updated_at)
        if locale is not None
        else None
    )
    with AuthWriteTransaction(db):
        db.execute(user_statement)
        if prepared_folders is not None:
            write_prepared_library_access(db, prepared_folders)
        if prepared_preferences is not None:
            write_prepared_user_preferences(db, prepared_preferences)
        if disable_sessions:
            db.execute(session_statement)
        write_prepared_system_events(db, (event,))


def persist_admin_password_reset(
    db: Session,
    *,
    user_id: str,
    password_hash: str,
    updated_at: datetime,
    event: PreparedSystemEvent,
) -> None:
    user_statement = (
        update(User)
        .where(User.id == user_id)
        .values(password_hash=password_hash, updated_at=updated_at)
    )
    session_statement = delete(UserSession).where(UserSession.user_id == user_id)
    with AuthWriteTransaction(db):
        db.execute(user_statement)
        db.execute(session_statement)
        write_prepared_system_events(db, (event,))


def persist_admin_user_delete(
    db: Session,
    *,
    user_id: str,
    anonymous_user_id: str,
    event: PreparedSystemEvent,
) -> None:
    delete_statement = delete(User).where(User.id == user_id)
    prepared_deletion = prepare_personal_user_deletion(
        db,
        user_id,
        anonymous_user_id,
    )
    with AuthWriteTransaction(db):
        write_prepared_personal_user_deletion(db, prepared_deletion)
        db.execute(delete_statement)
        write_prepared_system_events(db, (event,))


def persist_user_preferences(
    db: Session,
    *,
    user_id: str,
    preferences: dict[str, object],
    updated_at: datetime,
) -> None:
    prepared_preferences = prepare_user_preferences(
        user_id,
        preferences,
        updated_at,
    )
    with AuthWriteTransaction(db):
        write_prepared_user_preferences(db, prepared_preferences)


def build_password_authenticator(
    session: Session,
    runtime: BoundedPasswordVerificationGateway,
) -> AuthenticatePassword:
    return AuthenticatePassword(
        credential_reader=SqlAlchemyUserCredentialReader(session),
        password_verification=runtime,
    )


def build_password_authentication_runtime(
    settings: Settings,
) -> BoundedPasswordVerificationGateway:
    return BoundedPasswordVerificationGateway(
        success_ttl_seconds=settings.opds_auth_cache_ttl_seconds,
        success_capacity=settings.opds_auth_cache_capacity,
        pair_attempt_limit=settings.opds_auth_identity_failures,
        pair_window_seconds=settings.opds_auth_identity_window_seconds,
        address_attempt_limit=settings.opds_auth_ip_failures,
        address_window_seconds=settings.opds_auth_ip_window_seconds,
    )


__all__ = [
    "build_password_authentication_runtime",
    "build_password_authenticator",
    "delete_expired_or_disabled_sessions",
    "list_library_ids",
    "persist_account_avatar",
    "persist_account_email",
    "persist_account_name",
    "persist_account_password",
    "prepare_account_avatar_publication",
    "persist_admin_password_reset",
    "persist_admin_user_create",
    "persist_admin_user_delete",
    "persist_admin_user_update",
    "persist_confirmed_password_reset",
    "persist_initial_setup",
    "persist_login_session",
    "persist_logout",
    "persist_password_reset_request",
    "persist_session_refresh",
    "persist_user_preferences",
    "remove_password_reset_request",
    "validate_library_ids",
]
