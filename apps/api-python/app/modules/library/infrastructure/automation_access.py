"""Current library IDs for an automation grant; includes no filesystem paths."""

from typing import cast

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, library_visibility_predicate
from app.models.library import Library
from app.modules.library.application.catalog import CatalogLibrary


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

    def list_libraries(
        self, context: AuthorizationContext
    ) -> tuple[CatalogLibrary, ...]:
        rows = self._db.execute(
            select(Library.id, Library.name)
            .where(
                library_visibility_predicate(
                    context, cast(ColumnElement[str], Library.id)
                )
            )
            .order_by(Library.name, Library.id)
        )
        return tuple(CatalogLibrary(id=row.id, name=row.name) for row in rows)
