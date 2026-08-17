"""Cross-capability SQLAlchemy adapters for Catalog authorization."""

from __future__ import annotations

from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from app.modules.auth.infrastructure.persistence.models import CurrentUser
from app.modules.catalog.application.ports import (
    SystemCreateLibraryPolicy,
    UserAuthorizationPort,
)
from app.modules.catalog.domain.errors import (
    GrantTargetNotFound,
    LibraryCreateDenied,
)


class SqlAlchemyCatalogUserAuthorization(UserAuthorizationPort):
    """Catalog's user checks against the Auth-owned current user table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_active_user(self, user_id: str) -> None:
        row = self._session.scalar(select(CurrentUser).where(CurrentUser.id == user_id))
        if row is None or row.status != "active":
            raise GrantTargetNotFound()

    def ensure_can_create_library(self, user_id: str) -> None:
        row = self._session.scalar(select(CurrentUser).where(CurrentUser.id == user_id))
        if row is None or row.status != "active" or row.role != "admin":
            raise LibraryCreateDenied()

    def increment_authz_version(self, user_id: str) -> None:
        result = self._session.execute(
            update(CurrentUser)
            .where(CurrentUser.id == user_id)
            .values(
                authz_version=CurrentUser.authz_version + 1,
                updated_at=func.current_timestamp(),
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            raise GrantTargetNotFound()


class SqlAlchemyCatalogCreatePolicy(SystemCreateLibraryPolicy):
    """Preflight create authorization using an independent read session."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def authorize(self, actor_id: str) -> None:
        with self._session_factory() as session:
            row = session.scalar(select(CurrentUser).where(CurrentUser.id == actor_id))
            if row is None or row.status != "active" or row.role != "admin":
                raise LibraryCreateDenied()


__all__ = ["SqlAlchemyCatalogCreatePolicy", "SqlAlchemyCatalogUserAuthorization"]
