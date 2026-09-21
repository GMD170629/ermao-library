"""Current library IDs for an automation grant; includes no filesystem paths."""

from typing import cast

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, library_visibility_predicate
from app.models.library import Library


class SqlAlchemyVisibleLibraryIds:
    def __init__(self, db: Session) -> None:
        self._db = db

    def __call__(self, context: AuthorizationContext) -> frozenset[str]:
        return frozenset(
            self._db.scalars(
                select(Library.id).where(
                    library_visibility_predicate(
                        context, cast(ColumnElement[str], Library.id)
                    )
                )
            )
        )
