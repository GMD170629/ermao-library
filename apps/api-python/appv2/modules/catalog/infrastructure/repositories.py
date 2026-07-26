from __future__ import annotations

import uuid
from collections.abc import Callable
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.catalog.contracts import (
    CatalogDeletion,
    CatalogEdition,
    CatalogFile,
    CatalogImport,
    CatalogImportResult,
    CatalogRepository,
    CatalogVolume,
    CatalogWork,
    CategoryView,
    DuplicateGroupView,
    LibraryOperationView,
    PreparedPublication,
    SeriesView,
    ShelfView,
)
from appv2.modules.catalog.infrastructure.models import (
    CategoryRecord,
    EditionRecord,
    FileRecord,
    LibraryOperationRecord,
    ShelfItemRecord,
    ShelfRecord,
    VolumeRecord,
    WorkCategoryRecord,
    WorkRecord,
)
from appv2.modules.reading.infrastructure.models import ReaderPreferenceRecord


def _work(record: WorkRecord) -> CatalogWork:
    return CatalogWork(
        id=record.id,
        title=record.title,
        author=record.author,
        media_type=record.media_type,
        status=record.status,
        cover_key=record.cover_key,
        summary=record.summary,
        metadata=record.metadata_json,
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
        metadata=record.metadata_json,
        created_at=record.created_at,
    )


def _file(record: FileRecord) -> CatalogFile:
    return CatalogFile(
        id=record.id,
        edition_id=record.edition_id,
        volume_id=record.volume_id,
        storage_path=record.storage_path,
        original_name=record.original_name,
        media_type=record.media_type,
        size_bytes=record.size_bytes,
        checksum=record.checksum,
        sort_order=record.sort_order,
        duration_ms=record.duration_ms,
    )


