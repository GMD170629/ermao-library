"""SQLAlchemy adapter for the first-administrator use case."""

from __future__ import annotations

from types import TracebackType
from typing import Literal, Self

from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransaction

from app.modules.auth.application.first_admin import (
    FirstAdministratorRepository,
    FirstAdministratorUnitOfWork,
    NewAdministrator,
)
from app.modules.auth.domain.first_admin import FirstAdministratorAlreadyInitialized
from app.modules.auth.infrastructure.persistence.models import (
    CurrentAuthIdentity,
    CurrentUser,
)
from app.modules.system.infrastructure.persistence import SystemInstance


class SqlAlchemyFirstAdministratorRepository(FirstAdministratorRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def has_users(self) -> bool:
        return self._session.scalar(select(CurrentUser.id).limit(1)) is not None

    def identity_bootstrap_completed(self) -> bool:
        system = self._session.get(SystemInstance, 1)
        return system is not None and system.identity_bootstrap_completed_at is not None

    def add_first_administrator(self, administrator: NewAdministrator) -> None:
        system = self._session.get(SystemInstance, 1)
        if system is None:
            system = SystemInstance(id=1)
            self._session.add(system)

        if system.identity_bootstrap_completed_at is not None:
            raise FirstAdministratorAlreadyInitialized()

        self._session.add(
            CurrentUser(
                id=administrator.user_id,
                authz_version=1,
                display_name=administrator.display_name,
                role="admin",
                status="active",
                created_at=administrator.created_at,
                updated_at=administrator.created_at,
            )
        )
        self._session.flush()

        self._session.add(
            CurrentAuthIdentity(
                id=administrator.identity_id,
                user_id=administrator.user_id,
                provider="PASSWORD",
                subject=administrator.normalized_email,
                password_hash=administrator.password_hash,
                created_at=administrator.created_at,
                updated_at=administrator.created_at,
            )
        )
        system.identity_bootstrap_completed_at = administrator.created_at
        self._session.flush()


class SqlAlchemyFirstAdministratorUnitOfWork(FirstAdministratorUnitOfWork):
    """Own the explicit transaction used by one bootstrap command."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.repository = SqlAlchemyFirstAdministratorRepository(session)
        self._transaction: SessionTransaction | None = None

    def __enter__(self) -> Self:
        self._transaction = self._session.begin()
        self._transaction.__enter__()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            if self._transaction is None:
                return False
            self._transaction.__exit__(exception_type, exception, traceback)
            return False
        finally:
            self._session.close()
