"""ORM persistence for user administration routes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete, Update

from app.core.sql_batches import sqlite_parameter_chunks
from app.models import BookDetailPreference, LibraryOperation, ReaderResourceProgress
from app.models.auth import (
    PasswordResetToken,
    ReaderBookmark,
    User,
    UserLibraryAccess,
    UserPreference,
)
from app.models.auth import (
    Session as UserSession,
)
from app.models.import_pipeline import KindleSendTask
from app.models.settings import (
    ReaderBookPreference,
    ReaderPreference,
    ReaderProgressCursor,
    SystemEvent,
)
from app.models.shelf import Shelf, ShelfBook


@dataclass(frozen=True)
class PreparedUserPreferenceWrite:
    rows: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class PreparedUserInsert:
    user_values: dict[str, object]
    preferences: PreparedUserPreferenceWrite


@dataclass(frozen=True)
class PreparedLibraryAccessWrite:
    user_id: str
    rows: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class PreparedPersonalUserDeletion:
    statements: tuple[Delete | Update, ...]


def list_library_ids(db: Session, user_id: str) -> list[str]:
    rows = db.execute(
        select(UserLibraryAccess.library_id)
        .where(UserLibraryAccess.user_id == user_id)
        .order_by(UserLibraryAccess.library_id)
    ).scalars()
    return [str(item) for item in rows]


def validate_library_ids(db: Session, folder_ids: list[str]) -> list[str]:
    if not folder_ids:
        return []
    from app.models.library import Library

    existing = {
        str(item)
        for item in db.execute(
            select(Library.id).where(Library.id.in_(folder_ids))
        ).scalars()
    }
    missing = [folder_id for folder_id in folder_ids if folder_id not in existing]
    if missing:
        raise ValueError("包含不存在的书库")
    return folder_ids


def prepare_library_access(
    user_id: str,
    folder_ids: list[str],
    now: datetime,
) -> PreparedLibraryAccessWrite:
    rows = tuple(
        {
            "user_id": user_id,
            "library_id": folder_id,
            "created_at": now,
        }
        for folder_id in folder_ids
    )
    return PreparedLibraryAccessWrite(user_id=user_id, rows=rows)


def write_prepared_library_access(
    db: Session,
    prepared: PreparedLibraryAccessWrite,
) -> None:
    db.execute(
        delete(UserLibraryAccess).where(UserLibraryAccess.user_id == prepared.user_id)
    )
    if prepared.rows:
        for chunk in sqlite_parameter_chunks(
            prepared.rows,
            parameters_per_row=3,
        ):
            db.execute(insert(UserLibraryAccess), list(chunk))


def _prepare_user_preference_rows(
    user_id: str,
    preferences: dict[str, object],
    now: datetime,
) -> PreparedUserPreferenceWrite:
    rows = tuple(
        {
            "user_id": user_id,
            "key": key,
            "value": json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "created_at": now,
            "updated_at": now,
        }
        for key, value in preferences.items()
    )
    return PreparedUserPreferenceWrite(rows=rows)


def _write_user_preference_rows(
    db: Session,
    prepared: PreparedUserPreferenceWrite,
) -> None:
    if not prepared.rows:
        return
    statement = sqlite_insert(UserPreference)
    upsert = statement.on_conflict_do_update(
        index_elements=[UserPreference.user_id, UserPreference.key],
        set_={
            UserPreference.value: statement.excluded.value,
            UserPreference.updated_at: statement.excluded["updatedAt"],
        },
    )
    for chunk in sqlite_parameter_chunks(
        prepared.rows,
        parameters_per_row=5,
    ):
        db.execute(upsert, list(chunk))


def prepare_user_preferences(
    user_id: str,
    preferences: dict[str, object],
    now: datetime,
) -> PreparedUserPreferenceWrite:
    return _prepare_user_preference_rows(user_id, preferences, now)


def write_prepared_user_preferences(
    db: Session,
    prepared: PreparedUserPreferenceWrite,
) -> None:
    _write_user_preference_rows(db, prepared)


def prepare_user_with_preferences(
    user: User,
    preferences: dict[str, object],
    now: datetime,
) -> PreparedUserInsert:
    preference_write = _prepare_user_preference_rows(user.id, preferences, now)
    user_values = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "password_hash": user.password_hash,
        "avatar_path": user.avatar_path,
        "role": user.role or "member",
        "status": user.status or "active",
        "can_manage_system": bool(user.can_manage_system),
        "can_view_manual_imports": bool(user.can_view_manual_imports),
        "authz_version": user.authz_version or 1,
        "created_at": user.created_at or now,
        "updated_at": user.updated_at or now,
    }
    return PreparedUserInsert(
        user_values=user_values,
        preferences=preference_write,
    )


def write_prepared_user_with_preferences(
    db: Session,
    prepared: PreparedUserInsert,
) -> None:
    db.execute(insert(User).values(prepared.user_values))
    _write_user_preference_rows(db, prepared.preferences)


def prepare_personal_user_deletion(
    db: Session,
    user_id: str,
    anonymous_user_id: str,
) -> PreparedPersonalUserDeletion:
    """Prepare deletion of all account-owned rows in the fresh schema."""

    statements: list[Delete | Update] = []
    statements.append(
        delete(ShelfBook).where(
            ShelfBook.shelf_id.in_(
                select(Shelf.id).where(Shelf.owner_user_id == user_id)
            )
        )
    )
    statements.append(delete(Shelf).where(Shelf.owner_user_id == user_id))
    for model in (
        ReaderBookmark,
        BookDetailPreference,
        ReaderResourceProgress,
        ReaderProgressCursor,
        ReaderBookPreference,
        ReaderPreference,
        UserPreference,
        UserLibraryAccess,
        PasswordResetToken,
        UserSession,
    ):
        statements.append(delete(model).where(model.user_id == user_id))
    for model in (KindleSendTask, LibraryOperation):
        statements.append(
            update(model).where(model.user_id == user_id).values(user_id=None)
        )
    statements.append(
        update(SystemEvent)
        .where(SystemEvent.actor_id == user_id)
        .values(actor_id=anonymous_user_id)
    )
    statements.append(
        update(SystemEvent)
        .where(SystemEvent.target_id == user_id)
        .values(target_id=anonymous_user_id)
    )
    return PreparedPersonalUserDeletion(statements=tuple(statements))


def write_prepared_personal_user_deletion(
    db: Session,
    prepared: PreparedPersonalUserDeletion,
) -> None:
    for statement in prepared.statements:
        db.execute(statement)