def _volume(record: VolumeRecord) -> CatalogVolume:
    return CatalogVolume(
        id=record.id,
        edition_id=record.edition_id,
        title=record.title,
        sort_order=record.sort_order,
        page_count=record.page_count,
        duration_ms=record.duration_ms,
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


def _category(record: CategoryRecord, book_count: int) -> CategoryView:
    return CategoryView(
        id=record.id,
        kind=record.kind,
        name=record.name,
        book_count=book_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _operation(record: LibraryOperationRecord) -> LibraryOperationView:
    affected = record.payload.get("affectedWorks")
    return LibraryOperationView(
        id=record.id,
        kind=record.kind,
        status=record.status,
        affected_works=affected if isinstance(affected, int) else 0,
        undo_available=record.status == "completed" and record.undo_payload is not None,
        created_at=record.created_at,
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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
        series_name: str | None,
        sort: str,
        sort_direction: str,
    ) -> tuple[list[CatalogWork], int]:
        criteria = [WorkRecord.status == status]
        if media_type:
            criteria.append(WorkRecord.media_type == media_type)
        if query:
            pattern = f"%{query.strip()}%"
            criteria.append(or_(WorkRecord.title.ilike(pattern), WorkRecord.author.ilike(pattern)))
        if series_name:
            criteria.append(WorkRecord.metadata_json["seriesName"].as_string() == series_name)
        total = int(
            self._session.scalar(select(func.count()).select_from(WorkRecord).where(*criteria)) or 0
        )
        sort_expressions = {
            "recent_read": WorkRecord.updated_at,
            "recent_import": WorkRecord.created_at,
            "title": func.lower(WorkRecord.title),
            "author": func.lower(WorkRecord.author),
            "publisher": func.lower(WorkRecord.metadata_json["publisher"].as_string()),
            "series": func.lower(WorkRecord.metadata_json["seriesName"].as_string()),
        }
        sort_expression = sort_expressions.get(sort, WorkRecord.updated_at)
        primary_order = (
            sort_expression.asc().nulls_last()
            if sort_direction == "asc"
            else sort_expression.desc().nulls_last()
        )
        records = self._session.scalars(
            select(WorkRecord)
            .where(*criteria)
            .order_by(primary_order, WorkRecord.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [_work(record) for record in records], total

    def list_series(self, *, status: str, offset: int, limit: int) -> tuple[list[SeriesView], int]:
        series = WorkRecord.metadata_json["seriesName"].as_string()
        criteria = [
            WorkRecord.status == status,
            series.is_not(None),
            series != "",
        ]
        total = int(
            self._session.scalar(
                select(func.count(func.distinct(series))).select_from(WorkRecord).where(*criteria)
            )
            or 0
        )
        rows = self._session.execute(
            select(
                series.label("name"),
                func.count(WorkRecord.id),
                func.max(WorkRecord.updated_at),
            )
            .where(*criteria)
            .group_by(series)
            .order_by(series)
            .offset(offset)
            .limit(limit)
        ).all()
        return [
            SeriesView(
                name=str(name),
                book_count=int(book_count),
                latest_updated_at=latest_updated_at,
            )
            for name, book_count, latest_updated_at in rows
        ], total

    def get_work(self, work_id: uuid.UUID) -> CatalogWork | None:
        record = self._session.get(WorkRecord, work_id)
        return _work(record) if record is not None else None

    def get_edition(self, edition_id: uuid.UUID) -> CatalogEdition | None:
        record = self._session.get(EditionRecord, edition_id)
        return _edition(record) if record is not None else None

    def get_file(self, file_id: uuid.UUID) -> CatalogFile | None:
        record = self._session.get(FileRecord, file_id)
        return _file(record) if record is not None else None

    def get_volume(self, volume_id: uuid.UUID) -> CatalogVolume | None:
        record = self._session.get(VolumeRecord, volume_id)
        return _volume(record) if record is not None else None

    def list_editions(self, work_id: uuid.UUID) -> list[CatalogEdition]:
        records = self._session.scalars(
            select(EditionRecord)
            .where(EditionRecord.work_id == work_id)
            .order_by(EditionRecord.is_primary.desc(), EditionRecord.created_at)
        ).all()
        return [_edition(record) for record in records]

    def editions_for_work(self, work_id: uuid.UUID) -> list[CatalogEdition]:
        return self.list_editions(work_id)

    def list_files(self, edition_id: uuid.UUID) -> list[CatalogFile]:
        records = self._session.scalars(
            select(FileRecord)
            .where(FileRecord.edition_id == edition_id)
            .order_by(FileRecord.sort_order, FileRecord.created_at)
        ).all()
        return [_file(record) for record in records]

    def list_volumes(self, edition_id: uuid.UUID) -> list[CatalogVolume]:
        records = self._session.scalars(
            select(VolumeRecord)
            .where(VolumeRecord.edition_id == edition_id)
            .order_by(VolumeRecord.sort_order, VolumeRecord.created_at)
        ).all()
        return [_volume(record) for record in records]

    def volumes_for_edition(self, edition_id: uuid.UUID) -> list[CatalogVolume]:
        return self.list_volumes(edition_id)

    def files_for_edition(self, edition_id: uuid.UUID) -> list[CatalogFile]:
        return self.list_files(edition_id)

    def update_edition(
        self,
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        *,
        title: str | None,
        language: str | None,
        metadata: dict[str, object] | None,
    ) -> CatalogEdition | None:
        record = self._session.scalar(
            select(EditionRecord).where(
                EditionRecord.id == edition_id,
                EditionRecord.work_id == work_id,
            )
        )
        if record is None:
            return None
        if title is not None:
            record.title = title
        if language is not None:
            record.language = language or None
        if metadata is not None:
            merged = dict(record.metadata_json)
            merged.update(metadata)
            record.metadata_json = merged
        self._session.flush()
        return _edition(record)

    def set_primary_edition(self, work_id: uuid.UUID, edition_id: uuid.UUID) -> bool:
        selected = self._session.scalar(
            select(EditionRecord).where(
                EditionRecord.id == edition_id,
                EditionRecord.work_id == work_id,
            )
        )
        if selected is None:
            return False
        editions = self._session.scalars(
            select(EditionRecord).where(EditionRecord.work_id == work_id)
        ).all()
        for edition in editions:
            edition.is_primary = edition.id == edition_id
        self._session.flush()
        return True

    def split_edition(
        self,
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        *,
        title: str,
        author: str | None,
        copy_shelves: bool,
    ) -> uuid.UUID | None:
        source_work = self._session.get(WorkRecord, work_id)
        edition = self._session.scalar(
            select(EditionRecord).where(
                EditionRecord.id == edition_id,
                EditionRecord.work_id == work_id,
            )
        )
        if source_work is None or edition is None:
            return None
        edition_count = int(
            self._session.scalar(
                select(func.count())
                .select_from(EditionRecord)
                .where(EditionRecord.work_id == work_id)
            )
            or 0
        )
        if edition_count < 2:
            return None
        new_work = WorkRecord(
            title=title,
            sort_title=title.casefold(),
            author=author,
            summary=source_work.summary,
            media_type=source_work.media_type,
            status="active",
            metadata_json=dict(source_work.metadata_json),
        )
        self._session.add(new_work)
        self._session.flush()
        was_primary = edition.is_primary
        edition.work_id = new_work.id
        edition.is_primary = True
        if was_primary:
            replacement = self._session.scalar(
                select(EditionRecord)
                .where(
                    EditionRecord.work_id == work_id,
                    EditionRecord.id != edition_id,
                )
                .order_by(EditionRecord.created_at, EditionRecord.id)
                .limit(1)
            )
            if replacement is not None:
                replacement.is_primary = True
        if copy_shelves:
            shelf_items = self._session.scalars(
                select(ShelfItemRecord).where(ShelfItemRecord.work_id == work_id)
            ).all()
            self._session.add_all(
                ShelfItemRecord(
                    shelf_id=item.shelf_id,
                    work_id=new_work.id,
                    sort_order=item.sort_order + 1,
                )
                for item in shelf_items
            )
        self._session.flush()
        return new_work.id

    def move_volume(
        self,
        work_id: uuid.UUID,
        volume_id: uuid.UUID,
        *,
        direction: str,
    ) -> bool:
        volume = self._session.scalar(
            select(VolumeRecord)
            .join(EditionRecord, EditionRecord.id == VolumeRecord.edition_id)
            .where(
                VolumeRecord.id == volume_id,
                EditionRecord.work_id == work_id,
            )
        )
        if volume is None:
            return False
        comparison = (
            VolumeRecord.sort_order < volume.sort_order
            if direction == "up"
            else VolumeRecord.sort_order > volume.sort_order
        )
        ordering = (
            VolumeRecord.sort_order.desc() if direction == "up" else VolumeRecord.sort_order.asc()
        )
        neighbor = self._session.scalar(
            select(VolumeRecord)
            .where(
                VolumeRecord.edition_id == volume.edition_id,
                comparison,
            )
            .order_by(ordering, VolumeRecord.id)
            .limit(1)
        )
        if neighbor is None:
            return True
        current_order = volume.sort_order
        neighbor_order = neighbor.sort_order
        volume.sort_order = -2_147_483_648
        self._session.flush()
        neighbor.sort_order = current_order
        self._session.flush()
        volume.sort_order = neighbor_order
        self._session.flush()
        return True

    def move_volume_to(
        self,
        work_id: uuid.UUID,
        volume_id: uuid.UUID,
        *,
        target_edition_id: uuid.UUID,
    ) -> bool:
        volume = self._session.scalar(
            select(VolumeRecord)
            .join(EditionRecord, EditionRecord.id == VolumeRecord.edition_id)
            .where(
                VolumeRecord.id == volume_id,
                EditionRecord.work_id == work_id,
            )
        )
        target = self._session.get(EditionRecord, target_edition_id)
        if volume is None or target is None:
            return False
        if volume.edition_id == target_edition_id:
            return True
        next_order = (
            int(
                self._session.scalar(
                    select(func.coalesce(func.max(VolumeRecord.sort_order), -1)).where(
                        VolumeRecord.edition_id == target_edition_id
                    )
                )
                or 0
            )
            + 1
        )
        volume.edition_id = target_edition_id
        volume.sort_order = next_order
        files = self._session.scalars(
            select(FileRecord).where(FileRecord.volume_id == volume_id)
        ).all()
        for file in files:
            file.edition_id = target_edition_id
        self._session.flush()
        return True

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
        metadata: dict[str, object] | None,
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
        if metadata is not None:
            merged = dict(record.metadata_json)
            merged.update(metadata)
            record.metadata_json = merged
        self._session.flush()
        return _work(record)

    def delete_work(self, work_id: uuid.UUID) -> CatalogDeletion | None:
        record = self._session.get(WorkRecord, work_id)
        if record is None:
            return None
        edition_ids = tuple(
            self._session.scalars(
                select(EditionRecord.id).where(EditionRecord.work_id == work_id)
            ).all()
        )
        volume_ids = tuple(
            self._session.scalars(
                select(VolumeRecord.id).where(VolumeRecord.edition_id.in_(edition_ids))
            ).all()
        ) if edition_ids else ()
        storage_paths = tuple(
            self._session.scalars(
                select(FileRecord.storage_path).where(FileRecord.edition_id.in_(edition_ids))
            ).all()
        ) if edition_ids else ()
        target_ids = (work_id, *edition_ids, *volume_ids)
        if target_ids:
            self._session.execute(
                delete(ReaderPreferenceRecord).where(
                    ReaderPreferenceRecord.target_id.in_(target_ids)
                )
            )
        self._session.execute(
            text(
                "UPDATE ingestion.jobs SET result_work_id = NULL, "
                "result_edition_id = NULL, result_volume_ids = CAST('[]' AS jsonb) "
                "WHERE result_work_id = :work_id"
            ),
            {"work_id": work_id},
        )
        deletion = CatalogDeletion(
            work_id=work_id,
            cover_key=record.cover_key,
            storage_paths=storage_paths,
        )
        self._session.delete(record)
        self._session.flush()
        return deletion

    def set_cover_key(self, work_id: uuid.UUID, cover_key: str) -> CatalogWork | None:
        record = self._session.get(WorkRecord, work_id)
        if record is None:
            return None
        record.cover_key = cover_key
        self._session.flush()
        return _work(record)

    def import_publication(self, publication: PreparedPublication) -> CatalogImportResult:
        checksums = [item.checksum for item in publication.files]
        existing_file = self._session.scalar(
            select(FileRecord).where(FileRecord.checksum.in_(checksums)).limit(1)
        )
        work: WorkRecord | None = None
        edition: EditionRecord | None = None
        if existing_file is not None:
            edition = self._session.get(EditionRecord, existing_file.edition_id)
            if edition is not None:
                work = self._session.get(WorkRecord, edition.work_id)
        if work is None:
            work = self._session.scalar(
                select(WorkRecord)
                .where(
                    WorkRecord.metadata_json["identityKey"].as_string() == publication.identity_key
                )
                .limit(1)
            )
        if work is None:
            work = WorkRecord(
                title=publication.title,
                sort_title=publication.title.casefold(),
                author=publication.author,
                media_type=publication.media_type,
                status="active",
                metadata_json={
                    **publication.metadata,
                    "identityKey": publication.identity_key,
                    "identifiers": list(publication.identifiers),
                },
            )
            self._session.add(work)
            self._session.flush()
        elif work.status == "archived":
            # Re-importing a publication is an explicit request to put it back
            # in the library. Keeping the reused work archived would let the
            # ingestion job complete successfully while every library query
            # continues to hide its result.
            work.status = "active"
        if edition is None or edition.work_id != work.id or edition.format != publication.format:
            edition = self._session.scalar(
                select(EditionRecord)
                .where(
                    EditionRecord.work_id == work.id,
                    EditionRecord.format == publication.format,
                )
                .order_by(EditionRecord.created_at)
                .limit(1)
            )
        if edition is None:
            edition = EditionRecord(
                work_id=work.id,
                title=publication.title,
                format=publication.format,
                language=publication.language,
                is_primary=True,
                metadata_json=publication.metadata,
            )
            self._session.add(edition)
            self._session.flush()

        volume_ids: dict[str, uuid.UUID] = {}
        for volume_spec in publication.volumes:
            volume = self._session.scalar(
                select(VolumeRecord).where(
                    VolumeRecord.edition_id == edition.id,
                    VolumeRecord.title == volume_spec.title,
                )
            )
            if volume is None:
                sort_order = volume_spec.sort_order
                occupied = self._session.scalar(
                    select(VolumeRecord.id).where(
                        VolumeRecord.edition_id == edition.id,
                        VolumeRecord.sort_order == sort_order,
                    )
                )
                if occupied is not None:
                    sort_order = (
                        int(
                            self._session.scalar(
                                select(func.max(VolumeRecord.sort_order)).where(
                                    VolumeRecord.edition_id == edition.id
                                )
                            )
                            or 0
                        )
                        + 1
                    )
                volume = VolumeRecord(
                    edition_id=edition.id,
                    title=volume_spec.title,
                    sort_order=sort_order,
                    page_count=volume_spec.page_count,
                    duration_ms=volume_spec.duration_ms,
                )
                self._session.add(volume)
                self._session.flush()
            else:
                volume.title = volume_spec.title
                volume.page_count = volume_spec.page_count
                volume.duration_ms = volume_spec.duration_ms
            volume_ids[volume_spec.key] = volume.id

        added = 0
        for file_spec in publication.files:
            existing = self._session.scalar(
                select(FileRecord).where(
                    FileRecord.checksum == file_spec.checksum,
                    FileRecord.storage_path == file_spec.source_path,
                )
            )
            if existing is not None:
                continue
            self._session.add(
                FileRecord(
                    edition_id=edition.id,
                    volume_id=(
                        volume_ids.get(file_spec.volume_key)
                        if file_spec.volume_key is not None
                        else None
                    ),
                    storage_path=file_spec.source_path,
                    original_name=file_spec.original_name,
                    media_type=file_spec.media_type,
                    size_bytes=file_spec.size_bytes,
                    checksum=file_spec.checksum,
                    sort_order=file_spec.sort_order,
                    duration_ms=file_spec.duration_ms,
                )
            )
            added += 1
        self._session.flush()
        return CatalogImportResult(
            work_id=work.id,
            edition_id=edition.id,
            volume_ids=tuple(volume_ids.values()),
            duplicate=added == 0,
        )

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
                media_type=imported.file_media_type,
                size_bytes=imported.size_bytes,
                checksum=imported.checksum,
                sort_order=0,
            )
        )
        self._session.flush()
        return _edition(edition)

    def publish_conversion(
        self,
        source_edition_id: uuid.UUID,
        converted: CatalogImport,
    ) -> CatalogEdition | None:
        source = self._session.get(EditionRecord, source_edition_id)
        if source is None:
            return None
        existing_file = self._session.scalar(
            select(FileRecord).where(FileRecord.checksum == converted.checksum).limit(1)
        )
        if existing_file is not None:
            existing_edition = self._session.get(EditionRecord, existing_file.edition_id)
            if existing_edition is not None and existing_edition.work_id == source.work_id:
                return _edition(existing_edition)
            raise ValueError("converted file checksum belongs to another work")
        metadata = {
            **converted.metadata,
            "conversion": {
                "sourceEditionId": str(source_edition_id),
                "sourceFormat": source.format,
                "targetFormat": converted.format,
            },
        }
        edition = EditionRecord(
            work_id=source.work_id,
            title=source.title,
            format=converted.format,
            language=source.language,
            is_primary=False,
            metadata_json=metadata,
        )
        self._session.add(edition)
        self._session.flush()
        self._session.add(
            FileRecord(
                edition_id=edition.id,
                storage_path=converted.source_path,
                original_name=converted.original_name,
                media_type=converted.file_media_type,
                size_bytes=converted.size_bytes,
                checksum=converted.checksum,
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

    def list_shelf_works(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[CatalogWork], list[uuid.UUID], int] | None:
        shelf = self._session.scalar(
            select(ShelfRecord).where(
                ShelfRecord.id == shelf_id,
                ShelfRecord.owner_id == owner_id,
            )
        )
        if shelf is None:
            return None
        if shelf.kind == "smart":
            criteria = [WorkRecord.status == "active"]
            media_type = shelf.rules.get("mediaType")
            if isinstance(media_type, str) and media_type:
                criteria.append(WorkRecord.media_type == media_type)
            all_ids = list(
                self._session.scalars(
                    select(WorkRecord.id)
                    .where(*criteria)
                    .order_by(WorkRecord.sort_title, WorkRecord.id)
                ).all()
            )
            records = self._session.scalars(
                select(WorkRecord)
                .where(*criteria)
                .order_by(WorkRecord.sort_title, WorkRecord.id)
                .offset(offset)
                .limit(limit)
            ).all()
        else:
            all_ids = list(
                self._session.scalars(
                    select(ShelfItemRecord.work_id)
                    .where(ShelfItemRecord.shelf_id == shelf_id)
                    .order_by(ShelfItemRecord.sort_order, ShelfItemRecord.id)
                ).all()
            )
            records = self._session.scalars(
                select(WorkRecord)
                .join(ShelfItemRecord, ShelfItemRecord.work_id == WorkRecord.id)
                .where(ShelfItemRecord.shelf_id == shelf_id)
                .order_by(ShelfItemRecord.sort_order, ShelfItemRecord.id)
                .offset(offset)
                .limit(limit)
            ).all()
        return [_work(record) for record in records], all_ids, len(all_ids)

    def replace_shelf_items(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        work_ids: list[uuid.UUID],
    ) -> bool:
        shelf = self._session.scalar(
            select(ShelfRecord).where(
                ShelfRecord.id == shelf_id,
                ShelfRecord.owner_id == owner_id,
                ShelfRecord.kind == "manual",
            )
        )
        if shelf is None:
            return False
        unique_ids = list(dict.fromkeys(work_ids))
        if unique_ids:
            existing = set(
                self._session.scalars(
                    select(WorkRecord.id).where(WorkRecord.id.in_(unique_ids))
                ).all()
            )
            if existing != set(unique_ids):
                return False
        self._session.execute(delete(ShelfItemRecord).where(ShelfItemRecord.shelf_id == shelf_id))
        self._session.add_all(
            ShelfItemRecord(
                shelf_id=shelf_id,
                work_id=work_id,
                sort_order=index,
            )
            for index, work_id in enumerate(unique_ids)
        )
        self._session.flush()
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

    def list_categories(
        self,
        *,
        kind: str,
        query: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[CategoryView], int]:
        criteria = [CategoryRecord.kind == kind]
        if query:
            criteria.append(CategoryRecord.name.ilike(f"%{query.strip()}%"))
        total = int(
            self._session.scalar(select(func.count()).select_from(CategoryRecord).where(*criteria))
            or 0
        )
        rows = self._session.execute(
            select(CategoryRecord, func.count(WorkCategoryRecord.id))
            .outerjoin(
                WorkCategoryRecord,
                WorkCategoryRecord.category_id == CategoryRecord.id,
            )
            .where(*criteria)
            .group_by(CategoryRecord.id)
            .order_by(CategoryRecord.name)
            .offset(offset)
            .limit(limit)
        ).all()
        return [_category(record, int(count)) for record, count in rows], total

    def rename_category(self, category_id: uuid.UUID, name: str) -> CategoryView | None:
        record = self._session.get(CategoryRecord, category_id)
        if record is None:
            return None
        record.name = name
        self._session.flush()
        count = int(
            self._session.scalar(
                select(func.count())
                .select_from(WorkCategoryRecord)
                .where(WorkCategoryRecord.category_id == category_id)
            )
            or 0
        )
        return _category(record, count)

    def merge_categories(
        self,
        *,
        kind: str,
        target_id: uuid.UUID,
        source_ids: list[uuid.UUID],
    ) -> CategoryView | None:
        target = self._session.get(CategoryRecord, target_id)
        if target is None or target.kind != kind:
            return None
        sources = self._session.scalars(
            select(CategoryRecord).where(
                CategoryRecord.id.in_(source_ids),
                CategoryRecord.kind == kind,
            )
        ).all()
        if len(sources) != len(set(source_ids)):
            return None
        for source in sources:
            links = self._session.scalars(
                select(WorkCategoryRecord).where(WorkCategoryRecord.category_id == source.id)
            ).all()
            for link in links:
                duplicate = self._session.scalar(
                    select(WorkCategoryRecord).where(
                        WorkCategoryRecord.work_id == link.work_id,
                        WorkCategoryRecord.category_id == target_id,
                    )
                )
                if duplicate is None:
                    link.category_id = target_id
                else:
                    self._session.delete(link)
            self._session.delete(source)
        self._session.flush()
        count = int(
            self._session.scalar(
                select(func.count())
                .select_from(WorkCategoryRecord)
                .where(WorkCategoryRecord.category_id == target_id)
            )
            or 0
        )
        return _category(target, count)

    def delete_category(self, category_id: uuid.UUID) -> bool:
        record = self._session.get(CategoryRecord, category_id)
        if record is None:
            return False
        self._session.delete(record)
        return True

    def list_duplicate_groups(self, *, limit: int) -> list[DuplicateGroupView]:
        title_key = func.regexp_replace(
            func.lower(func.trim(WorkRecord.title)),
            r"\s+",
            "",
            "g",
        )
        author_key = func.regexp_replace(
            func.lower(func.trim(func.coalesce(WorkRecord.author, ""))),
            r"\s+",
            "",
            "g",
        )
        ranked = (
            select(
                WorkRecord.id.label("work_id"),
                title_key.label("title_key"),
                author_key.label("author_key"),
                func.count(WorkRecord.id)
                .over(partition_by=(title_key, author_key))
                .label("duplicate_count"),
            )
            .where(WorkRecord.status == "active")
            .subquery()
        )
        rows = self._session.execute(
            select(WorkRecord, ranked.c.title_key, ranked.c.author_key)
            .join(ranked, ranked.c.work_id == WorkRecord.id)
            .where(ranked.c.duplicate_count > 1)
            .order_by(ranked.c.title_key, ranked.c.author_key, WorkRecord.created_at)
        ).all()
        grouped: dict[tuple[str, str], list[CatalogWork]] = {}
        for record, normalized_title, normalized_author in rows:
            key = (str(normalized_title), str(normalized_author))
            grouped.setdefault(key, []).append(_work(record))
        result: list[DuplicateGroupView] = []
        for (normalized_title, normalized_author), works in grouped.items():
            if len(result) >= limit:
                break
            namespace_key = f"{normalized_title}\0{normalized_author}"
            result.append(
                DuplicateGroupView(
                    id=uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"shuku:duplicate:{namespace_key}",
                    ),
                    confidence=0.98 if normalized_author else 0.9,
                    reasons=("NORMALIZED_TITLE", "NORMALIZED_AUTHOR")
                    if normalized_author
                    else ("NORMALIZED_TITLE",),
                    works=tuple(works),
                )
            )
        return result

    def merge_duplicate_works(
        self,
        *,
        actor_id: uuid.UUID,
        target_id: uuid.UUID,
        source_ids: list[uuid.UUID],
    ) -> LibraryOperationView | None:
        target = self._session.scalar(
            select(WorkRecord).where(
                WorkRecord.id == target_id,
                WorkRecord.status == "active",
            )
        )
        sources = self._session.scalars(
            select(WorkRecord).where(
                WorkRecord.id.in_(source_ids),
                WorkRecord.status == "active",
            )
        ).all()
        if target is None or len(sources) != len(set(source_ids)):
            return None
        target_shelves_before = set(
            self._session.scalars(
                select(ShelfItemRecord.shelf_id).where(ShelfItemRecord.work_id == target_id)
            ).all()
        )
        target_categories_before = set(
            self._session.scalars(
                select(WorkCategoryRecord.category_id).where(
                    WorkCategoryRecord.work_id == target_id
                )
            ).all()
        )
        source_states: list[dict[str, object]] = []
        moved_shelves: set[uuid.UUID] = set()
        moved_categories: set[uuid.UUID] = set()
        for source in sources:
            editions = self._session.scalars(
                select(EditionRecord).where(EditionRecord.work_id == source.id)
            ).all()
            shelf_links = self._session.scalars(
                select(ShelfItemRecord).where(ShelfItemRecord.work_id == source.id)
            ).all()
            category_links = self._session.scalars(
                select(WorkCategoryRecord).where(WorkCategoryRecord.work_id == source.id)
            ).all()
            source_states.append(
                {
                    "id": str(source.id),
                    "status": source.status,
                    "metadata": source.metadata_json,
                    "editions": [
                        {"id": str(edition.id), "primary": edition.is_primary}
                        for edition in editions
                    ],
                    "shelfIds": [str(link.shelf_id) for link in shelf_links],
                    "categoryIds": [str(link.category_id) for link in category_links],
                }
            )
            for edition in editions:
                edition.work_id = target_id
                edition.is_primary = False
            for shelf_link in shelf_links:
                duplicate_link = (
                    shelf_link.shelf_id in target_shelves_before
                    or shelf_link.shelf_id in moved_shelves
                )
                moved_shelves.add(shelf_link.shelf_id)
                if duplicate_link:
                    self._session.delete(shelf_link)
                else:
                    shelf_link.work_id = target_id
            for category_link in category_links:
                duplicate_link = (
                    category_link.category_id in target_categories_before
                    or category_link.category_id in moved_categories
                )
                moved_categories.add(category_link.category_id)
                if duplicate_link:
                    self._session.delete(category_link)
                else:
                    category_link.work_id = target_id
            source.status = "archived"
            source.metadata_json = {
                **source.metadata_json,
                "mergedInto": str(target_id),
            }
        operation = LibraryOperationRecord(
            actor_id=actor_id,
            kind="duplicate_merge",
            status="completed",
            payload={
                "targetWorkId": str(target_id),
                "sourceWorkIds": [str(source.id) for source in sources],
                "affectedWorks": len(sources),
            },
            undo_payload={
                "targetWorkId": str(target_id),
                "sources": source_states,
                "movedShelfIds": [str(value) for value in moved_shelves],
                "targetShelfIdsBefore": [str(value) for value in target_shelves_before],
                "movedCategoryIds": [str(value) for value in moved_categories],
                "targetCategoryIdsBefore": [str(value) for value in target_categories_before],
            },
        )
        self._session.add(operation)
        self._session.flush()
        return _operation(operation)

    def undo_library_operation(
        self,
        *,
        actor_id: uuid.UUID,
        operation_id: uuid.UUID,
    ) -> LibraryOperationView | None:
        operation = self._session.scalar(
            select(LibraryOperationRecord).where(
                LibraryOperationRecord.id == operation_id,
                LibraryOperationRecord.actor_id == actor_id,
                LibraryOperationRecord.kind == "duplicate_merge",
                LibraryOperationRecord.status == "completed",
            )
        )
        if operation is None or operation.undo_payload is None:
            return None
        undo = operation.undo_payload
        target_id_value = undo.get("targetWorkId")
        sources_value = undo.get("sources")
        if not isinstance(target_id_value, str) or not isinstance(sources_value, list):
            return None
        target_id = uuid.UUID(target_id_value)
        target_shelves_before = {
            uuid.UUID(value) for value in _string_list(undo.get("targetShelfIdsBefore"))
        }
        target_categories_before = {
            uuid.UUID(value) for value in _string_list(undo.get("targetCategoryIdsBefore"))
        }
        for value in _string_list(undo.get("movedShelfIds")):
            if uuid.UUID(value) not in target_shelves_before:
                shelf_link = self._session.scalar(
                    select(ShelfItemRecord).where(
                        ShelfItemRecord.shelf_id == uuid.UUID(value),
                        ShelfItemRecord.work_id == target_id,
                    )
                )
                if shelf_link is not None:
                    self._session.delete(shelf_link)
        for value in _string_list(undo.get("movedCategoryIds")):
            if uuid.UUID(value) not in target_categories_before:
                category_link = self._session.scalar(
                    select(WorkCategoryRecord).where(
                        WorkCategoryRecord.category_id == uuid.UUID(value),
                        WorkCategoryRecord.work_id == target_id,
                    )
                )
                if category_link is not None:
                    self._session.delete(category_link)
        for source_value in sources_value:
            source_state = (
                {str(key): item for key, item in source_value.items()}
                if isinstance(source_value, dict)
                else {}
            )
            source_id_value = source_state.get("id")
            if not isinstance(source_id_value, str):
                return None
            source_id = uuid.UUID(source_id_value)
            source = self._session.get(WorkRecord, source_id)
            if source is None:
                return None
            status_value = source_state.get("status")
            metadata_value = source_state.get("metadata")
            source.status = status_value if isinstance(status_value, str) else "active"
            source.metadata_json = (
                {str(key): item for key, item in metadata_value.items()}
                if isinstance(metadata_value, dict)
                else {}
            )
            editions_value = source_state.get("editions")
            if isinstance(editions_value, list):
                for edition_value in editions_value:
                    edition_state = (
                        {str(key): item for key, item in edition_value.items()}
                        if isinstance(edition_value, dict)
                        else {}
                    )
                    edition_id_value = edition_state.get("id")
                    if not isinstance(edition_id_value, str):
                        continue
                    edition = self._session.get(
                        EditionRecord,
                        uuid.UUID(edition_id_value),
                    )
                    if edition is not None:
                        edition.work_id = source_id
                        edition.is_primary = edition_state.get("primary") is True
            for shelf_id_value in _string_list(source_state.get("shelfIds")):
                shelf_id = uuid.UUID(shelf_id_value)
                existing_shelf_link = self._session.scalar(
                    select(ShelfItemRecord).where(
                        ShelfItemRecord.shelf_id == shelf_id,
                        ShelfItemRecord.work_id == source_id,
                    )
                )
                if existing_shelf_link is None:
                    self._session.add(ShelfItemRecord(shelf_id=shelf_id, work_id=source_id))
            for category_id_value in _string_list(source_state.get("categoryIds")):
                category_id = uuid.UUID(category_id_value)
                existing_category_link = self._session.scalar(
                    select(WorkCategoryRecord).where(
                        WorkCategoryRecord.category_id == category_id,
                        WorkCategoryRecord.work_id == source_id,
                    )
                )
                if existing_category_link is None:
                    self._session.add(
                        WorkCategoryRecord(
                            category_id=category_id,
                            work_id=source_id,
                        )
                    )
        operation.status = "reverted"
        self._session.flush()
        return _operation(operation)


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
