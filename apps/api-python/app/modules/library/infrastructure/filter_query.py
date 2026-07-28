from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    ColumnElement,
    Float,
    and_,
    case,
    cast,
    exists,
    false,
    func,
    not_,
    or_,
    select,
    true,
)
from sqlalchemy.orm import aliased

from app.core.authorization import AuthorizationContext, edition_visibility_predicate
from app.models.library import (
    LibraryConsumptionState,
    LibraryEdition,
    LibraryFacet,
    LibraryFile,
    LibraryReadingProgress,
    LibraryWork,
    LibraryWorkFacet,
)
from app.models.shelf import Shelf, ShelfWork
from app.modules.library.application.filter_ast import (
    FilterCondition,
    FilterExpression,
)

WORK_TEXT_FIELDS = {
    "title": LibraryWork.title,
    "author": LibraryWork.author,
    "description": LibraryWork.description,
    "series": LibraryWork.series_name,
    "publicationStatus": LibraryWork.publication_status,
    "trackingStatus": LibraryWork.tracking_status,
    "organizeStatus": LibraryWork.organize_status,
    "origin": LibraryWork.origin,
}
WORK_NUMBER_FIELDS = {
    "publishedYear": LibraryWork.published_year,
    "seriesIndex": LibraryWork.series_index,
    "metadataQuality": LibraryWork.metadata_quality,
}
WORK_DATE_FIELDS = {
    "createdAt": LibraryWork.created_at,
    "updatedAt": LibraryWork.updated_at,
}
EDITION_TEXT_FIELDS = {
    "publisher": "publisher",
    "language": "language",
    "isbn": "isbn",
    "identifier": "identifier",
    "editionName": "version_name",
    "narrator": "narrator",
    "mediaKind": "media_kind",
    "format": "format",
    "importStatus": "import_status",
}


def inferred_media_kind(edition: type[LibraryEdition] = LibraryEdition) -> ColumnElement[str]:
    return func.coalesce(
        func.nullif(func.trim(edition.media_kind), ""),
        case(
            (func.upper(edition.format) == "COMIC", "COMIC"),
            (func.upper(edition.format) == "AUDIO", "AUDIOBOOK"),
            else_="EBOOK",
        ),
    )


def _normalized_text(expression: ColumnElement[object]) -> ColumnElement[str]:
    return func.lower(func.trim(func.coalesce(expression, "")))


def _text_predicate(
    expression: ColumnElement[object],
    condition: FilterCondition,
) -> ColumnElement[bool]:
    normalized = _normalized_text(expression)
    operator = condition.operator
    if operator == "is_empty":
        return normalized == ""
    if operator == "is_not_empty":
        return normalized != ""
    value = str(condition.value or "").casefold()
    if operator in {"contains", "not_contains"}:
        predicate = normalized.like(f"%{value}%")
        return not_(predicate) if operator == "not_contains" else predicate
    if operator == "starts_with":
        return normalized.like(f"{value}%")
    if operator == "ends_with":
        return normalized.like(f"%{value}")
    predicate = normalized == value
    return not_(predicate) if operator == "not_equals" else predicate


def _number_predicate(
    expression: ColumnElement[object],
    condition: FilterCondition,
    *,
    scale: float = 1,
) -> ColumnElement[bool]:
    operator = condition.operator
    if operator == "is_empty":
        return expression.is_(None)
    if operator == "is_not_empty":
        return expression.is_not(None)
    numeric = cast(expression, Float)
    if operator == "between":
        assert isinstance(condition.value, tuple)
        return numeric.between(
            float(condition.value[0]) * scale,
            float(condition.value[1]) * scale,
        )
    value = float(str(condition.value)) * scale
    comparisons = {
        "equals": numeric == value,
        "not_equals": numeric != value,
        "greater_than": numeric > value,
        "greater_or_equal": numeric >= value,
        "less_than": numeric < value,
        "less_or_equal": numeric <= value,
    }
    return comparisons[operator]


def _day_bounds(raw: str) -> tuple[datetime, datetime]:
    day = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _date_predicate(
    expression: ColumnElement[object],
    condition: FilterCondition,
) -> ColumnElement[bool]:
    operator = condition.operator
    if operator == "is_empty":
        return expression.is_(None)
    if operator == "is_not_empty":
        return expression.is_not(None)
    if operator == "between":
        assert isinstance(condition.value, tuple)
        start, _ = _day_bounds(condition.value[0])
        _, end = _day_bounds(condition.value[1])
        return and_(expression >= start, expression < end)
    start, end = _day_bounds(str(condition.value))
    if operator == "equals":
        return and_(expression >= start, expression < end)
    if operator == "not_equals":
        return not_(and_(expression >= start, expression < end))
    if operator == "after":
        return expression >= end
    if operator == "on_or_after":
        return expression >= start
    if operator == "before":
        return expression < start
    return expression < end


