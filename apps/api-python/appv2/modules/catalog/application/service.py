from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import BinaryIO

from appv2.modules.catalog.contracts import (
    BulkMutationResult,
    BulkSkipped,
    CatalogEdition,
    CatalogEditionDetail,
    CatalogFile,
    CatalogImport,
    CatalogRepository,
    CatalogUnitOfWork,
    CatalogWork,
    CategoryView,
    CoverResource,
    CoverStoragePort,
    DuplicateGroupView,
    FindReplaceItem,
    FindReplacePreview,
    LibraryOperationView,
    SeriesView,
    ShelfView,
)
from appv2.modules.catalog.domain import Work


class CatalogNotFound(Exception):
    pass


def _sequence_letters(value: int) -> str:
    result = ""
    current = max(value, 1)
    while current:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _render_replacement(
    template: str,
    *,
    match: str,
    value: str,
    index: int,
    number: int,
) -> str:
    replacements = {
        "{{ match }}": match,
        "{{ value }}": value,
        "{{ number }}": str(number),
        "{{ letter_upper }}": _sequence_letters(number),
        "{{ index }}": str(index),
    }
    rendered = template
    for marker, replacement in replacements.items():
        rendered = rendered.replace(marker, replacement)
    return rendered


def _primary_edition(
    repository: CatalogRepository,
    work_id: uuid.UUID,
) -> CatalogEdition | None:
    editions = repository.list_editions(work_id)
    return next(
        (edition for edition in editions if edition.primary), editions[0] if editions else None
    )


