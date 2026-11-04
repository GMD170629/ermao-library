"""Shelf capability composition root."""

from sqlalchemy.orm import Session

from app.modules.shelf.application.catalog import ListShelfNavigation
from app.modules.shelf.infrastructure import shelves as shelf_store
from app.modules.shelf.infrastructure.catalog import SqlAlchemyCatalogShelfQueries


def shelf_navigation(db: Session) -> ListShelfNavigation:
    return ListShelfNavigation(SqlAlchemyCatalogShelfQueries(db))


__all__ = ["shelf_navigation", "shelf_store"]
