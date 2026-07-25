from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.accounts.contracts import (
    AccessScope,
    AccountsRepository,
    AccountView,
    PasswordResetsRepository,
    SessionsRepository,
)
from appv2.modules.accounts.infrastructure.models import (
    AccountPreferenceRecord,
    PasswordResetRecord,
    SessionRecord,
    UserRecord,
)


def _view(record: UserRecord) -> AccountView:
    return AccountView(
        id=record.id,
        email=record.email,
        display_name=record.display_name,
        role=record.role,
        locale=record.locale,
        scopes=frozenset(AccessScope(scope) for scope in record.scopes),
        disabled=record.disabled_at is not None,
        monitor_folder_ids=tuple(uuid.UUID(value) for value in record.monitor_folder_ids),
        created_at=record.created_at,
    )


class SqlAccountsRepository(AccountsRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def count_users(self) -> int:
        return int(self._session.scalar(select(func.count()).select_from(UserRecord)) or 0)

    def get_user(self, user_id: uuid.UUID) -> AccountView | None:
        record = self._session.get(UserRecord, user_id)
        return _view(record) if record is not None and record.disabled_at is None else None

    def get_user_by_email(self, email: str) -> AccountView | None:
        record = self._session.scalar(
            select(UserRecord).where(UserRecord.email == email, UserRecord.disabled_at.is_(None))
        )
        return _view(record) if record is not None else None

    def email_in_use(self, email: str, *, excluding: uuid.UUID | None = None) -> bool:
        query = select(func.count()).select_from(UserRecord).where(UserRecord.email == email)
        if excluding is not None:
            query = query.where(UserRecord.id != excluding)
        return bool(self._session.scalar(query))

    def password_hash_for(self, user_id: uuid.UUID) -> str | None:
        return self._session.scalar(
            select(UserRecord.password_hash).where(
                UserRecord.id == user_id, UserRecord.disabled_at.is_(None)
            )
        )

    def add_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        role: str,
        locale: str,
        scopes: frozenset[AccessScope],
        monitor_folder_ids: tuple[uuid.UUID, ...] = (),
    ) -> AccountView:
        record = UserRecord(
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
            locale=locale,
            scopes=sorted(scope.value for scope in scopes),
            monitor_folder_ids=[str(value) for value in monitor_folder_ids],
        )
        self._session.add(record)
        self._session.flush()
        return _view(record)

    def update_user(
        self,
        user_id: uuid.UUID,
        *,
        email: str | None = None,
        display_name: str | None = None,
        password_hash: str | None = None,
        locale: str | None = None,
        role: str | None = None,
        scopes: frozenset[AccessScope] | None = None,
        disabled: bool | None = None,
        monitor_folder_ids: tuple[uuid.UUID, ...] | None = None,
    ) -> AccountView | None:
        record = self._session.get(UserRecord, user_id)
        if record is None or record.disabled_at is not None:
            return None
        if email is not None:
            record.email = email
        if display_name is not None:
            record.display_name = display_name
        if password_hash is not None:
            record.password_hash = password_hash
        if locale is not None:
            record.locale = locale
        if role is not None:
            record.role = role
        if scopes is not None:
            record.scopes = sorted(scope.value for scope in scopes)
        if disabled is not None:
            record.disabled_at = datetime.now(UTC) if disabled else None
        if monitor_folder_ids is not None:
            record.monitor_folder_ids = [str(value) for value in monitor_folder_ids]
        self._session.flush()
        return _view(record)

    def list_users(self, *, offset: int, limit: int) -> tuple[list[AccountView], int]:
        total = int(self._session.scalar(select(func.count()).select_from(UserRecord)) or 0)
        records = self._session.scalars(
            select(UserRecord)
            .order_by(UserRecord.created_at, UserRecord.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [_view(record) for record in records], total

    def delete_user(self, user_id: uuid.UUID) -> bool:
        record = self._session.get(UserRecord, user_id)
        if record is None or record.disabled_at is not None:
            return False
        record.disabled_at = datetime.now(UTC)
        self._session.flush()
        return True

    def preferences(self, user_id: uuid.UUID) -> dict[str, object]:
        records = self._session.scalars(
            select(AccountPreferenceRecord)
            .where(AccountPreferenceRecord.user_id == user_id)
            .order_by(AccountPreferenceRecord.key)
        ).all()
        return {record.key: record.value for record in records}

    def save_preferences(
        self,
        user_id: uuid.UUID,
        values: dict[str, object],
    ) -> dict[str, object]:
        existing = {
            record.key: record
            for record in self._session.scalars(
                select(AccountPreferenceRecord).where(
                    AccountPreferenceRecord.user_id == user_id,
                    AccountPreferenceRecord.key.in_(values),
                )
            ).all()
        }
        for key, value in values.items():
            record = existing.get(key)
            if record is None:
                self._session.add(
                    AccountPreferenceRecord(
                        user_id=user_id,
                        key=key,
                        value=value,
                    )
                )
            else:
                record.value = value
        self._session.flush()
        return self.preferences(user_id)


class SqlSessionsRepository(SessionsRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> None:
        now = datetime.now(UTC)
        self._session.add(
            SessionRecord(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=now,
                last_seen_at=now,
            )
        )
        self._session.flush()

    def account_for(self, *, token_hash: str, now: datetime) -> AccountView | None:
        row = self._session.execute(
            select(SessionRecord, UserRecord)
            .join(UserRecord, UserRecord.id == SessionRecord.user_id)
            .where(
                SessionRecord.token_hash == token_hash,
                SessionRecord.expires_at > now,
                UserRecord.disabled_at.is_(None),
            )
        ).one_or_none()
        if row is None:
            return None
        session, user = row
        session.last_seen_at = now
        return _view(user)

    def revoke(self, token_hash: str) -> bool:
        record = self._session.scalar(
            select(SessionRecord).where(SessionRecord.token_hash == token_hash)
        )
        if record is None:
            return False
        self._session.delete(record)
        return True

    def revoke_user(self, user_id: uuid.UUID) -> None:
        self._session.execute(delete(SessionRecord).where(SessionRecord.user_id == user_id))


class SqlPasswordResetsRepository(PasswordResetsRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def issue(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        created_at: datetime,
    ) -> None:
        self._session.execute(
            delete(PasswordResetRecord).where(PasswordResetRecord.user_id == user_id)
        )
        self._session.add(
            PasswordResetRecord(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=created_at,
            )
        )
        self._session.flush()

    def consume(self, *, token_hash: str, now: datetime) -> uuid.UUID | None:
        record = self._session.scalar(
            select(PasswordResetRecord)
            .where(
                PasswordResetRecord.token_hash == token_hash,
                PasswordResetRecord.consumed_at.is_(None),
                PasswordResetRecord.expires_at > now,
            )
            .with_for_update()
        )
        if record is None:
            return None
        record.consumed_at = now
        self._session.flush()
        return record.user_id


class AccountsSqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.accounts: AccountsRepository
        self.sessions: SessionsRepository
        self.password_resets: PasswordResetsRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.accounts = SqlAccountsRepository(self._session)
        self.sessions = SqlSessionsRepository(self._session)
        self.password_resets = SqlPasswordResetsRepository(self._session)
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        if self._session is None:
            return False
        try:
            if exc_type is not None or not self._committed:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None
        return False

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before commit")
        self._session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before rollback")
        self._session.rollback()


def accounts_uow_factory(
    session_factory: sessionmaker[Session],
) -> Callable[[], AccountsSqlUnitOfWork]:
    return lambda: AccountsSqlUnitOfWork(session_factory)
