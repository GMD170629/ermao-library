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
    SessionsRepository,
)
from appv2.modules.accounts.infrastructure.models import SessionRecord, UserRecord


def _view(record: UserRecord) -> AccountView:
    return AccountView(
        id=record.id,
        email=record.email,
        display_name=record.display_name,
        role=record.role,
        locale=record.locale,
        scopes=frozenset(AccessScope(scope) for scope in record.scopes),
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
    ) -> AccountView:
        record = UserRecord(
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
            locale=locale,
            scopes=sorted(scope.value for scope in scopes),
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
        self._session.flush()
        return _view(record)

    def list_users(self, *, offset: int, limit: int) -> tuple[list[AccountView], int]:
        criteria = UserRecord.disabled_at.is_(None)
        total = int(
            self._session.scalar(select(func.count()).select_from(UserRecord).where(criteria)) or 0
        )
        records = self._session.scalars(
            select(UserRecord)
            .where(criteria)
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


class AccountsSqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.accounts: AccountsRepository
        self.sessions: SessionsRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.accounts = SqlAccountsRepository(self._session)
        self.sessions = SqlSessionsRepository(self._session)
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
