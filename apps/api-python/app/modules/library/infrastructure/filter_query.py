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
    false,
    func,
    not_,
    or_,
    select,
    true,
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
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.shelf import Shelf, ShelfBook
from app.modules.library.application.filter_ast import FilterCondition, FilterExpression
from app.modules.library.domain.authors import UNKNOWN_AUTHOR_PLACEHOLDER
from app.modules.library.infrastructure.book_covers import effective_book_cover_exists
from app.modules.reader.public import ReaderV5LibraryPresentationQueryPort

BOOK_TEXT_FIELDS = {
    "title": LibraryBookMetadata.title,
    "author": LibraryBookMetadata.author,
    "description": LibraryBookMetadata.description,
    "series": LibraryBookMetadata.series_name,
}
BOOK_NUMBER_FIELDS = {
    "seriesIndex": LibraryBookMetadata.series_index,
}
RESOURCE_TEXT_FIELDS = {
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


def reading_status_predicate(
    context: AuthorizationContext,
    user_id: str,
    status: str,
    *,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> ColumnElement[bool]:
    return typing_cast(
        ColumnElement[bool],
        reader_queries.reading_status_expression(
            context=context,
            user_id=user_id,
            book_id_expression=LibraryBook.id,
            status=status,
        ),
    )


def _reading_status(
    context: AuthorizationContext,
    user_id: str,
    condition: FilterCondition,
    *,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> ColumnElement[bool]:
    resource = aliased(LibraryReadableResource)
    has_resource = exists(
        select(resource.id).where(
            resource_visibility_predicate(context, resource),
            resource.book_id == LibraryBook.id,
        )
    )
    if condition.operator == "is_empty":
        return ~has_resource
    if condition.operator == "is_not_empty":
        return has_resource
    predicate = reading_status_predicate(
        context,
        user_id,
        str(condition.value or "UNREAD"),
        reader_queries=reader_queries,
    )
    return not_(predicate) if condition.operator == "not_equals" else predicate


def _condition(
    condition: FilterCondition,
    *,
    context: AuthorizationContext,
    user_id: str | None,
    shelf_owner_user_id: str | None,
    library_roots: Mapping[str, str],
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> ColumnElement[bool]:
    del library_roots
    field = condition.field
    if field == "readingStatus" and user_id:
        return _reading_status(
            context, user_id, condition, reader_queries=reader_queries
        )
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

    resource = aliased(LibraryReadableResource)
    source_node = aliased(LibrarySourceNode)
    visible = _visible_resource(context, resource, LibraryBook)
    resource_base = select(resource.id).where(visible)
    if field in RESOURCE_TEXT_FIELDS:
        return _relation_text(
            resource_base,
            getattr(resource, RESOURCE_TEXT_FIELDS[field]),
            condition,
        )
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
        if condition.operator == "is_empty":
            return false()
        if condition.operator == "is_not_empty":
            return true()
        library_id_value = str(condition.value or "")
        if condition.operator == "equals":
            return LibraryBook.library_id == library_id_value
        if condition.operator == "not_equals":
            return LibraryBook.library_id != library_id_value
        raise ValueError(f"Unsupported library filter operator: {condition.operator}")
    if field == "sourcePath":
        asset = aliased(LibraryResourceAsset)
        return _relation_text(
            select(asset.id)
            .join(resource, resource.id == asset.resource_id)
            .join(source_node, source_node.id == asset.source_node_id)
            .where(visible, asset.import_state == "READY"),
            source_node.relative_path,
            condition,
        )

    if field in {"progress", "lastReadAt"}:
        if field == "progress":
            value = reader_queries.progress_expression(
                context=context,
                user_id=user_id,
                book_id_expression=LibraryBook.id,
                field="display_percent",
            )
            return _number(value, condition)
        value = reader_queries.progress_expression(
            context=context,
            user_id=user_id,
            book_id_expression=LibraryBook.id,
            field="updated_at",
        )
        return _date(value, condition)
    if field == "hasCover":
        cover_value = effective_book_cover_exists(LibraryBook.id)
        return cover_value if condition.operator == "is_true" else not_(cover_value)
    raise ValueError(f"Unsupported filter field: {field}")


def compile_filter_expression(
    expression: FilterExpression,
    *,
    context: AuthorizationContext,
    user_id: str | None = None,
    shelf_owner_user_id: str | None = None,
    library_roots: Mapping[str, str] | None = None,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> ColumnElement[bool] | None:
    predicates = [
        _condition(
            condition,
            context=context,
            user_id=user_id,
            shelf_owner_user_id=shelf_owner_user_id,
            library_roots=library_roots or {},
            reader_queries=reader_queries,
        )
        for condition in expression.conditions
    ]
    if not predicates:
        return None
    return and_(*predicates) if expression.combinator == "ALL" else or_(*predicates)
