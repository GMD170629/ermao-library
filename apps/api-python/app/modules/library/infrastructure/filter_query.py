"""Compile validated library filters against volume-owned resource fields."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
from sqlalchemy.orm import aliased

from app.core.authorization import AuthorizationContext, volume_visibility_predicate
from app.models.library import (
    LibraryFacet,
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    LibraryWorkFacet,
)
from app.models.shelf import Shelf, ShelfWork
from app.modules.library.application.filter_ast import FilterCondition, FilterExpression
from app.modules.library.domain.authors import UNKNOWN_AUTHOR_PLACEHOLDER

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
    "seriesIndex": LibraryWork.series_index,
    "metadataQuality": LibraryWork.metadata_quality,
}
WORK_DATE_FIELDS = {
    "createdAt": LibraryWork.created_at,
    "updatedAt": LibraryWork.updated_at,
}
VOLUME_TEXT_FIELDS = {
    "volumeTitle": "title",
    "narrator": "narrator",
    "format": "format",
    "importStatus": "import_status",
}


def _normalized_text(expression: ColumnElement[object]) -> ColumnElement[str]:
    return func.lower(func.trim(func.coalesce(expression, "")))


def _literal_like_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _text(
    expression: ColumnElement[object],
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
        result = normalized.like(f"%{value}%", escape="\\")
        return not_(result) if condition.operator == "not_contains" else result
    if condition.operator == "starts_with":
        return normalized.like(f"{value}%", escape="\\")
    if condition.operator == "ends_with":
        return normalized.like(f"%{value}", escape="\\")
    result = normalized == value
    return not_(result) if condition.operator == "not_equals" else result


def _number(
    expression: ColumnElement[object], condition: FilterCondition, *, scale: float = 1
) -> ColumnElement[bool]:
    if condition.operator == "is_empty":
        return expression.is_(None)
    if condition.operator == "is_not_empty":
        return expression.is_not(None)
    numeric = cast(expression, Float)
    if condition.operator == "between":
        assert isinstance(condition.value, tuple)
        return numeric.between(
            float(condition.value[0]) * scale,
            float(condition.value[1]) * scale,
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


def _date(
    expression: ColumnElement[object], condition: FilterCondition
) -> ColumnElement[bool]:
    if condition.operator == "is_empty":
        return expression.is_(None)
    if condition.operator == "is_not_empty":
        return expression.is_not(None)
    if condition.operator == "between":
        assert isinstance(condition.value, tuple)
        start = datetime.fromisoformat(condition.value[0]).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(condition.value[1]).replace(
            tzinfo=timezone.utc
        ) + timedelta(days=1)
        return and_(expression >= start, expression < end)
    start = datetime.fromisoformat(str(condition.value)).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    if condition.operator == "equals":
        return and_(expression >= start, expression < end)
    if condition.operator == "not_equals":
        return not_(and_(expression >= start, expression < end))
    if condition.operator == "after":
        return expression >= end
    if condition.operator == "on_or_after":
        return expression >= start
    if condition.operator == "before":
        return expression < start
    return expression < end


def _visible_volume(
    context: AuthorizationContext,
    volume: type[LibraryVolume],
    media_version: type[LibraryMediaVersion],
) -> ColumnElement[bool]:
    return and_(
        media_version.work_id == LibraryWork.id,
        volume.media_version_id == media_version.id,
        volume.hidden.is_(False),
        volume_visibility_predicate(context, volume),
    )


def _relation_text(
    statement: object,
    expression: ColumnElement[object],
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


def _reading_status(
    context: AuthorizationContext, user_id: str, condition: FilterCondition
) -> ColumnElement[bool]:
    volume = aliased(LibraryVolume)
    media_version = aliased(LibraryMediaVersion)
    progress = aliased(LibraryReadingProgress)
    visible = _visible_volume(context, volume, media_version)
    has_volume = exists(select(volume.id).where(visible))
    if condition.operator == "is_empty":
        return ~has_volume
    if condition.operator == "is_not_empty":
        return has_volume
    started = exists(
        select(progress.id)
        .join(volume, volume.id == progress.volume_id)
        .join(media_version, media_version.id == volume.media_version_id)
        .where(visible, progress.user_id == user_id, progress.percent > 0)
    )
    unfinished = exists(
        select(volume.id)
        .join(media_version, media_version.id == volume.media_version_id)
        .outerjoin(
            progress,
            and_(progress.volume_id == volume.id, progress.user_id == user_id),
        )
        .where(visible, func.coalesce(progress.percent, 0) < 100)
    )
    status = str(condition.value or "UNREAD").upper()
    predicate = (
        and_(has_volume, ~unfinished)
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
) -> ColumnElement[bool]:
    field = condition.field
    if field == "readingStatus" and user_id:
        return _reading_status(context, user_id, condition)
    if field == "author":
        return _text(
            LibraryWork.author,
            condition,
            empty_values=(UNKNOWN_AUTHOR_PLACEHOLDER,),
        )
    if field in WORK_TEXT_FIELDS:
        return _text(WORK_TEXT_FIELDS[field], condition)
    if field in WORK_NUMBER_FIELDS:
        return _number(WORK_NUMBER_FIELDS[field], condition)
    if field in WORK_DATE_FIELDS:
        return _date(WORK_DATE_FIELDS[field], condition)
    volume = aliased(LibraryVolume)
    media_version = aliased(LibraryMediaVersion)
    visible = _visible_volume(context, volume, media_version)
    if field in VOLUME_TEXT_FIELDS or field == "mediaKind":
        expression = (
            media_version.media_kind
            if field == "mediaKind"
            else getattr(volume, VOLUME_TEXT_FIELDS[field])
        )
        return _relation_text(
            select(volume.id)
            .join(media_version, media_version.id == volume.media_version_id)
            .where(visible),
            expression,
            condition,
        )
    if field == "tag":
        link = aliased(LibraryWorkFacet)
        facet = aliased(LibraryFacet)
        return _relation_text(
            select(link.work_id)
            .join(facet, facet.id == link.facet_id)
            .where(link.work_id == LibraryWork.id, facet.kind == "TAG"),
            facet.name,
            condition,
        )
    if field == "shelf":
        link = aliased(ShelfWork)
        shelf = aliased(Shelf)
        clauses = [link.work_id == LibraryWork.id, shelf.kind == "STATIC"]
        if shelf_owner_user_id:
            clauses.append(shelf.owner_user_id == shelf_owner_user_id)
        return _relation_text(
            select(link.work_id).join(shelf, shelf.id == link.shelf_id).where(*clauses),
            shelf.id,
            condition,
        )
    if field == "monitorFolder":
        return _relation_text(
            select(volume.id)
            .join(media_version, media_version.id == volume.media_version_id)
            .where(visible),
            volume.monitor_folder_id,
            condition,
        )
    if field == "sourcePath":
        file = aliased(LibraryFile)
        return _relation_text(
            select(file.id)
            .join(volume, volume.id == file.volume_id)
            .join(media_version, media_version.id == volume.media_version_id)
            .where(visible),
            file.path,
            condition,
        )
    scalar = {
        "fileSize": select(func.sum(LibraryFile.size_bytes))
        .join(volume, volume.id == LibraryFile.volume_id)
        .join(media_version, media_version.id == volume.media_version_id)
        .where(visible)
        .scalar_subquery(),
        "pageCount": select(func.max(volume.page_count))
        .where(visible)
        .scalar_subquery(),
        "chapterCount": select(func.max(volume.chapter_count))
        .where(visible)
        .scalar_subquery(),
        "duration": select(func.max(volume.duration_ms))
        .where(visible)
        .scalar_subquery(),
        "volumeCount": select(func.count(volume.id)).where(visible).scalar_subquery(),
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
        progress = aliased(LibraryReadingProgress)
        statement = (
            select(progress)
            .join(volume, volume.id == progress.volume_id)
            .join(media_version, media_version.id == volume.media_version_id)
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
    if field == "organized":
        value = LibraryWork.organized.is_(True)
        return value if condition.operator == "is_true" else not_(value)
    if field == "hasCover":
        value = and_(
            LibraryWork.cover_path.is_not(None), LibraryWork.cover_status == "READY"
        )
        return value if condition.operator == "is_true" else not_(value)
    raise ValueError(f"Unsupported filter field: {field}")


def compile_filter_expression(
    expression: FilterExpression,
    *,
    context: AuthorizationContext,
    user_id: str | None = None,
    shelf_owner_user_id: str | None = None,
) -> ColumnElement[bool] | None:
    predicates = [
        _condition(
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
