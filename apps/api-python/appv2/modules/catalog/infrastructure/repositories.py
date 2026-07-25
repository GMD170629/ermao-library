from __future__ import annotations

import uuid
from collections.abc import Callable
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.catalog.contracts import (
    CatalogEdition,
    CatalogFile,
    CatalogImport,
    CatalogRepository,
    CatalogWork,
    ShelfView,
)
from appv2.modules.catalog.infrastructure.models import (
    CategoryRecord,
    EditionRecord,
    FileRecord,
    ShelfItemRecord,
    ShelfRecord,
    WorkRecord,
)


def _work(record: WorkRecord) -> CatalogWork:
    return CatalogWork(
        id=record.id,
        title=record.title,
        author=record.author,
        media_type=record.media_type,
        status=record.status,
        cover_key=record.cover_key,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _edition(record: EditionRecord) -> CatalogEdition:
    return CatalogEdition(
        id=record.id,
        work_id=record.work_id,
        title=record.title,
        format=record.format,
        language=record.language,
        primary=record.is_primary,
        created_at=record.created_at,
    )


def _file(record: FileRecord) -> CatalogFile:
    return CatalogFile(
        id=record.id,
        edition_id=record.edition_id,
        storage_path=record.storage_path,
        original_name=record.original_name,
        media_type=record.media_type,
        size_bytes=record.size_bytes,
        checksum=record.checksum,
    )


def _shelf(record: ShelfRecord) -> ShelfView:
    return ShelfView(
        id=record.id,
        owner_id=record.owner_id,
        name=record.name,
        description=record.description,
        kind=record.kind,
        rules=record.rules,
        pinned=record.pinned,
        created_at=record.created_at,
    )


class SqlCatalogRepository(CatalogRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_works(
        self,
        *,
        offset: int,
        limit: int,
        query: str | None,
        media_type: str | None,
        status: str,
    ) -> tuple[list[CatalogWork], int]:
        criteria = [WorkRecord.status == status]
        if media_type:
            criteria.append(WorkRecord.media_type == media_type)
        if query:
            pattern = f"%{query.strip()}%"
            criteria.append(or_(WorkRecord.title.ilike(pattern), WorkRecord.author.ilike(pattern)))
        total = int(
            self._session.scalar(select(func.count()).select_from(WorkRecord).where(*criteria)) or 0
        )
        records = self._session.scalars(
            select(WorkRecord)
            .where(*criteria)
            .order_by(WorkRecord.updated_at.desc(), WorkRecord.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [_work(record) for record in records], total

    def get_work(self, work_id: uuid.UUID) -> CatalogWork | None:
        record = self._session.get(WorkRecord, work_id)
        return _work(record) if record is not None else None

    def get_edition(self, edition_id: uuid.UUID) -> CatalogEdition | None:
        record = self._session.get(EditionRecord, edition_id)
        return _edition(record) if record is not None else None

    def get_file(self, file_id: uuid.UUID) -> CatalogFile | None:
        record = self._session.get(FileRecord, file_id)
        return _file(record) if record is not None else None

    def list_editions(self, work_id: uuid.UUID) -> list[CatalogEdition]:
        records = self._session.scalars(
            select(EditionRecord)
            .where(EditionRecord.work_id == work_id)
            .order_by(EditionRecord.is_primary.desc(), EditionRecord.created_at)
        ).all()
        return [_edition(record) for record in records]

    def list_files(self, edition_id: uuid.UUID) -> list[CatalogFile]:
        records = self._session.scalars(
            select(FileRecord)
            .where(FileRecord.edition_id == edition_id)
            .order_by(FileRecord.sort_order, FileRecord.created_at)
        ).all()
        return [_file(record) for record in records]

    def files_for_edition(self, edition_id: uuid.UUID) -> list[CatalogFile]:
        return self.list_files(edition_id)

    def add_work(
        self,
        *,
        title: str,
        author: str | None,
        media_type: str,
        metadata: dict[str, object],
    ) -> CatalogWork:
        record = WorkRecord(
            title=title,
            sort_title=title.casefold(),
            author=author,
            media_type=media_type,
            status="active",
            metadata_json=metadata,
        )
        self._session.add(record)
        self._session.flush()
        return _work(record)

    def update_work(
        self,
        work_id: uuid.UUID,
        *,
        title: str | None,
        author: str | None,
        summary: str | None,
        status: str | None,
    ) -> CatalogWork | None:
        record = self._session.get(WorkRecord, work_id)
        if record is None:
            return None
        if title is not None:
            record.title = title
            record.sort_title = title.casefold()
        if author is not None:
            record.author = author
        if summary is not None:
            record.summary = summary
        if status is not None:
            record.status = status
        self._session.flush()
        return _work(record)

    def import_file(self, imported: CatalogImport) -> CatalogEdition:
        existing = self._session.scalar(
            select(FileRecord).where(FileRecord.checksum == imported.checksum).limit(1)
        )
        if existing is not None:
            edition = self._session.get(EditionRecord, existing.edition_id)
            if edition is None:
                raise RuntimeError("catalog file references a missing edition")
            return _edition(edition)
        work = WorkRecord(
            title=imported.title,
            sort_title=imported.title.casefold(),
            author=imported.author,
            media_type=imported.media_type,
            status="active",
            metadata_json=imported.metadata,
        )
        self._session.add(work)
        self._session.flush()
        edition = EditionRecord(
            work_id=work.id,
            title=imported.title,
            format=imported.format,
            is_primary=True,
            metadata_json=imported.metadata,
        )
        self._session.add(edition)
        self._session.flush()
        self._session.add(
            FileRecord(
                edition_id=edition.id,
                storage_path=imported.source_path,
                original_name=imported.original_name,
                media_type=imported.media_type,
                size_bytes=imported.size_bytes,
                checksum=imported.checksum,
                sort_order=0,
            )
        )
        self._session.flush()
        return _edition(edition)

    def apply_metadata(self, work_id: uuid.UUID, values: dict[str, object]) -> CatalogWork | None:
        record = self._session.get(WorkRecord, work_id)
        if record is None:
            return None
        if isinstance(values.get("title"), str):
            record.title = str(values["title"])
            record.sort_title = record.title.casefold()
        if isinstance(values.get("author"), str):
            record.author = str(values["author"])
        if isinstance(values.get("summary"), str):
            record.summary = str(values["summary"])
        merged = dict(record.metadata_json)
        merged.update(values)
        record.metadata_json = merged
        self._session.flush()
        return _work(record)

    def list_shelves(self, owner_id: uuid.UUID) -> list[ShelfView]:
        records = self._session.scalars(
            select(ShelfRecord)
            .where(ShelfRecord.owner_id == owner_id)
            .order_by(ShelfRecord.pinned.desc(), ShelfRecord.name)
        ).all()
        return [_shelf(record) for record in records]

    def get_shelf(self, shelf_id: uuid.UUID, owner_id: uuid.UUID) -> ShelfView | None:
        record = self._session.scalar(
            select(ShelfRecord).where(ShelfRecord.id == shelf_id, ShelfRecord.owner_id == owner_id)
        )
        return _shelf(record) if record is not None else None

    def add_shelf(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        description: str | None,
        kind: str,
        rules: dict[str, object],
        pinned: bool,
    ) -> ShelfView:
        record = ShelfRecord(
            owner_id=owner_id,
            name=name,
            description=description,
            kind=kind,
            rules=rules,
            pinned=pinned,
        )
        self._session.add(record)
        self._session.flush()
        return _shelf(record)

    def update_shelf(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
        rules: dict[str, object] | None,
        pinned: bool | None,
    ) -> ShelfView | None:
        record = self._session.scalar(
            select(ShelfRecord).where(ShelfRecord.id == shelf_id, ShelfRecord.owner_id == owner_id)
        )
        if record is None:
            return None
        if name is not None:
            record.name = " ".join(name.split())
        if description is not None:
            record.description = description
        if rules is not None:
            record.rules = rules
        if pinned is not None:
            record.pinned = pinned
        self._session.flush()
        return _shelf(record)

    def delete_shelf(self, shelf_id: uuid.UUID, owner_id: uuid.UUID) -> bool:
        record = self._session.scalar(
            select(ShelfRecord).where(ShelfRecord.id == shelf_id, ShelfRecord.owner_id == owner_id)
        )
        if record is None:
            return False
        self._session.delete(record)
        return True

    def add_shelf_item(self, shelf_id: uuid.UUID, owner_id: uuid.UUID, work_id: uuid.UUID) -> bool:
        shelf = self.get_shelf(shelf_id, owner_id)
        work = self.get_work(work_id)
        if shelf is None or work is None:
            return False
        existing = self._session.scalar(
            select(ShelfItemRecord).where(
                ShelfItemRecord.shelf_id == shelf_id,
                ShelfItemRecord.work_id == work_id,
            )
        )
        if existing is None:
            self._session.add(ShelfItemRecord(shelf_id=shelf_id, work_id=work_id))
            self._session.flush()
        return True

    def remove_shelf_item(
        self, shelf_id: uuid.UUID, owner_id: uuid.UUID, work_id: uuid.UUID
    ) -> bool:
        if self.get_shelf(shelf_id, owner_id) is None:
            return False
        record = self._session.scalar(
            select(ShelfItemRecord).where(
                ShelfItemRecord.shelf_id == shelf_id,
                ShelfItemRecord.work_id == work_id,
            )
        )
        if record is None:
            return False
        self._session.delete(record)
        return True

    def category_facets(self) -> dict[str, list[dict[str, object]]]:
        rows = self._session.execute(
            select(CategoryRecord.kind, CategoryRecord.id, CategoryRecord.name).order_by(
                CategoryRecord.kind, CategoryRecord.name
            )
        ).all()
        result: dict[str, list[dict[str, object]]] = {}
        for kind, category_id, name in rows:
            result.setdefault(kind, []).append({"id": str(category_id), "name": name})
        return result


class CatalogSqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.catalog: CatalogRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.catalog = SqlCatalogRepository(self._session)
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


def catalog_uow_factory(
    session_factory: sessionmaker[Session],
) -> Callable[[], CatalogSqlUnitOfWork]:
    return lambda: CatalogSqlUnitOfWork(session_factory)