def _relation_text_predicate(
    relation_statement,
    expression: ColumnElement[object],
    condition: FilterCondition,
) -> ColumnElement[bool]:
    negative = condition.operator in {"not_contains", "not_equals", "is_empty"}
    positive_operator = {
        "not_contains": "contains",
        "not_equals": "equals",
        "is_empty": "is_not_empty",
    }.get(condition.operator, condition.operator)
    positive = FilterCondition(
        field=condition.field,
        operator=positive_operator,
        value=condition.value,
    )
    predicate = exists(relation_statement.where(_text_predicate(expression, positive)))
    return not_(predicate) if negative else predicate


def _visible_edition_base(
    context: AuthorizationContext,
    edition,
):
    return select(edition.id).where(
        edition.work_id == LibraryWork.id,
        edition.hidden.is_(False),
        edition_visibility_predicate(context, edition),
    )


def _reading_status_predicate(
    context: AuthorizationContext,
    user_id: str,
    condition: FilterCondition,
) -> ColumnElement[bool]:
    if condition.operator == "is_empty":
        return false()
    if condition.operator == "is_not_empty":
        return true()
    edition = aliased(LibraryEdition)
    state = aliased(LibraryConsumptionState)
    visible_edition = and_(
        edition.work_id == LibraryWork.id,
        edition.hidden.is_(False),
        edition_visibility_predicate(context, edition),
    )
    has_started = exists(
        select(state.id)
        .join(
            edition,
            and_(
                edition.work_id == state.work_id,
                inferred_media_kind(edition) == state.media_kind,
            ),
        )
        .where(
            state.user_id == user_id,
            state.work_id == LibraryWork.id,
            state.status.in_(("READING", "FINISHED")),
            visible_edition,
        )
        .correlate(LibraryWork)
    )
    has_visible = exists(
        select(edition.id).where(visible_edition).correlate(LibraryWork)
    )
    unfinished_visible = exists(
        select(edition.id).where(
            visible_edition,
            ~exists(
                select(state.id).where(
                    state.user_id == user_id,
                    state.work_id == LibraryWork.id,
                    state.media_kind == inferred_media_kind(edition),
                    state.status == "FINISHED",
                ).correlate(edition, LibraryWork)
            ),
        ).correlate(LibraryWork)
    )
    status = str(condition.value or "UNREAD").upper()
    if status == "FINISHED":
        predicate = and_(has_visible, ~unfinished_visible)
    elif status == "READING":
        predicate = and_(has_started, unfinished_visible)
    else:
        predicate = ~has_started
    return not_(predicate) if condition.operator == "not_equals" else predicate


