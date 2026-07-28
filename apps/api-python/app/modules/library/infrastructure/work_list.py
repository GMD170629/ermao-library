"""ORM-backed library work listing for compat list_works."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    ColumnElement,
    and_,
    case,
    exists,
    func,
    inspect as sa_inspect,
    or_,
    select,
)
from sqlalchemy.orm import Session, aliased

from app.core.authorization import (
    AuthorizationContext,
    authorization_context,
    edition_visibility_predicate,
    work_visibility_predicate,
)
from app.models.auth import User
from app.models.library import (
    LibraryEdition,
    LibraryFile,
    LibraryReadingProgress,
    LibraryWork,
)
from app.modules.library.application.filter_ast import (
    FilterCondition,
    FilterExpression,
    InvalidFilterExpression,
    parse_filter_expression,
)
from app.modules.library.application.work_list import WorkListQuery, WorkListResult
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    inferred_media_kind,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict
from app.services.library_filters import compile_filter_predicate, normalize_filter_rules


def _has_table(db: Session, table: str) -> bool:
    try:
        return sa_inspect(db.connection()).has_table(table)
    except Exception:
        return False


def _has_column(db: Session, table: str, column: str) -> bool:
    try:
        return any(
            item.get("name") == column
            for item in sa_inspect(db.connection()).get_columns(table)
        )
    except Exception:
        return False


def _edition_visible(
    context: AuthorizationContext,
    edition: type[LibraryEdition] = LibraryEdition,
) -> ColumnElement[bool]:
    return and_(
        edition.work_id == LibraryWork.id,
        edition.hidden.is_(False),
        edition_visibility_predicate(context, edition),
    )


def _edition_exists(
    context: AuthorizationContext,
    *extra: ColumnElement[bool],
    edition: type[LibraryEdition] = LibraryEdition,
) -> ColumnElement[bool]:
    return exists(select(edition.id).where(_edition_visible(context, edition), *extra))


def _status_predicate(
    db: Session,
    context: AuthorizationContext,
    user_id: str,
    status: str,
) -> ColumnElement[bool] | None:
    normalized = status.upper()
    if normalized not in {"UNREAD", "READING", "FINISHED"}:
        return None
    if not (
        _has_table(db, "LibraryConsumptionState")
        and _has_table(db, "LibraryEdition")
    ):
        if normalized == "UNREAD":
            return LibraryWork.status.in_(("UNREAD", "WANT"))
        return LibraryWork.status == normalized
    expression = FilterExpression(
        combinator="ALL",
        conditions=(
            FilterCondition(
                field="readingStatus",
                operator="equals",
                value=normalized,
            ),
        ),
    )
    return compile_filter_expression(
        expression,
        context=context,
        user_id=user_id,
    )


def _type_filter_predicate(
    db: Session,
    context: AuthorizationContext,
    type_filter: str,
) -> ColumnElement[bool] | None:
    normalized = type_filter.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    upper = normalized.upper()
    has_edition_table = _has_table(db, "LibraryEdition")
    has_media_kind = has_edition_table and _has_column(db, "LibraryEdition", "mediaKind")
    edition = aliased(LibraryEdition)

    if lowered == "ebook":
        if has_media_kind:
            return _edition_exists(
                context,
                inferred_media_kind(edition) == "EBOOK",
                edition=edition,
            )
        return _edition_exists(
            context,
            edition.format.in_(("EPUB", "PDF", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT")),
            edition=edition,
        )
    if lowered in {"audio", "audiobook"}:
        if has_media_kind:
            return _edition_exists(
                context,
                inferred_media_kind(edition) == "AUDIOBOOK",
                edition=edition,
            )
        return _edition_exists(context, edition.format == "AUDIO", edition=edition)
    if upper == "COMIC":
        if has_edition_table:
            if has_media_kind:
                return _edition_exists(
                    context,
                    inferred_media_kind(edition) == "COMIC",
                    edition=edition,
                )
            return _edition_exists(context, edition.format == "COMIC", edition=edition)
        return LibraryWork.work_type == "COMIC"
    if upper in {"EPUB", "PDF"} and has_edition_table:
        return _edition_exists(context, edition.format == upper, edition=edition)
    if upper in {"COMIC", "EPUB", "PDF"}:
        return LibraryWork.work_type == upper
    if upper in {"CBZ", "ZIP"} and _has_table(db, "LibraryFile"):
        library_file = aliased(LibraryFile)
        return exists(
            select(edition.id)
            .join(library_file, library_file.edition_id == edition.id)
            .where(
                _edition_visible(context, edition),
                func.lower(library_file.path).like(f"%.{lowered}"),
            )
        )
    return None


def _media_kinds_predicate(
    db: Session,
    context: AuthorizationContext,
    media_kinds: tuple[str, ...],
) -> ColumnElement[bool] | None:
    if not media_kinds or not _has_table(db, "LibraryEdition"):
        return None
    edition = aliased(LibraryEdition)
    if _has_column(db, "LibraryEdition", "mediaKind"):
        kind_expression: ColumnElement[str] = inferred_media_kind(edition)
    else:
        kind_expression = case(
            (edition.format == "COMIC", "COMIC"),
            (edition.format == "AUDIO", "AUDIOBOOK"),
            else_="EBOOK",
        )
    return _edition_exists(
        context,
        kind_expression.in_(media_kinds),
        edition=edition,
    )


def _build_predicates(
    db: Session,
    context: AuthorizationContext,
    user: User,
    query: WorkListQuery,
) -> tuple[list[ColumnElement[bool]], str | None]:
    predicates: list[ColumnElement[bool]] = [work_visibility_predicate(context)]
    if query.visibility == "ignored":
        predicates.append(LibraryWork.hidden.is_(True))
    elif query.visibility != "all":
        predicates.append(LibraryWork.hidden.is_(False))

    term = (query.search or query.keyword or "").strip()
    if term:
        pattern = f"%{term.casefold()}%"
        search_predicates = [
            func.lower(LibraryWork.title).like(pattern),
            func.lower(func.coalesce(LibraryWork.author, "")).like(pattern),
            func.lower(LibraryWork.tags).like(pattern),
        ]
        if _has_column(db, "LibraryWork", "seriesName"):
            search_predicates.append(
                func.lower(func.coalesce(LibraryWork.series_name, "")).like(pattern)
            )
        predicates.append(or_(*search_predicates))

    type_predicate = _type_filter_predicate(db, context, query.type_filter)
    if type_predicate is not None:
        predicates.append(type_predicate)

    media_predicate = _media_kinds_predicate(db, context, query.media_kinds)
    if media_predicate is not None:
        predicates.append(media_predicate)

    if query.status:
        status_predicate = _status_predicate(db, context, user.id, query.status)
        if status_predicate is not None:
            predicates.append(status_predicate)

    if query.publication_status in {
        "UNKNOWN",
        "ONGOING",
        "COMPLETED",
        "HIATUS",
        "CANCELLED",
    }:
        predicates.append(LibraryWork.publication_status == query.publication_status)

    if query.tracking_status in {"NOT_TRACKING", "TRACKING", "PAUSED", "IGNORED"}:
        predicates.append(LibraryWork.tracking_status == query.tracking_status)

    if query.tag:
        predicates.append(LibraryWork.tags.like(f"%{query.tag}%"))

    if query.missing_cover and _has_column(db, "LibraryWork", "coverPath"):
        predicates.append(
            or_(
                LibraryWork.cover_path.is_(None),
                func.trim(func.coalesce(LibraryWork.cover_path, "")) == "",
                LibraryWork.cover_status != "READY",
            )
        )

    if query.new_import:
        predicates.append(LibraryWork.organize_status.in_(("PENDING", "REVIEWING")))

    series_name = (query.series_name or "").strip()
    if series_name and _has_column(db, "LibraryWork", "seriesName"):
        predicates.append(func.trim(LibraryWork.series_name) == series_name)

    if query.filter_rules:
        filter_predicate, filter_error = compile_filter_predicate(
            db,
            query.filter_rules,
            user_id=user.id,
            shelf_owner_user_id=user.id
            if _has_column(db, "Shelf", "ownerUserId")
            else None,
        )
        if filter_error:
            return predicates, filter_error
        if filter_predicate is not None:
            predicates.append(filter_predicate)

    return predicates, None


def _sort_direction(query: WorkListQuery) -> str:
    default = "DESC" if query.sort in {"updated", "recent_read", "recent_import", "progress"} else "ASC"
    if query.sort_direction and query.sort_direction.lower() in {"asc", "desc"}:
        return query.sort_direction.upper()
    return default


def _primary_publisher_subquery(
    context: AuthorizationContext,
) -> ColumnElement[Any]:
    edition_sort = aliased(LibraryEdition)
    return (
        select(edition_sort.publisher)
        .where(
            edition_sort.work_id == LibraryWork.id,
            edition_sort.hidden.is_(False),
            edition_visibility_predicate(context, edition_sort),
        )
        .order_by(
            func.coalesce(edition_sort.is_primary, 0).desc(),
            edition_sort.created_at.asc(),
            edition_sort.id.asc(),
        )
        .limit(1)
        .scalar_subquery()
    )


def _order_by_clauses(
    db: Session,
    context: AuthorizationContext,
    query: WorkListQuery,
    direction: str,
) -> list[ColumnElement[Any]]:
    descending = direction == "DESC"
    title_order = (
        LibraryWork.title.desc() if descending else LibraryWork.title.asc()
    )
    updated_order = (
        LibraryWork.updated_at.desc() if descending else LibraryWork.updated_at.asc()
    )

    if query.sort == "series_index" and _has_column(db, "LibraryWork", "seriesIndex"):
        index_order = (
            LibraryWork.series_index.desc()
            if descending
            else LibraryWork.series_index.asc()
        )
        return [
            case((LibraryWork.series_index.is_(None), 1), else_=0),
            index_order,
            LibraryWork.title.asc(),
            LibraryWork.id.asc(),
        ]
    if query.sort == "title":
        return [title_order, LibraryWork.id.asc()]
    if query.sort == "author":
        return [
            case(
                (
                    func.nullif(func.trim(func.coalesce(LibraryWork.author, "")), "").is_(
                        None
                    ),
                    1,
                ),
                else_=0,
            ),
            LibraryWork.author.desc() if descending else LibraryWork.author.asc(),
            LibraryWork.title.asc(),
            LibraryWork.id.asc(),
        ]
    if (
        query.sort == "publisher"
        and _has_table(db, "LibraryEdition")
        and _has_column(db, "LibraryEdition", "publisher")
    ):
        publisher = _primary_publisher_subquery(context)
        return [
            case(
                (
                    func.nullif(func.trim(func.coalesce(publisher, "")), "").is_(None),
                    1,
                ),
                else_=0,
            ),
            publisher.desc() if descending else publisher.asc(),
            LibraryWork.title.asc(),
            LibraryWork.id.asc(),
        ]
    if query.sort == "series" and _has_column(db, "LibraryWork", "seriesName"):
        return [
            case(
                (
                    func.nullif(func.trim(func.coalesce(LibraryWork.series_name, "")), "").is_(
                        None
                    ),
                    1,
                ),
                else_=0,
            ),
            LibraryWork.series_name.desc()
            if descending
            else LibraryWork.series_name.asc(),
            case((LibraryWork.series_index.is_(None), 1), else_=0),
            LibraryWork.series_index.asc(),
            LibraryWork.title.asc(),
            LibraryWork.id.asc(),
        ]
    if query.sort == "recent_import":
        return [LibraryWork.created_at.desc() if descending else LibraryWork.created_at.asc(), LibraryWork.id.desc() if descending else LibraryWork.id.asc()]
    return [updated_order, LibraryWork.id.desc() if descending else LibraryWork.id.asc()]


def _recent_read_statement(
    db: Session,
    predicates: list[ColumnElement[bool]],
    user_id: str,
    direction: str,
    *,
    limit: int,
    offset: int,
) -> Any:
    progress = aliased(LibraryReadingProgress)
    ranked = (
        select(
            progress.work_id.label("work_id"),
            progress.updated_at.label("latest_read_at"),
            func.row_number()
            .over(
                partition_by=progress.work_id,
                order_by=(progress.updated_at.desc(), progress.id.desc()),
            )
            .label("row_number"),
        )
        .where(progress.user_id == user_id)
        .subquery("ranked_progress")
    )
    recent_progress = (
        select(
            ranked.c.work_id,
            ranked.c.latest_read_at,
        )
        .where(ranked.c.row_number == 1)
        .subquery("recent_progress")
    )
    descending = direction == "DESC"
    latest_order = (
        recent_progress.c.latest_read_at.desc()
        if descending
        else recent_progress.c.latest_read_at.asc()
    )
    updated_order = (
        LibraryWork.updated_at.desc() if descending else LibraryWork.updated_at.asc()
    )
    return (
        select(LibraryWork)
        .outerjoin(
            recent_progress,
            recent_progress.c.work_id == LibraryWork.id,
        )
        .where(and_(*predicates))
        .order_by(
            case((recent_progress.c.latest_read_at.is_(None), 1), else_=0),
            latest_order,
            updated_order,
            LibraryWork.id.desc() if descending else LibraryWork.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )


def list_works(
    db: Session,
    user: User,
    query: WorkListQuery,
) -> WorkListResult:
    page = max(1, query.page)
    page_size = min(100, max(1, query.page_size))
    if not _has_table(db, "LibraryWork"):
        return WorkListResult(works=[], total=0, page=page, page_size=page_size)

    context = authorization_context(db, user)
    predicates, filter_error = _build_predicates(db, context, user, query)
    if filter_error:
        raise ValueError(filter_error)

    total = int(
        db.scalar(select(func.count()).select_from(LibraryWork).where(and_(*predicates)))
        or 0
    )
    direction = _sort_direction(query)

    if (
        query.sort == "progress"
        and _has_table(db, "LibraryReadingProgress")
    ):
        rows = db.scalars(
            select(LibraryWork).where(and_(*predicates))
        ).all()
        return WorkListResult(
            works=[entity_as_legacy_dict(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
            progress_sort=True,
        )

    if (
        query.sort == "recent_read"
        and _has_table(db, "LibraryReadingProgress")
    ):
        statement = _recent_read_statement(
            db,
            predicates,
            user.id,
            direction,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    else:
        statement = (
            select(LibraryWork)
            .where(and_(*predicates))
            .order_by(*_order_by_clauses(db, context, query, direction))
            .limit(page_size)
            .offset((page - 1) * page_size)
        )

    rows = db.scalars(statement).all()
    return WorkListResult(
        works=[entity_as_legacy_dict(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
