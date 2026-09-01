"""SQLAlchemy adapter for auditable multi-Book application commands."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.contracts.media_capabilities import require_reader_type_for_format
from app.core.authorization import AuthorizationContext, book_visibility_predicate
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNodeMetadata,
    ReaderResourceProgress,
)
from app.models.common import cuid
from app.models.shelf import Shelf, ShelfBook
from app.modules.library.application.bulk_operations import (
    BulkBookOperationPort,
    BulkBookOperationResult,
    BulkCoverCommand,
    BulkCoverResult,
    BulkCoverSkipped,
    BulkFindReplaceCommand,
    BulkMetadataCommand,
    BulkReadingStatusCommand,
    BulkShelfMembershipCommand,
    FindReplacePreview,
    FindReplacePreviewItem,
    InvalidBulkBookOperationError,
    PreparedBulkCoverResult,
)
from app.modules.library.application.facet_sync import (
    BookFacetProjection,
    prepare_book_facet,
)
from app.modules.library.application.source_node_commands import (
    PublishedSourceNodeCover,
    SourceNodeMetadataChanges,
)
from app.modules.library.domain.authors import UNKNOWN_AUTHOR_PLACEHOLDER
from app.modules.library.domain.facets import (
    normalize_facet_name,
    unique_facet_names,
)
from app.modules.library.infrastructure import operations as operation_store
from app.modules.library.infrastructure.books import entity_record
from app.modules.library.infrastructure.facet_sync import (
    execute_book_facet_write,
    prepare_book_facet_write,
)
from app.modules.library.infrastructure.source_node_commands import (
    SqlAlchemySourceNodeMetadata,
)
from app.modules.library.infrastructure.source_node_cover import (
    FilesystemSourceNodeCoverPublication,
)

_TEMPLATE_VARIABLES = {
    "value",
    "match",
    "index",
    "index0",
    "number",
    "letter",
    "letter_upper",
}
_TEMPLATE_PATTERN = re.compile(
    r"{{\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s*\|\s*(lower|upper|title|trim))?\s*}}"
)


@dataclass(frozen=True, slots=True)
class _Replacement:
    book_id: str
    book_title: str
    field: str
    target_id: str
    before: str | tuple[str, ...]
    after: str | tuple[str, ...]
    resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class _PublishedBookCover:
    published: PublishedSourceNodeCover
    previous_stored_path: str | None


@dataclass(frozen=True, slots=True)
class _CoverCompletion:
    publications: tuple[_PublishedBookCover, ...]


def _now() -> datetime:
    return datetime.now(UTC)


def _sequence_letters(value: int) -> str:
    number = max(1, value)
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(97 + remainder) + result
    return result


def _render_template(
    template: str, *, value: str, match: str, index: int, number: int
) -> str:
    invalid = [
        name
        for name in re.findall(r"{{\s*([^}|\s]+)", template)
        if name not in _TEMPLATE_VARIABLES
    ]
    if invalid:
        raise InvalidBulkBookOperationError(
            f"UNSUPPORTED_TEMPLATE_VARIABLE:{invalid[0]}"
        )
    context: dict[str, object] = {
        "value": value,
        "match": match,
        "index": index + 1,
        "index0": index,
        "number": number,
        "letter": _sequence_letters(number),
        "letter_upper": _sequence_letters(number).upper(),
    }

    def replace_variable(template_match: re.Match[str]) -> str:
        variable, filter_name = template_match.groups()
        rendered = str(context[variable])
        if filter_name == "lower":
            return rendered.lower()
        if filter_name == "upper":
            return rendered.upper()
        if filter_name == "title":
            return rendered.title()
        if filter_name == "trim":
            return rendered.strip()
        return rendered

    return _TEMPLATE_PATTERN.sub(replace_variable, template)


def _replace_text(
    value: str,
    *,
    command: BulkFindReplaceCommand,
    index: int,
) -> str:
    flags = 0 if command.case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(
            command.find if command.regex else re.escape(command.find), flags
        )
    except re.error as error:
        raise InvalidBulkBookOperationError(f"INVALID_REGEX:{error}") from None

    def replace_match(match: re.Match[str]) -> str:
        return _render_template(
            command.replacement,
            value=value,
            match=match.group(0),
            index=index,
            number=max(1, command.start_number) + index,
        )

    return pattern.sub(replace_match, value)


def _operation_result(
    *,
    updated: int,
    changed_values: int,
    operation: dict[str, Any],
) -> BulkBookOperationResult:
    return BulkBookOperationResult(
        updated=updated,
        changed_values=changed_values,
        operation=operation_store.operation_summary(operation),
    )


class SqlAlchemyBulkBookOperations(BulkBookOperationPort):
    def __init__(
        self,
        db: Session,
        *,
        storage_root: Path | None = None,
    ) -> None:
        self._db = db
        self._storage_root = (
            storage_root.resolve() if storage_root is not None else None
        )
        self._cover_publication = (
            FilesystemSourceNodeCoverPublication(self._storage_root)
            if self._storage_root is not None
            else None
        )

    def accessible_book_ids(
        self,
        *,
        context: AuthorizationContext,
        book_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not book_ids:
            return ()
        accessible = {
            str(book_id)
            for book_id in self._db.scalars(
                select(LibraryBook.id).where(
                    LibraryBook.id.in_(book_ids),
                    book_visibility_predicate(context),
                )
            ).all()
        }
        return tuple(book_id for book_id in book_ids if book_id in accessible)

    def _metadata_by_book(
        self, book_ids: tuple[str, ...]
    ) -> dict[str, LibraryBookMetadata]:
        return {
            str(metadata.book_id): metadata
            for metadata in self._db.scalars(
                select(LibraryBookMetadata).where(
                    LibraryBookMetadata.book_id.in_(book_ids)
                )
            ).all()
        }

    def _tags_by_book(self, book_ids: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
        result: dict[str, list[str]] = {book_id: [] for book_id in book_ids}
        rows = self._db.execute(
            select(LibraryBookFacet.book_id, LibraryFacet.name)
            .join(LibraryFacet, LibraryFacet.id == LibraryBookFacet.facet_id)
            .where(
                LibraryBookFacet.book_id.in_(book_ids),
                LibraryFacet.kind == "TAG",
            )
            .order_by(LibraryBookFacet.book_id, LibraryBookFacet.sort_order)
        ).all()
        for book_id, name in rows:
            result.setdefault(str(book_id), []).append(str(name))
        return {book_id: tuple(names) for book_id, names in result.items()}

    def _inverse(self, book_ids: tuple[str, ...]) -> dict[str, object]:
        metadata = self._metadata_by_book(book_ids)
        links = self._db.scalars(
            select(LibraryBookFacet).where(LibraryBookFacet.book_id.in_(book_ids))
        ).all()
        facet_ids = tuple(dict.fromkeys(str(link.facet_id) for link in links))
        facets = (
            self._db.scalars(
                select(LibraryFacet).where(LibraryFacet.id.in_(facet_ids))
            ).all()
            if facet_ids
            else []
        )
        return {
            "books": [
                {
                    "id": book_id,
                    "title": row.title,
                    "normalizedTitle": row.normalized_title,
                    "author": row.author,
                    "normalizedAuthor": row.normalized_author,
                    "description": row.description,
                    "seriesName": row.series_name,
                    "seriesIndex": row.series_index,
                    "updatedAt": row.updated_at,
                }
                for book_id in book_ids
                if (row := metadata.get(book_id)) is not None
            ],
            "bookLinks": [entity_record(link) for link in links],
            "facets": [entity_record(facet) for facet in facets],
        }

    @staticmethod
    def _next_tags(
        current: tuple[str, ...], add: tuple[str, ...], remove: tuple[str, ...]
    ) -> tuple[str, ...]:
        removed = {normalize_facet_name(value) for value in remove}
        return unique_facet_names(
            [
                *(
                    value
                    for value in current
                    if normalize_facet_name(value) not in removed
                ),
                *add,
            ]
        )

    def update_metadata(self, command: BulkMetadataCommand) -> BulkBookOperationResult:
        metadata = self._metadata_by_book(command.book_ids)
        tags = self._tags_by_book(command.book_ids)
        now = _now()
        prepared = []
        changed_values = 0
        for book_id in command.book_ids:
            row = metadata.get(book_id)
            if row is None:
                continue
            author = row.author
            series_name = row.series_name
            if "author" in command.fields:
                author = command.fields["author"].strip() or UNKNOWN_AUTHOR_PLACEHOLDER
            if "seriesName" in command.fields:
                series_name = command.fields["seriesName"].strip() or None
            next_tags = self._next_tags(
                tags.get(book_id, ()), command.add_tags, command.remove_tags
            )
            author_changed = "author" in command.fields and (
                row.author != author
                or row.normalized_author
                != (normalize_facet_name(str(author or "")) or None)
            )
            series_changed = "seriesName" in command.fields and (
                row.series_name != series_name
            )
            tags_changed = tags.get(book_id, ()) != next_tags
            if not (author_changed or series_changed or tags_changed):
                continue
            changed_values += sum((author_changed, series_changed, tags_changed))
            prepared.append(
                (
                    row,
                    author,
                    series_name,
                    next_tags,
                    author_changed,
                    series_changed,
                    prepare_book_facet(
                        BookFacetProjection(
                            book_id=book_id,
                            author=author,
                            tags_source=self._tags_json(next_tags),
                            series_name=series_name,
                        )
                    ),
                )
            )
        operation = operation_store.prepare_operation_write(
            user_id=command.context.user_id,
            action="BULK_UPDATE_METADATA",
            target_type="books",
            target_id=None,
            summary=f"批量更新 {len(prepared)} 本图书的元数据",
            payload={
                "bookIds": list(command.book_ids),
                "fields": dict(command.fields),
                "addTags": list(command.add_tags),
                "removeTags": list(command.remove_tags),
            },
            inverse=self._inverse(tuple(str(item[0].book_id) for item in prepared)),
            now=now,
            undoable=bool(prepared),
        )
        facet_write = prepare_book_facet_write(
            tuple(item[6] for item in prepared), now=now
        )
        for (
            row,
            author,
            series_name,
            _next_tags,
            author_changed,
            series_changed,
            _facet,
        ) in prepared:
            if author_changed:
                row.author = author
                row.normalized_author = normalize_facet_name(str(author or "")) or None
            if series_changed:
                row.series_name = series_name
                if series_name is None:
                    row.series_index = None
            row.updated_at = now
        execute_book_facet_write(self._db, facet_write)
        operation_store.write_prepared_operation(self._db, operation)
        return _operation_result(
            updated=len(prepared),
            changed_values=changed_values,
            operation=operation.record,
        )

    @staticmethod
    def _tags_json(tags: tuple[str, ...]) -> str:
        return json.dumps(tags, ensure_ascii=False)

    def _find_replacements(
        self, command: BulkFindReplaceCommand
    ) -> tuple[_Replacement, ...]:
        _render_template(
            command.replacement,
            value="",
            match="",
            index=0,
            number=max(1, command.start_number),
        )
        metadata = self._metadata_by_book(command.book_ids)
        tags = self._tags_by_book(command.book_ids)
        replacements: list[_Replacement] = []
        if command.field == "resourceTitle":
            resources = self._db.execute(
                select(LibraryReadableResource, LibraryReadableResourceMetadata)
                .join(
                    LibraryReadableResourceMetadata,
                    LibraryReadableResourceMetadata.resource_id
                    == LibraryReadableResource.id,
                )
                .where(LibraryReadableResource.book_id.in_(command.book_ids))
                .order_by(
                    LibraryReadableResource.book_id,
                    LibraryReadableResourceMetadata.resource_index,
                    LibraryReadableResource.id,
                )
            ).all()
            index_by_book = {
                book_id: index for index, book_id in enumerate(command.book_ids)
            }
            for resource, resource_metadata in resources:
                book_id = str(resource.book_id)
                before_resource_title = str(resource_metadata.title or "")
                after_resource_title = _replace_text(
                    before_resource_title,
                    command=command,
                    index=index_by_book[book_id],
                )
                if before_resource_title != after_resource_title:
                    book_metadata = metadata.get(book_id)
                    replacements.append(
                        _Replacement(
                            book_id=book_id,
                            book_title=book_metadata.title
                            if book_metadata is not None
                            else "未命名图书",
                            field=command.field,
                            target_id=resource.id,
                            resource_id=resource.id,
                            before=before_resource_title,
                            after=after_resource_title,
                        )
                    )
            return tuple(replacements)

        field_map = {
            "title": "title",
            "author": "author",
            "description": "description",
            "seriesName": "series_name",
        }
        for index, book_id in enumerate(command.book_ids):
            row = metadata.get(book_id)
            if row is None:
                continue
            if command.field == "tags":
                before_tags = tags.get(book_id, ())
                after_tags = unique_facet_names(
                    value
                    for tag in before_tags
                    if (
                        value := _replace_text(
                            tag, command=command, index=index
                        ).strip()
                    )
                )
                before_value: str | tuple[str, ...] = before_tags
                after_value: str | tuple[str, ...] = after_tags
            else:
                before_value = str(getattr(row, field_map[command.field]) or "")
                after_value = _replace_text(before_value, command=command, index=index)
            if before_value != after_value:
                replacements.append(
                    _Replacement(
                        book_id=book_id,
                        book_title=row.title or "未命名图书",
                        field=command.field,
                        target_id=book_id,
                        before=before_value,
                        after=after_value,
                    )
                )
        return tuple(replacements)

    def preview_find_replace(
        self, command: BulkFindReplaceCommand
    ) -> FindReplacePreview:
        replacements = self._find_replacements(command)
        return FindReplacePreview(
            changed_books=len({replacement.book_id for replacement in replacements}),
            changed_values=len(replacements),
            items=tuple(
                FindReplacePreviewItem(
                    book_id=replacement.book_id,
                    title=replacement.book_title,
                    before=replacement.before,
                    after=replacement.after,
                    resource_id=replacement.resource_id,
                )
                for replacement in replacements[:30]
            ),
        )

    def apply_find_replace(
        self, command: BulkFindReplaceCommand
    ) -> BulkBookOperationResult:
        replacements = self._find_replacements(command)
        changed_book_ids = tuple(
            book_id
            for book_id in command.book_ids
            if any(item.book_id == book_id for item in replacements)
        )
        metadata = self._metadata_by_book(command.book_ids)
        tags = self._tags_by_book(command.book_ids)
        next_tags = dict(tags)
        now = _now()
        resource_snapshots: list[dict[str, object]] = []
        inverse = self._inverse(changed_book_ids)
        for replacement in replacements:
            if replacement.field == "resourceTitle":
                resource_metadata = self._db.get(
                    LibraryReadableResourceMetadata, replacement.target_id
                )
                if resource_metadata is None:
                    continue
                resource_snapshots.append(
                    {
                        "id": resource_metadata.resource_id,
                        "title": resource_metadata.title,
                        "updatedAt": resource_metadata.updated_at,
                    }
                )
                resource_metadata.title = str(replacement.after)
                resource_metadata.updated_at = now
                continue
            row = metadata.get(replacement.book_id)
            if row is None:
                continue
            if replacement.field == "title":
                title = str(replacement.after).strip()
                if not title:
                    raise InvalidBulkBookOperationError("EMPTY_BOOK_TITLE")
                row.title = title
                row.normalized_title = normalize_facet_name(title)
            elif replacement.field == "author":
                author = str(replacement.after).strip() or UNKNOWN_AUTHOR_PLACEHOLDER
                row.author = author
                row.normalized_author = normalize_facet_name(author)
            elif replacement.field == "description":
                row.description = str(replacement.after).strip() or None
            elif replacement.field == "seriesName":
                row.series_name = str(replacement.after).strip() or None
                if row.series_name is None:
                    row.series_index = None
            elif replacement.field == "tags":
                next_tags[replacement.book_id] = tuple(replacement.after)
            row.updated_at = now
        inverse["resources"] = resource_snapshots
        facet_fields = {"author", "seriesName", "tags"}
        facet_book_ids = tuple(
            book_id
            for book_id in changed_book_ids
            if any(
                replacement.book_id == book_id and replacement.field in facet_fields
                for replacement in replacements
            )
        )
        if facet_book_ids:
            facet_write = prepare_book_facet_write(
                tuple(
                    prepare_book_facet(
                        BookFacetProjection(
                            book_id=book_id,
                            author=metadata[book_id].author,
                            tags_source=self._tags_json(next_tags.get(book_id, ())),
                            series_name=metadata[book_id].series_name,
                        )
                    )
                    for book_id in facet_book_ids
                ),
                now=now,
            )
            execute_book_facet_write(self._db, facet_write)
        operation = operation_store.create_operation(
            self._db,
            user_id=command.context.user_id,
            action="BULK_FIND_REPLACE",
            target_type="books",
            target_id=None,
            summary=f"批量替换 {len(replacements)} 处元数据",
            payload={
                "bookIds": list(command.book_ids),
                "field": command.field,
                "find": command.find,
                "replacement": command.replacement,
                "regex": command.regex,
                "caseSensitive": command.case_sensitive,
                "startNumber": command.start_number,
            },
            inverse=inverse,
            now=now,
            undoable=bool(replacements),
        )
        return _operation_result(
            updated=len(changed_book_ids),
            changed_values=len(replacements),
            operation=operation,
        )

    def update_shelf_membership(
        self, command: BulkShelfMembershipCommand
    ) -> BulkBookOperationResult:
        shelf = self._db.scalar(
            select(Shelf).where(
                Shelf.id == command.shelf_id,
                Shelf.owner_user_id == command.context.user_id,
                Shelf.kind == "STATIC",
            )
        )
        if shelf is None:
            raise InvalidBulkBookOperationError("STATIC_SHELF_REQUIRED")
        existing = {
            str(book_id)
            for book_id in self._db.scalars(
                select(ShelfBook.book_id).where(
                    ShelfBook.shelf_id == shelf.id,
                    ShelfBook.book_id.in_(command.book_ids),
                )
            ).all()
        }
        now = _now()
        if command.membership == "ADD":
            changed = tuple(
                book_id for book_id in command.book_ids if book_id not in existing
            )
            if changed:
                self._db.execute(
                    sqlite_insert(ShelfBook)
                    .values(
                        [
                            {
                                "shelf_id": shelf.id,
                                "book_id": book_id,
                                "created_at": now,
                            }
                            for book_id in changed
                        ]
                    )
                    .on_conflict_do_nothing(
                        index_elements=[ShelfBook.shelf_id, ShelfBook.book_id]
                    )
                )
        else:
            changed = tuple(
                book_id for book_id in command.book_ids if book_id in existing
            )
            if changed:
                self._db.execute(
                    delete(ShelfBook).where(
                        ShelfBook.shelf_id == shelf.id,
                        ShelfBook.book_id.in_(changed),
                    )
                )
        operation = operation_store.create_operation(
            self._db,
            user_id=command.context.user_id,
            action="BULK_SHELF_MEMBERSHIP",
            target_type="shelf",
            target_id=shelf.id,
            summary=f"批量{('加入' if command.membership == 'ADD' else '移除')}书架 {len(changed)} 本图书",
            payload={
                "bookIds": list(command.book_ids),
                "shelfId": shelf.id,
                "membership": command.membership,
            },
            inverse={"existingBookIds": sorted(existing)},
            now=now,
            undoable=False,
        )
        return _operation_result(
            updated=len(changed), changed_values=len(changed), operation=operation
        )

    def update_reading_status(
        self, command: BulkReadingStatusCommand
    ) -> BulkBookOperationResult:
        resources = self._db.execute(
            select(
                LibraryReadableResource.id,
                LibraryReadableResource.book_id,
                LibraryReadableResource.format,
            )
            .where(
                LibraryReadableResource.book_id.in_(command.book_ids),
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
            )
            .order_by(LibraryReadableResource.book_id, LibraryReadableResource.id)
        ).all()
        resource_ids = tuple(str(row.id) for row in resources)
        progress_rows = (
            self._db.scalars(
                select(ReaderResourceProgress).where(
                    ReaderResourceProgress.user_id == command.context.user_id,
                    ReaderResourceProgress.resource_id.in_(resource_ids),
                )
            ).all()
            if resource_ids
            else []
        )
        progress_by_resource = {str(row.resource_id): row for row in progress_rows}
        if command.status == "UNREAD":
            changed_resource_ids = tuple(progress_by_resource)
        else:
            changed_resource_ids = tuple(
                str(row.id)
                for row in resources
                if (progress := progress_by_resource.get(str(row.id))) is None
                or float(progress.percent) < 100.0
            )
        now = _now()
        if command.status == "UNREAD":
            if changed_resource_ids:
                self._db.execute(
                    delete(ReaderResourceProgress).where(
                        ReaderResourceProgress.user_id == command.context.user_id,
                        ReaderResourceProgress.resource_id.in_(changed_resource_ids),
                    )
                )
        elif changed_resource_ids:
            values = [
                {
                    "id": cuid(),
                    "user_id": command.context.user_id,
                    "resource_id": str(row.id),
                    "reader_type": require_reader_type_for_format(
                        str(row.format)
                    ).value,
                    "position": "0",
                    "percent": 100.0,
                    "extra": "{}",
                    "schema_version": 3,
                    "progressed_at": now,
                    "source_protocol": "SHUKU_WEB",
                    "created_at": now,
                    "updated_at": now,
                }
                for row in resources
                if str(row.id) in changed_resource_ids
            ]
            self._db.execute(
                sqlite_insert(ReaderResourceProgress)
                .values(values)
                .on_conflict_do_update(
                    index_elements=[
                        ReaderResourceProgress.user_id,
                        ReaderResourceProgress.resource_id,
                    ],
                    set_={
                        ReaderResourceProgress.percent: 100.0,
                        ReaderResourceProgress.position: "0",
                        ReaderResourceProgress.updated_at: now,
                        ReaderResourceProgress.progressed_at: now,
                    },
                )
            )
        affected_books = {
            str(row.book_id) for row in resources if str(row.id) in changed_resource_ids
        }
        operation = operation_store.create_operation(
            self._db,
            user_id=command.context.user_id,
            action="BULK_READING_STATUS",
            target_type="books",
            target_id=None,
            summary=f"批量设置 {len(affected_books)} 本图书为{('未读' if command.status == 'UNREAD' else '已读')}",
            payload={"bookIds": list(command.book_ids), "status": command.status},
            inverse={"progress": [entity_record(row) for row in progress_rows]},
            now=now,
            undoable=False,
        )
        return _operation_result(
            updated=len(affected_books),
            changed_values=len(changed_resource_ids),
            operation=operation,
        )

    @staticmethod
    def _prepare_cover_image(
        image: Image.Image,
        *,
        ratio: str | None,
        max_dimension: int,
        quality: int,
    ) -> bytes:
        prepared = ImageOps.exif_transpose(image).convert("RGB")
        ratios = {"2:3": 2 / 3, "3:4": 3 / 4, "1:1": 1.0}
        target_ratio = ratios.get(str(ratio or ""))
        if target_ratio:
            width, height = prepared.size
            current_ratio = width / height if height else target_ratio
            if current_ratio > target_ratio:
                crop_width = max(1, round(height * target_ratio))
                left = max(0, (width - crop_width) // 2)
                prepared = prepared.crop((left, 0, left + crop_width, height))
            elif current_ratio < target_ratio:
                crop_height = max(1, round(width / target_ratio))
                top = max(0, (height - crop_height) // 2)
                prepared = prepared.crop((0, top, width, top + crop_height))
        if max(prepared.size) > max_dimension:
            prepared.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        output = BytesIO()
        prepared.save(
            output,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )
        return output.getvalue()

    def _stored_cover_path(self, stored_path: str | None) -> Path | None:
        if self._storage_root is None or not stored_path:
            return None
        candidate = (self._storage_root / stored_path).resolve()
        try:
            candidate.relative_to(self._storage_root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def prepare_covers(self, command: BulkCoverCommand) -> PreparedBulkCoverResult:
        if self._storage_root is None or self._cover_publication is None:
            raise RuntimeError("bulk cover publication is not configured")
        quality = max(40, min(95, command.quality))
        max_dimension = max(600, min(3200, command.max_dimension))
        uploaded_image: Image.Image | None = None
        if command.cover_content is not None:
            if (
                not command.cover_content
                or len(command.cover_content) > 12 * 1024 * 1024
            ):
                raise InvalidBulkBookOperationError("INVALID_COVER_FILE_SIZE")
            try:
                with Image.open(BytesIO(command.cover_content)) as image:
                    image.load()
                    uploaded_image = image.copy()
            except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
                raise InvalidBulkBookOperationError("INVALID_COVER_IMAGE") from None

        rows = self._db.execute(
            select(LibraryBook, LibraryBookMetadata)
            .join(
                LibraryBookMetadata,
                LibraryBookMetadata.book_id == LibraryBook.id,
            )
            .where(LibraryBook.id.in_(command.book_ids))
        ).all()
        by_id = {str(book.id): (book, metadata) for book, metadata in rows}
        now = _now()
        publications: list[_PublishedBookCover] = []
        skipped: list[BulkCoverSkipped] = []
        inverse_books: list[dict[str, object]] = []
        inverse_source_nodes: list[dict[str, object]] = []
        source_metadata_port = SqlAlchemySourceNodeMetadata(self._db)
        try:
            for book_id in command.book_ids:
                context = by_id.get(book_id)
                if context is None:
                    skipped.append(BulkCoverSkipped(book_id, "BOOK_NOT_FOUND"))
                    continue
                book, metadata = context
                source_metadata = self._db.get(
                    LibrarySourceNodeMetadata, book.source_node_id
                )
                inverse_books.append(
                    {
                        "id": book.id,
                        "coverPath": metadata.cover_path,
                        "coverStatus": metadata.cover_status,
                        "updatedAt": metadata.updated_at,
                    }
                )
                if source_metadata is not None:
                    inverse_source_nodes.append(entity_record(source_metadata))

                source_image: Image.Image
                if uploaded_image is not None:
                    source_image = uploaded_image.copy()
                else:
                    source_path = self._stored_cover_path(metadata.cover_path)
                    if source_path is None:
                        skipped.append(BulkCoverSkipped(book.id, "BOOK_COVER_REQUIRED"))
                        continue
                    try:
                        with Image.open(source_path) as image:
                            image.load()
                            source_image = image.copy()
                    except (
                        OSError,
                        UnidentifiedImageError,
                        Image.DecompressionBombError,
                    ):
                        skipped.append(
                            BulkCoverSkipped(book.id, "BOOK_COVER_UNREADABLE")
                        )
                        continue
                cover_content = self._prepare_cover_image(
                    source_image,
                    ratio=command.ratio if command.action == "crop" else None,
                    max_dimension=max_dimension,
                    quality=quality,
                )
                previous_path = (
                    source_metadata.cover_path
                    if source_metadata is not None
                    else metadata.cover_path
                )
                prepared_cover = self._cover_publication.prepare(
                    source_node_id=book.source_node_id,
                    content=cover_content,
                )
                published = self._cover_publication.publish(
                    prepared_cover,
                    previous_stored_path=previous_path,
                )
                publications.append(
                    _PublishedBookCover(
                        published=published,
                        previous_stored_path=previous_path,
                    )
                )
                updated = source_metadata_port.update_metadata(
                    book_id=book.id,
                    source_node_id=book.source_node_id,
                    changes=SourceNodeMetadataChanges(
                        title=source_metadata.title
                        if source_metadata is not None and source_metadata.title
                        else metadata.title,
                        description=source_metadata.description
                        if source_metadata is not None
                        else metadata.description,
                        cover_path=prepared_cover.stored_path,
                        replace_cover=True,
                    ),
                )
                if not updated:
                    raise RuntimeError("Book anchor SourceNode disappeared")
        except Exception:
            for item in reversed(publications):
                self._cover_publication.revert(item.published)
            raise

        updated_count = len(publications)
        operation = operation_store.create_operation(
            self._db,
            user_id=command.context.user_id,
            action="BULK_BOOK_COVERS",
            target_type="books",
            target_id=None,
            summary=f"批量处理 {updated_count} 本图书的封面",
            payload={
                "bookIds": list(command.book_ids),
                "action": command.action,
                "ratio": command.ratio if command.action == "crop" else None,
                "quality": quality,
                "maxDimension": max_dimension,
                "skipped": [
                    {"bookId": item.book_id, "reason": item.reason} for item in skipped
                ],
            },
            inverse={
                "books": inverse_books,
                "sourceNodes": inverse_source_nodes,
            },
            now=now,
            undoable=False,
        )
        completion = _CoverCompletion(
            publications=tuple(publications),
        )
        return PreparedBulkCoverResult(
            outcome=BulkCoverResult(
                updated=updated_count,
                skipped=tuple(skipped),
                operation=operation_store.operation_summary(operation),
            ),
            completion_token=completion,
        )

    def complete_covers(self, prepared: PreparedBulkCoverResult) -> None:
        completion = prepared.completion_token
        if not isinstance(completion, _CoverCompletion):
            raise TypeError("invalid bulk cover completion token")
        if self._cover_publication is None:
            raise RuntimeError("bulk cover publication is not configured")
        for item in completion.publications:
            self._cover_publication.complete(
                item.published,
                previous_stored_path=item.previous_stored_path,
            )

    def revert_covers(self, prepared: PreparedBulkCoverResult) -> None:
        completion = prepared.completion_token
        if not isinstance(completion, _CoverCompletion):
            return
        if self._cover_publication is None:
            return
        for item in reversed(completion.publications):
            self._cover_publication.revert(item.published)


__all__ = ["SqlAlchemyBulkBookOperations"]