def _condition_predicate(
    condition: FilterCondition,
    *,
    context: AuthorizationContext,
    user_id: str | None,
    shelf_owner_user_id: str | None,
) -> ColumnElement[bool]:
    field = condition.field
    if field == "readingStatus" and user_id:
        return _reading_status_predicate(context, user_id, condition)
    if field == "readingStatus":
        status_expression = case(
            (LibraryWork.status == "WANT", "UNREAD"),
            else_=LibraryWork.status,
        )
        return _text_predicate(status_expression, condition)
    if field in WORK_TEXT_FIELDS:
        return _text_predicate(WORK_TEXT_FIELDS[field], condition)
    if field in WORK_NUMBER_FIELDS:
        return _number_predicate(WORK_NUMBER_FIELDS[field], condition)
    if field in WORK_DATE_FIELDS:
        return _date_predicate(WORK_DATE_FIELDS[field], condition)
    if field in EDITION_TEXT_FIELDS:
        edition = aliased(LibraryEdition)
        expression = (
            inferred_media_kind(edition)
            if field == "mediaKind"
            else getattr(edition, EDITION_TEXT_FIELDS[field])
        )
        return _relation_text_predicate(
            _visible_edition_base(context, edition),
            expression,
            condition,
        )
    if field == "tag":
        link = aliased(LibraryWorkFacet)
        facet = aliased(LibraryFacet)
        statement = (
            select(link.work_id)
            .join(facet, facet.id == link.facet_id)
            .where(link.work_id == LibraryWork.id, facet.kind == "TAG")
        )
        return _relation_text_predicate(statement, facet.name, condition)
    if field == "shelf":
        shelf_work = aliased(ShelfWork)
        shelf = aliased(Shelf)
        clauses = [
            shelf_work.work_id == LibraryWork.id,
            shelf.kind == "STATIC",
        ]
        if shelf_owner_user_id:
            clauses.append(shelf.owner_user_id == shelf_owner_user_id)
        statement = (
            select(shelf_work.work_id)
            .join(shelf, shelf.id == shelf_work.shelf_id)
            .where(*clauses)
        )
        return _relation_text_predicate(statement, shelf.id, condition)
    if field == "monitorFolder":
        edition = aliased(LibraryEdition)
        visible_base = _visible_edition_base(context, edition)
        if condition.operator == "is_empty":
            return and_(
                LibraryWork.monitor_folder_id.is_(None),
                ~exists(visible_base.where(edition.monitor_folder_id.is_not(None))),
            )
        if condition.operator == "is_not_empty":
            return or_(
                LibraryWork.monitor_folder_id.is_not(None),
                exists(visible_base.where(edition.monitor_folder_id.is_not(None))),
            )
        value = str(condition.value or "")
        positive = or_(
            LibraryWork.monitor_folder_id == value,
            exists(visible_base.where(edition.monitor_folder_id == value)),
        )
        return not_(positive) if condition.operator == "not_equals" else positive
    if field == "sourcePath":
        edition = aliased(LibraryEdition)
        library_file = aliased(LibraryFile)
        statement = (
            _visible_edition_base(context, edition)
            .join(library_file, library_file.edition_id == edition.id)
        )
        return _relation_text_predicate(statement, library_file.path, condition)

    edition = aliased(LibraryEdition)
    visible_edition = and_(
        edition.work_id == LibraryWork.id,
        edition.hidden.is_(False),
        edition_visibility_predicate(context, edition),
    )
    scalar_expressions = {
        "fileSize": (
            select(func.sum(LibraryFile.size_bytes))
            .join(edition, edition.id == LibraryFile.edition_id)
            .where(visible_edition)
            .scalar_subquery()
        ),
        "pageCount": select(func.max(edition.page_count))
        .where(visible_edition)
        .scalar_subquery(),
        "chapterCount": select(func.max(edition.chapter_count))
        .where(visible_edition)
        .scalar_subquery(),
        "duration": select(func.max(edition.duration_ms))
        .where(visible_edition)
        .scalar_subquery(),
        "versionCount": select(func.count(edition.id))
        .where(visible_edition)
        .scalar_subquery(),
    }
    if field in scalar_expressions:
        scale = 1048576 if field == "fileSize" else 60000 if field == "duration" else 1
        return _number_predicate(scalar_expressions[field], condition, scale=scale)
    if field in {"progress", "lastReadAt"}:
        progress = aliased(LibraryReadingProgress)
        progress_filters = [progress.work_id == LibraryWork.id]
        if user_id:
            progress_filters.append(progress.user_id == user_id)
        if field == "progress":
            expression = (
                select(progress.percent)
                .where(*progress_filters)
                .order_by(progress.updated_at.desc(), progress.id.desc())
                .limit(1)
                .scalar_subquery()
            )
            return _number_predicate(expression, condition)
        expression = (
            select(func.max(progress.updated_at))
            .where(*progress_filters)
            .scalar_subquery()
        )
        return _date_predicate(expression, condition)
    if field == "organized":
        predicate = LibraryWork.organized.is_(True)
        return predicate if condition.operator == "is_true" else not_(predicate)
    if field == "hasCover":
        predicate = and_(
            func.trim(func.coalesce(LibraryWork.cover_path, "")) != "",
            LibraryWork.cover_status == "READY",
        )
        return predicate if condition.operator == "is_true" else not_(predicate)
    raise ValueError(f"Unsupported filter field: {field}")


def compile_filter_expression(
    expression: FilterExpression,
    *,
    context: AuthorizationContext,
    user_id: str | None = None,
    shelf_owner_user_id: str | None = None,
) -> ColumnElement[bool] | None:
    predicates = [
        _condition_predicate(
            condition,
            context=context,
            user_id=user_id,
            shelf_owner_user_id=shelf_owner_user_id,
        )
        for condition in expression.conditions
    ]
    if not predicates:
        return None
    return and_(*predicates) if expression.combinator == "ALL" else or_(*predicates)
