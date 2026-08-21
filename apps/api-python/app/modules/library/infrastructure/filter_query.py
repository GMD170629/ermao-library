"""Compile validated library filters against Book/Resource/Asset fields."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from typing import cast as typing_cast

from sqlalchemy import (
    ColumnElement,
    Float,
    and_,
    cast,
    exists,
    func,
    not_,
    or_,
    select,
)
from sqlalchemy.orm import Session, aliased

from app.core.authorization import (
    AuthorizationContext,
    resource_visibility_predicate,
)
from app.models import (
    Library,
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    OrganizeJob,
    ReaderResourceProgress,
)
from app.models.shelf import Shelf, ShelfBook
from app.modules.library.application.filter_ast import FilterCondition, FilterExpression
from app.modules.library.domain.authors import UNKNOWN_AUTHOR_PLACEHOLDER

BOOK_TEXT_FIELDS = {
    "title": LibraryBookMetadata.title,
    "author": LibraryBookMetadata.author,
    "description": LibraryBookMetadata.description,
    "series": LibraryBookMetadata.series_name,
    "publicationStatus": LibraryBookMetadata.publication_status,
    "trackingStatus": LibraryBookMetadata.tracking_status,
}
BOOK_NUMBER_FIELDS = {
    "seriesIndex": LibraryBookMetadata.series_index,
    "metadataQuality": LibraryBookMetadata.metadata_quality,
}
BOOK_DATE_FIELDS = {
    "createdAt": LibraryBook.created_at,
    "updatedAt": LibraryBook.updated_at,
}
RESOURCE_TEXT_FIELDS = {
    "resourceTitle": "title",
    "narrator": "narrator",
    "format": "format",
    "importStatus": "import_state",
}


def _column(expression: object) -> ColumnElement[object]:
    return typing_cast(ColumnElement[object], expression)


def _normalized_text(expression: object) -> ColumnElement[str]:
    return func.lower(func.trim(func.coalesce(_column(expression), "")))


def _literal_like_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _text(
    expression: object,
    condition: FilterCondition,
    *,
    empty_values: tuple[str, ...] = (),
) -> ColumnElement[bool]:
    normalized = _normalized_text(expression)
    empty_predicate = normalized.in_(
        ("", *(value.casefold() for value in empty_values))
    )
    if condition.operator == "is_empty":
        return empty_predicate
    if condition.operator == "is_not_empty":
        return not_(empty_predicate)
    value = _literal_like_value(str(condition.value or "").casefold())
    if condition.operator in {"contains", "not_contains"}:
        result: ColumnElement[bool] = normalized.like(f"%{value}%", escape="\\")
        return not_(result) if condition.operator == "not_contains" else result
    if condition.operator == "starts_with":
        return normalized.like(f"{value}%", escape="\\")
    if condition.operator == "ends_with":
        return normalized.like(f"%{value}", escape="\\")
    result = normalized == value
    return not_(result) if condition.operator == "not_equals" else result


def _number(
    expression: object, condition: FilterCondition, *, scale: float = 1
) -> ColumnElement[bool]:
    column = _column(expression)
    if condition.operator == "is_empty":
        return column.is_(None)
    if condition.operator == "is_not_empty":
        return column.is_not(None)
    numeric = cast(column, Float)
    if condition.operator == "between":
        assert isinstance(condition.value, tuple)
        return numeric.between(
            float(condition.value[0]) * scale, float(condition.value[1]) * scale
        )
    value = float(str(condition.value)) * scale
    return {
        "equals": numeric == value,
        "not_equals": numeric != value,
        "greater_than": numeric > value,
        "greater_or_equal": numeric >= value,
        "less_than": numeric < value,
        "less_or_equal": numeric <= value,
    }[condition.operator]


def _date(expression: object, condition: FilterCondition) -> ColumnElement[bool]:
    column = _column(expression)
    if condition.operator == "is_empty":
        return column.is_(None)
    if condition.operator == "is_not_empty":
        return column.is_not(None)
    if condition.operator == "between":
        assert isinstance(condition.value, tuple)
        start = datetime.fromisoformat(condition.value[0]).replace(tzinfo=UTC)
        end = datetime.fromisoformat(condition.value[1]).replace(
            tzinfo=UTC
        ) + timedelta(days=1)
        return and_(column >= start, column < end)
    start = datetime.fromisoformat(str(condition.value)).replace(tzinfo=UTC)
    end = start + timedelta(days=1)
    if condition.operator == "equals":
        return and_(column >= start, column < end)
    if condition.operator == "not_equals":
        return not_(and_(column >= start, column < end))
    if condition.operator == "after":
        return column >= end
    if condition.operator == "on_or_after":
        return column >= start
    if condition.operator == "before":
        return column < start
    return column < end


def _visible_resource(
    context: AuthorizationContext,
    resource: type[LibraryReadableResource],
    book: type[LibraryBook],
) -> ColumnElement[bool]:
    return and_(
        resource.book_id == book.id, resource_visibility_predicate(context, resource)
    )


def _relation_text(
    statement: Any,
    expression: object,
    condition: FilterCondition,
) -> ColumnElement[bool]:
    negative = condition.operator in {"not_contains", "not_equals", "is_empty"}
    positive = FilterCondition(
        field=condition.field,
        operator={
            "not_contains": "contains",
            "not_equals": "equals",
            "is_empty": "is_not_empty",
        }.get(condition.operator, condition.operator),
        value=condition.value,
    )
    predicate = exists(statement.where(_text(expression, positive)))
    return not_(predicate) if negative else predicate


def resolve_library_roots(
    db: Session,
    expression: FilterExpression,
    context: AuthorizationContext,
) -> dict[str, str]:
    conditions = tuple(c for c in expression.conditions if c.field == "library")
    if not conditions:
        return {}
    include_all = any(c.operator in {"is_empty", "is_not_empty"} for c in conditions)
    requested_ids = {str(c.value) for c in conditions if c.value is not None}
    statement = select(Library.id, Library.root_path)
    if not context.is_admin:
        statement = statement.where(Library.id.in_(context.library_ids))
    if not include_all:
        if not requested_ids:
            return {}
        statement = statement.where(Library.id.in_(requested_ids))
    return {
        str(library_id): _normalized_library_root(str(root_path))
        for library_id, root_path in db.execute(statement).all()
        if _normalized_library_root(str(root_path))
    }


def _normalized_library_root(root_path: str) -> str:
    normalized = root_path.strip()
    if normalized in {"/", "\\"}:
        return normalized
    if (
        len(normalized) >= 3
        and normalized[1] == ":"
        and set(normalized[2:]).issubset({"/", "\\"})
    ):
        return normalized[:3]
    return normalized.rstrip("/\\")


def _reading_status(
    context: AuthorizationContext, user_id: str, condition: FilterCondition
) -> ColumnElement[bool]:
    resource = aliased(LibraryReadableResource)
    progress = aliased(ReaderResourceProgress)
    visible = and_(
        resource_visibility_predicate(context, resource),
        resource.book_id == LibraryBook.id,
    )
    has_resource = exists(select(resource.id).where(visible))
    if condition.operator == "is_empty":
        return ~has_resource
    if condition.operator == "is_not_empty":
        return has_resource
    started = exists(
        select(progress.id)
        .join(resource, resource.id == progress.resource_id)
        .where(visible, progress.user_id == user_id, progress.percent > 0)
    )
    unfinished = exists(
        select(resource.id)
        .outerjoin(
            progress,
            and_(progress.resource_id == resource.id, progress.user_id == user_id),
        )
        .where(visible, func.coalesce(progress.percent, 0) < 100)
    )
    status = str(condition.value or "UNREAD").upper()
    predicate = (
        and_(has_resource, ~unfinished)
        if status == "FINISHED"
        else and_(started, unfinished)
        if status == "READING"
        else ~started
    )
    return not_(predicate) if condition.operator == "not_equals" else predicate


def _condition(
    condition: FilterCondition,
    *,
    context: AuthorizationContext,
    user_id: str | None,
    shelf_owner_user_id: str | None,
    library_roots: Mapping[str, str],
) -> ColumnElement[bool]:
    del library_roots
    field = condition.field
    if field == "readingStatus" and user_id:
        return _reading_status(context, user_id, condition)
    if field == "author":
        return _text(
            LibraryBookMetadata.author,
            condition,
            empty_values=(UNKNOWN_AUTHOR_PLACEHOLDER,),
        )
    if field in BOOK_TEXT_FIELDS:
        return _text(BOOK_TEXT_FIELDS[field], condition)
    if field in BOOK_NUMBER_FIELDS:
        return _number(BOOK_NUMBER_FIELDS[field], condition)
    if field in BOOK_DATE_FIELDS:
        return _date(BOOK_DATE_FIELDS[field], condition)

    resource = aliased(LibraryReadableResource)
    resource_metadata = aliased(LibraryReadableResourceMetadata)
    visible = _visible_resource(context, resource, LibraryBook)
    resource_base = (
        select(resource.id)
        .join(resource_metadata, resource_metadata.resource_id == resource.id)
        .where(visible)
    )
    if field in RESOURCE_TEXT_FIELDS or field == "mediaKind":
        expression = (
            resource.media_kind
            if field == "mediaKind"
            else getattr(
                resource_metadata
                if field in {"resourceTitle", "narrator"}
                else resource,
                RESOURCE_TEXT_FIELDS[field],
            )
        )
        return _relation_text(resource_base, expression, condition)
    if field == "tag":
        link = aliased(LibraryBookFacet)
        facet = aliased(LibraryFacet)
        return _relation_text(
            select(link.book_id)
            .join(facet, facet.id == link.facet_id)
            .where(link.book_id == LibraryBook.id, facet.kind == "TAG"),
            facet.name,
            condition,
        )
    if field == "shelf":
        shelf_link = aliased(ShelfBook)
        shelf = aliased(Shelf)
        clauses = [
            shelf_link.book_id == LibraryBook.id,
            shelf.kind == "STATIC",
        ]
        if shelf_owner_user_id:
            clauses.append(shelf.owner_user_id == shelf_owner_user_id)
        return _relation_text(
            select(shelf_link.book_id)
            .join(shelf, shelf.id == shelf_link.shelf_id)
            .where(*clauses),
            shelf.id,
            condition,
        )
    if field == "library":
        expression = LibraryBook.library_id
        return _text(expression, condition)
    if field == "sourcePath":
        asset = aliased(LibraryResourceAsset)
        source_node = aliased(LibrarySourceNode)
        return _relation_text(
            select(asset.id)
            .join(resource, resource.id == asset.resource_id)
            .join(source_node, source_node.id == asset.source_node_id)
            .where(visible, asset.import_state == "READY"),
            source_node.relative_path,
            condition,
        )

    scalar = {
        "fileSize": (
            select(func.sum(source_node.observed_size_bytes))
            .select_from(LibraryResourceAsset)
            .join(resource, resource.id == LibraryResourceAsset.resource_id)
            .join(source_node, source_node.id == LibraryResourceAsset.source_node_id)
            .where(visible, LibraryResourceAsset.import_state == "READY")
            .scalar_subquery()
        ),
        "pageCount": select(func.max(resource_metadata.page_count))
        .where(resource_base.exists())
        .scalar_subquery(),
        "chapterCount": select(func.max(resource_metadata.chapter_count))
        .where(resource_base.exists())
        .scalar_subquery(),
        "duration": select(func.max(resource_metadata.duration_ms))
        .where(resource_base.exists())
        .scalar_subquery(),
        "resourceCount": select(func.count(resource.id))
        .where(visible)
        .scalar_subquery(),
    }
    if field in scalar:
        return _number(
            scalar[field],
            condition,
            scale=1048576
            if field == "fileSize"
            else 60000
            if field == "duration"
            else 1,
        )
    if field in {"progress", "lastReadAt"}:
        progress = aliased(ReaderResourceProgress)
        statement = (
            select(progress)
            .join(resource, resource.id == progress.resource_id)
            .where(visible)
        )
        if user_id:
            statement = statement.where(progress.user_id == user_id)
        if field == "progress":
            value = (
                statement.with_only_columns(progress.percent)
                .order_by(progress.updated_at.desc())
                .limit(1)
                .scalar_subquery()
            )
            return _number(value, condition)
        value = statement.with_only_columns(
            func.max(progress.updated_at)
        ).scalar_subquery()
        return _date(value, condition)
    if field == "organizeStatus":
        job = aliased(OrganizeJob)
        return _relation_text(
            select(job.book_id).where(job.book_id == LibraryBook.id),
            job.status,
            condition,
        )
    if field == "organized":
        organized_value = ~exists(
            select(OrganizeJob.id).where(
                OrganizeJob.book_id == LibraryBook.id, OrganizeJob.status != "COMPLETED"
            )
        )
        return (
            organized_value
            if condition.operator == "is_true"
            else not_(organized_value)
        )
    if field == "hasCover":
        cover_value = and_(
            LibraryBookMetadata.cover_path.is_not(None),
            LibraryBookMetadata.cover_status == "READY",
        )
        return cover_value if condition.operator == "is_true" else not_(cover_value)
    raise ValueError(f"Unsupported filter field: {field}")


def compile_filter_expression(
    expression: FilterExpression,
    *,
    context: AuthorizationContext,
    user_id: str | None = None,
    shelf_owner_user_id: str | None = None,
    library_roots: Mapping[str, str] | None = None,
) -> ColumnElement[bool] | None:
    predicates = [
        _condition(
            condition,
            context=context,
            user_id=user_id,
            shelf_owner_user_id=shelf_owner_user_id,
            library_roots=library_roots or {},
        )
        for condition in expression.conditions
    ]
    if not predicates:
        return None
    return and_(*predicates) if expression.combinator == "ALL" else or_(*predicates)
