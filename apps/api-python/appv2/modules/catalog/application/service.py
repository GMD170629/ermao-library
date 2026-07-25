from __future__ import annotations

import uuid
from collections.abc import Callable

from appv2.modules.catalog.contracts import (
    CatalogEdition,
    CatalogFile,
    CatalogImport,
    CatalogUnitOfWork,
    CatalogWork,
    ShelfView,
)
from appv2.modules.catalog.domain import Work


class CatalogNotFound(Exception):
    pass


class CatalogService:
    def __init__(self, uow_factory: Callable[[], CatalogUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def list_works(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None,
        media_type: str | None,
        status: str,
    ) -> tuple[list[CatalogWork], int]:
        with self._uow_factory() as uow:
            return uow.catalog.list_works(
                offset=(page - 1) * page_size,
                limit=page_size,
                query=query,
                media_type=media_type,
                status=status,
            )

    def get_work(self, work_id: uuid.UUID) -> tuple[CatalogWork, list[CatalogEdition]]:
        with self._uow_factory() as uow:
            work = uow.catalog.get_work(work_id)
            if work is None:
                raise CatalogNotFound
            return work, uow.catalog.list_editions(work_id)

    def create_work(
        self,
        *,
        title: str,
        author: str | None,
        media_type: str,
        metadata: dict[str, object] | None = None,
    ) -> CatalogWork:
        domain = Work(
            id=uuid.uuid4(),
            title=" ".join(title.split()),
            author=author,
            media_type=media_type,
        )
        domain = domain.rename(domain.title)
        with self._uow_factory() as uow:
            created = uow.catalog.add_work(
                title=domain.title,
                author=domain.author,
                media_type=domain.media_type,
                metadata=metadata or {},
            )
            uow.commit()
            return created

    def update_work(
        self,
        work_id: uuid.UUID,
        *,
        title: str | None,
        author: str | None,
        summary: str | None,
        status: str | None,
    ) -> CatalogWork:
        if title is not None:
            title = (
                Work(id=work_id, title=title, author=author, media_type="book").rename(title).title
            )
        with self._uow_factory() as uow:
            updated = uow.catalog.update_work(
                work_id,
                title=title,
                author=author,
                summary=summary,
                status=status,
            )
            if updated is None:
                raise CatalogNotFound
            uow.commit()
            return updated

    def list_files(self, edition_id: uuid.UUID) -> list[CatalogFile]:
        with self._uow_factory() as uow:
            if uow.catalog.get_edition(edition_id) is None:
                raise CatalogNotFound
            return uow.catalog.list_files(edition_id)

    def get_file(self, file_id: uuid.UUID) -> CatalogFile:
        with self._uow_factory() as uow:
            file = uow.catalog.get_file(file_id)
            if file is None:
                raise CatalogNotFound
            return file

    def import_file(self, imported: CatalogImport) -> CatalogEdition:
        with self._uow_factory() as uow:
            edition = uow.catalog.import_file(imported)
            uow.commit()
            return edition

    def apply_metadata(self, work_id: uuid.UUID, values: dict[str, object]) -> CatalogWork:
        with self._uow_factory() as uow:
            work = uow.catalog.apply_metadata(work_id, values)
            if work is None:
                raise CatalogNotFound
            uow.commit()
            return work

    def list_shelves(self, owner_id: uuid.UUID) -> list[ShelfView]:
        with self._uow_factory() as uow:
            return uow.catalog.list_shelves(owner_id)

    def create_shelf(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        description: str | None,
        kind: str,
        rules: dict[str, object],
        pinned: bool,
    ) -> ShelfView:
        normalized = " ".join(name.split())
        if not normalized:
            raise ValueError("shelf name cannot be empty")
        with self._uow_factory() as uow:
            shelf = uow.catalog.add_shelf(
                owner_id=owner_id,
                name=normalized,
                description=description,
                kind=kind,
                rules=rules,
                pinned=pinned,
            )
            uow.commit()
            return shelf

    def update_shelf(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
        rules: dict[str, object] | None,
        pinned: bool | None,
    ) -> ShelfView:
        with self._uow_factory() as uow:
            shelf = uow.catalog.update_shelf(
                shelf_id,
                owner_id,
                name=name,
                description=description,
                rules=rules,
                pinned=pinned,
            )
            if shelf is None:
                raise CatalogNotFound
            uow.commit()
            return shelf

    def delete_shelf(self, shelf_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.catalog.delete_shelf(shelf_id, owner_id):
                raise CatalogNotFound
            uow.commit()

    def set_shelf_item(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        work_id: uuid.UUID,
        *,
        present: bool,
    ) -> None:
        with self._uow_factory() as uow:
            changed = (
                uow.catalog.add_shelf_item(shelf_id, owner_id, work_id)
                if present
                else uow.catalog.remove_shelf_item(shelf_id, owner_id, work_id)
            )
            if not changed:
                raise CatalogNotFound
            uow.commit()

    def facets(self) -> dict[str, list[dict[str, object]]]:
        with self._uow_factory() as uow:
            return uow.catalog.category_facets()
