"""SQLAlchemy read adapter for catalog-visible personal shelves."""

from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, work_visibility_predicate
from app.models.library import LibraryWork
from app.models.shelf import Shelf, ShelfWork
from app.modules.shelf.application.catalog import (
    CatalogShelf,
    CatalogShelfPage,
    CatalogShelfWorkPage,
)


class SqlAlchemyCatalogShelfQueries:
    """Publish static membership and dynamically resolved smart shelves."""

    def __init__(
        self,
        db: Session,
        smart_work_ids: Callable[[object, str], list[str]] | None = None,
    ) -> None:
        self._db = db
        self._smart_work_ids = smart_work_ids

    def list_shelves(
        self,
        *,
        context: AuthorizationContext,
        page: int,
        page_size: int,
    ) -> CatalogShelfPage:
        filters = (
            Shelf.owner_user_id == context.user_id,
            Shelf.kind.in_(("STATIC", "SMART")),
        )
        total = int(
            self._db.scalar(select(func.count()).select_from(Shelf).where(*filters))
            or 0
        )
        rows = self._db.scalars(
            select(Shelf)
            .where(*filters)
            .order_by(
                Shelf.pinned.desc(),
                Shelf.updated_at.desc(),
                Shelf.id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        shelves = tuple(
            CatalogShelf(
                id=shelf.id,
                name=shelf.name,
                description=shelf.description,
                updated_at=shelf.updated_at,
            )
            for shelf in rows
        )
        return CatalogShelfPage(
            shelves=shelves,
            total=total,
            page=page,
            page_size=page_size,
            updated_at=max((shelf.updated_at for shelf in shelves), default=None),
        )

    def list_shelf_work_ids(
        self,
        *,
        context: AuthorizationContext,
        shelf_id: str,
        page: int,
        page_size: int,
    ) -> CatalogShelfWorkPage | None:
        shelf = self._db.scalar(
            select(Shelf).where(
                Shelf.id == shelf_id,
                Shelf.owner_user_id == context.user_id,
                Shelf.kind.in_(("STATIC", "SMART")),
            )
        )
        if shelf is None:
            return None
        if shelf.kind == "SMART":
            try:
                rules: object = json.loads(shelf.rules_json)
                work_ids = (
                    self._smart_work_ids(rules, context.user_id)
                    if self._smart_work_ids is not None
                    else []
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                work_ids = []
            start = (page - 1) * page_size
            selected_ids = tuple(work_ids[start : start + page_size])
            catalog_shelf = CatalogShelf(
                id=shelf.id,
                name=shelf.name,
                description=shelf.description,
                updated_at=shelf.updated_at,
            )
            return CatalogShelfWorkPage(
                shelf=catalog_shelf,
                work_ids=selected_ids,
                total=len(work_ids),
                page=page,
                page_size=page_size,
                updated_at=shelf.updated_at,
            )
        work_filters = (
            ShelfWork.shelf_id == shelf.id,
            LibraryWork.hidden.is_(False),
            work_visibility_predicate(context),
        )
        total = int(
            self._db.scalar(
                select(func.count())
                .select_from(ShelfWork)
                .join(LibraryWork, LibraryWork.id == ShelfWork.work_id)
                .where(*work_filters)
            )
            or 0
        )
        rows = self._db.execute(
            select(ShelfWork.work_id, ShelfWork.created_at)
            .join(LibraryWork, LibraryWork.id == ShelfWork.work_id)
            .where(*work_filters)
            .order_by(ShelfWork.created_at.asc(), ShelfWork.work_id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        catalog_shelf = CatalogShelf(
            id=shelf.id,
            name=shelf.name,
            description=shelf.description,
            updated_at=shelf.updated_at,
        )
        return CatalogShelfWorkPage(
            shelf=catalog_shelf,
            work_ids=tuple(str(row.work_id) for row in rows),
            total=total,
            page=page,
            page_size=page_size,
            updated_at=max([shelf.updated_at] + [row.created_at for row in rows]),
        )