def _field_value(
    repository: CatalogRepository,
    work: CatalogWork,
    field: str,
) -> tuple[str | list[str], CatalogEdition | None]:
    if field == "title":
        return work.title, None
    if field == "author":
        return work.author or "", None
    if field == "description":
        return work.summary or "", None
    if field == "seriesName":
        value = work.metadata.get("seriesName")
        return value if isinstance(value, str) else "", None
    if field == "tags":
        value = work.metadata.get("tags")
        return (
            [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
        ), None
    edition = _primary_edition(repository, work.id)
    if edition is None:
        return "", None
    if field == "versionName":
        return edition.title, edition
    if field == "language":
        return edition.language or "", edition
    value = edition.metadata.get(field)
    return value if isinstance(value, str) else "", edition


def _replace_text(
    value: str,
    *,
    pattern: re.Pattern[str],
    replacement: str,
    index: int,
    number: int,
) -> tuple[str, int]:
    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        changed += 1
        return _render_replacement(
            replacement,
            match=match.group(0),
            value=value,
            index=index,
            number=number,
        )

    return pattern.sub(replace, value), changed


class CatalogService:
    def __init__(
        self,
        uow_factory: Callable[[], CatalogUnitOfWork],
        covers: CoverStoragePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._covers = covers

    def list_works(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None,
        media_type: str | None,
        status: str,
        series_name: str | None = None,
    ) -> tuple[list[CatalogWork], int]:
        with self._uow_factory() as uow:
            return uow.catalog.list_works(
                offset=(page - 1) * page_size,
                limit=page_size,
                query=query,
                media_type=media_type,
                status=status,
                series_name=series_name,
            )

    def list_series(
        self, *, page: int, page_size: int, status: str
    ) -> tuple[list[SeriesView], int]:
        with self._uow_factory() as uow:
            return uow.catalog.list_series(
                status=status,
                offset=(page - 1) * page_size,
                limit=page_size,
            )

    def get_work(self, work_id: uuid.UUID) -> tuple[CatalogWork, list[CatalogEdition]]:
        with self._uow_factory() as uow:
            work = uow.catalog.get_work(work_id)
            if work is None:
                raise CatalogNotFound
            return work, uow.catalog.list_editions(work_id)

    def get_work_detail(self, work_id: uuid.UUID) -> tuple[CatalogWork, list[CatalogEditionDetail]]:
        with self._uow_factory() as uow:
            work = uow.catalog.get_work(work_id)
            if work is None:
                raise CatalogNotFound
            details = [
                CatalogEditionDetail(
                    edition=edition,
                    files=tuple(uow.catalog.list_files(edition.id)),
                    volumes=tuple(uow.catalog.list_volumes(edition.id)),
                )
                for edition in uow.catalog.list_editions(work_id)
            ]
            return work, details

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
        metadata: dict[str, object] | None = None,
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
                metadata=metadata,
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

    def cover(self, work_id: uuid.UUID, *, size: str) -> CoverResource:
        with self._uow_factory() as uow:
            work = uow.catalog.get_work(work_id)
        if work is None or work.cover_key is None:
            raise CatalogNotFound
        try:
            return self._covers.open(work.cover_key, size)
        except FileNotFoundError as error:
            raise CatalogNotFound from error

    def upload_cover(self, work_id: uuid.UUID, stream: BinaryIO) -> CatalogWork:
        with self._uow_factory() as uow:
            if uow.catalog.get_work(work_id) is None:
                raise CatalogNotFound
        key = self._covers.store(work_id, stream)
        with self._uow_factory() as uow:
            work = uow.catalog.set_cover_key(work_id, key)
            if work is None:
                self._covers.delete(key)
                raise CatalogNotFound
            uow.commit()
            return work

    def bulk_upload_cover(
        self,
        *,
        work_ids: list[uuid.UUID],
        stream: BinaryIO,
    ) -> BulkMutationResult:
        valid_ids: list[uuid.UUID] = []
        previous_keys: dict[uuid.UUID, str] = {}
        skipped: list[BulkSkipped] = []
        with self._uow_factory() as uow:
            for work_id in dict.fromkeys(work_ids):
                work = uow.catalog.get_work(work_id)
                if work is None:
                    skipped.append(BulkSkipped(work_id, "WORK_NOT_FOUND"))
                else:
                    valid_ids.append(work_id)
                    if work.cover_key is not None:
                        previous_keys[work_id] = work.cover_key
        if not valid_ids:
            return BulkMutationResult(0, 0, tuple(skipped))
        keys = self._covers.store_many(valid_ids, stream)
        try:
            with self._uow_factory() as uow:
                for work_id, key in keys.items():
                    if uow.catalog.set_cover_key(work_id, key) is None:
                        raise CatalogNotFound
                uow.commit()
        except Exception:
            for key in keys.values():
                self._covers.delete(key)
            raise
        for work_id, previous_key in previous_keys.items():
            if previous_key != keys[work_id]:
                self._covers.delete(previous_key)
        return BulkMutationResult(
            updated=len(valid_ids),
            changed_values=len(valid_ids),
            skipped=tuple(skipped),
        )

    def update_edition(
        self,
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        *,
        title: str | None,
        language: str | None,
        metadata: dict[str, object] | None,
    ) -> CatalogEdition:
        normalized_title = " ".join(title.split()) if title is not None else None
        if normalized_title == "":
            raise ValueError("edition title cannot be empty")
        with self._uow_factory() as uow:
            edition = uow.catalog.update_edition(
                work_id,
                edition_id,
                title=normalized_title,
                language=language,
                metadata=metadata,
            )
            if edition is None:
                raise CatalogNotFound
            uow.commit()
            return edition

    def set_primary_edition(self, work_id: uuid.UUID, edition_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.catalog.set_primary_edition(work_id, edition_id):
                raise CatalogNotFound
            uow.commit()

    def split_edition(
        self,
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        *,
        title: str,
        author: str | None,
        copy_shelves: bool,
    ) -> uuid.UUID:
        normalized_title = " ".join(title.split())
        if not normalized_title:
            raise ValueError("work title cannot be empty")
        with self._uow_factory() as uow:
            new_work_id = uow.catalog.split_edition(
                work_id,
                edition_id,
                title=normalized_title,
                author=author,
                copy_shelves=copy_shelves,
            )
            if new_work_id is None:
                raise CatalogNotFound
            uow.commit()
            return new_work_id

    def move_volume(
        self,
        work_id: uuid.UUID,
        volume_id: uuid.UUID,
        *,
        direction: str,
    ) -> None:
        with self._uow_factory() as uow:
            if not uow.catalog.move_volume(
                work_id,
                volume_id,
                direction=direction,
            ):
                raise CatalogNotFound
            uow.commit()

    def move_volume_to(
        self,
        work_id: uuid.UUID,
        volume_id: uuid.UUID,
        *,
        target_edition_id: uuid.UUID,
    ) -> None:
        with self._uow_factory() as uow:
            if not uow.catalog.move_volume_to(
                work_id,
                volume_id,
                target_edition_id=target_edition_id,
            ):
                raise CatalogNotFound
            uow.commit()

    def import_file(self, imported: CatalogImport) -> CatalogEdition:
        with self._uow_factory() as uow:
            edition = uow.catalog.import_file(imported)
            uow.commit()
            return edition

    def publish_conversion(
        self,
        source_edition_id: uuid.UUID,
        converted: CatalogImport,
    ) -> CatalogEdition | None:
        with self._uow_factory() as uow:
            edition = uow.catalog.publish_conversion(
                source_edition_id,
                converted,
            )
            if edition is None:
                return None
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
        book_ids: list[uuid.UUID],
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
            if book_ids and not uow.catalog.replace_shelf_items(
                shelf.id,
                owner_id,
                book_ids,
            ):
                raise CatalogNotFound
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
        book_ids: list[uuid.UUID] | None,
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
            if (
                book_ids is not None
                and shelf.kind == "manual"
                and not uow.catalog.replace_shelf_items(
                    shelf_id,
                    owner_id,
                    book_ids,
                )
            ):
                raise CatalogNotFound
            uow.commit()
            return shelf

    def get_shelf(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[ShelfView, list[CatalogWork], list[uuid.UUID], int]:
        with self._uow_factory() as uow:
            shelf = uow.catalog.get_shelf(shelf_id, owner_id)
            result = uow.catalog.list_shelf_works(
                shelf_id,
                owner_id,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            if shelf is None or result is None:
                raise CatalogNotFound
            works, work_ids, total = result
            return shelf, works, work_ids, total

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

    def bulk_update_metadata(
        self,
        *,
        work_ids: list[uuid.UUID],
        author: str | None,
        publisher: str | None,
        series_name: str | None,
        add_tags: list[str],
        remove_tags: list[str],
    ) -> BulkMutationResult:
        updated = 0
        changed_values = 0
        skipped: list[BulkSkipped] = []
        with self._uow_factory() as uow:
            for work_id in dict.fromkeys(work_ids):
                work = uow.catalog.get_work(work_id)
                if work is None:
                    skipped.append(BulkSkipped(work_id, "WORK_NOT_FOUND"))
                    continue
                edition = _primary_edition(uow.catalog, work_id) if publisher is not None else None
                if publisher is not None and edition is None:
                    skipped.append(BulkSkipped(work_id, "PRIMARY_EDITION_NOT_FOUND"))
                    continue
                metadata: dict[str, object] = {}
                if series_name is not None:
                    metadata["seriesName"] = series_name
                    changed_values += 1
                if add_tags or remove_tags:
                    existing = work.metadata.get("tags")
                    tags = (
                        [item for item in existing if isinstance(item, str)]
                        if isinstance(existing, list)
                        else []
                    )
                    removed = {value.casefold() for value in remove_tags}
                    tags = [value for value in tags if value.casefold() not in removed]
                    known = {value.casefold() for value in tags}
                    for value in add_tags:
                        if value.casefold() not in known:
                            tags.append(value)
                            known.add(value.casefold())
                    metadata["tags"] = tags
                    changed_values += 1
                if author is not None or metadata:
                    uow.catalog.update_work(
                        work_id,
                        title=None,
                        author=author,
                        summary=None,
                        status=None,
                        metadata=metadata or None,
                    )
                    changed_values += int(author is not None)
                if publisher is not None:
                    assert edition is not None
                    uow.catalog.update_edition(
                        work_id,
                        edition.id,
                        title=None,
                        language=None,
                        metadata={"publisher": publisher},
                    )
                    changed_values += 1
                updated += 1
            uow.commit()
        return BulkMutationResult(
            updated=updated,
            changed_values=changed_values,
            skipped=tuple(skipped),
        )

    def find_replace(
        self,
        *,
        work_ids: list[uuid.UUID],
        field: str,
        find: str,
        replacement: str,
        regex: bool,
        case_sensitive: bool,
        start_number: int,
        apply: bool,
    ) -> tuple[FindReplacePreview, BulkMutationResult | None]:
        if not find:
            raise ValueError("find text cannot be empty")
        try:
            pattern = re.compile(
                find if regex else re.escape(find),
                0 if case_sensitive else re.IGNORECASE,
            )
        except re.error as error:
            raise ValueError("invalid regular expression") from error
        items: list[FindReplaceItem] = []
        skipped: list[BulkSkipped] = []
        changed_values = 0
        updated = 0
        with self._uow_factory() as uow:
            for index, work_id in enumerate(dict.fromkeys(work_ids), start=1):
                work = uow.catalog.get_work(work_id)
                if work is None:
                    skipped.append(BulkSkipped(work_id, "WORK_NOT_FOUND"))
                    continue
                before, edition = _field_value(uow.catalog, work, field)
                number = start_number + index - 1
                if isinstance(before, list):
                    after_items: list[str] = []
                    changes = 0
                    for value in before:
                        replaced, count = _replace_text(
                            value,
                            pattern=pattern,
                            replacement=replacement,
                            index=index,
                            number=number,
                        )
                        after_items.append(replaced)
                        changes += count
                    after: str | list[str] = after_items
                else:
                    after, changes = _replace_text(
                        before,
                        pattern=pattern,
                        replacement=replacement,
                        index=index,
                        number=number,
                    )
                if changes == 0:
                    continue
                if field == "title" and not str(after).strip():
                    skipped.append(BulkSkipped(work_id, "EMPTY_TITLE"))
                    continue
                items.append(
                    FindReplaceItem(
                        work_id=work_id,
                        title=work.title,
                        before=before,
                        after=after,
                    )
                )
                changed_values += changes
                updated += 1
                if apply:
                    self._apply_replaced_field(
                        uow.catalog,
                        work,
                        edition,
                        field=field,
                        value=after,
                    )
            if apply:
                uow.commit()
        preview = FindReplacePreview(
            changed_works=len(items),
            changed_values=changed_values,
            items=tuple(items),
        )
        result = BulkMutationResult(updated, changed_values, tuple(skipped)) if apply else None
        return preview, result

    @staticmethod
    def _apply_replaced_field(
        repository: CatalogRepository,
        work: CatalogWork,
        edition: CatalogEdition | None,
        *,
        field: str,
        value: str | list[str],
    ) -> None:
        if field in {"title", "author", "description", "seriesName", "tags"}:
            repository.update_work(
                work.id,
                title=str(value) if field == "title" else None,
                author=str(value) if field == "author" else None,
                summary=str(value) if field == "description" else None,
                status=None,
                metadata={field: value} if field in {"seriesName", "tags"} else None,
            )
            return
        if edition is None:
            return
        repository.update_edition(
            work.id,
            edition.id,
            title=str(value) if field == "versionName" else None,
            language=str(value) if field == "language" else None,
            metadata=({field: value} if field not in {"versionName", "language"} else None),
        )

    def bulk_shelf_membership(
        self,
        *,
        owner_id: uuid.UUID,
        shelf_id: uuid.UUID,
        work_ids: list[uuid.UUID],
        present: bool,
    ) -> BulkMutationResult:
        updated = 0
        skipped: list[BulkSkipped] = []
        with self._uow_factory() as uow:
            shelf = uow.catalog.get_shelf(shelf_id, owner_id)
            if shelf is None or shelf.kind != "manual":
                raise CatalogNotFound
            for work_id in dict.fromkeys(work_ids):
                changed = (
                    uow.catalog.add_shelf_item(shelf_id, owner_id, work_id)
                    if present
                    else uow.catalog.remove_shelf_item(shelf_id, owner_id, work_id)
                )
                if changed:
                    updated += 1
                else:
                    skipped.append(BulkSkipped(work_id, "WORK_OR_MEMBERSHIP_NOT_FOUND"))
            uow.commit()
        return BulkMutationResult(updated, updated, tuple(skipped))

    def list_duplicate_groups(self) -> list[DuplicateGroupView]:
        with self._uow_factory() as uow:
            return uow.catalog.list_duplicate_groups(limit=100)

    def merge_duplicate_works(
        self,
        *,
        actor_id: uuid.UUID,
        target_id: uuid.UUID,
        source_ids: list[uuid.UUID],
    ) -> LibraryOperationView:
        if target_id in source_ids or not source_ids:
            raise ValueError("duplicate merge requires distinct source works")
        with self._uow_factory() as uow:
            operation = uow.catalog.merge_duplicate_works(
                actor_id=actor_id,
                target_id=target_id,
                source_ids=list(dict.fromkeys(source_ids)),
            )
            if operation is None:
                raise CatalogNotFound
            uow.commit()
            return operation

    def undo_library_operation(
        self,
        *,
        actor_id: uuid.UUID,
        operation_id: uuid.UUID,
    ) -> LibraryOperationView:
        with self._uow_factory() as uow:
            operation = uow.catalog.undo_library_operation(
                actor_id=actor_id,
                operation_id=operation_id,
            )
            if operation is None:
                raise CatalogNotFound
            uow.commit()
            return operation

    def facets(self) -> dict[str, list[dict[str, object]]]:
        with self._uow_factory() as uow:
            return uow.catalog.category_facets()

    def list_categories(
        self,
        *,
        kind: str,
        query: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CategoryView], int]:
        with self._uow_factory() as uow:
            return uow.catalog.list_categories(
                kind=kind,
                query=query,
                offset=(page - 1) * page_size,
                limit=page_size,
            )

    def rename_category(self, category_id: uuid.UUID, name: str) -> CategoryView:
        normalized = " ".join(name.split())
        if not normalized:
            raise ValueError("category name cannot be empty")
        with self._uow_factory() as uow:
            category = uow.catalog.rename_category(category_id, normalized)
            if category is None:
                raise CatalogNotFound
            uow.commit()
            return category

    def merge_categories(
        self,
        *,
        kind: str,
        target_id: uuid.UUID,
        source_ids: list[uuid.UUID],
    ) -> CategoryView:
        if target_id in source_ids or not source_ids:
            raise ValueError("category merge requires distinct source categories")
        with self._uow_factory() as uow:
            category = uow.catalog.merge_categories(
                kind=kind,
                target_id=target_id,
                source_ids=source_ids,
            )
            if category is None:
                raise CatalogNotFound
            uow.commit()
            return category

    def delete_category(self, category_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.catalog.delete_category(category_id):
                raise CatalogNotFound
            uow.commit()
