"""Volume-authorized ORM work listing."""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.authorization import (
    AuthorizationContext,
    authorization_context,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.auth import User
from app.models.library import (
    LibraryFacet,
    LibraryReadingProgress,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
    LibraryWorkFacet,
)
from app.modules.library.application.work_list import (
    WorkListQuery,
    WorkListResult,
    resolve_page_size,
)
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    resolve_library_roots,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def _visible_volume_exists(
    context: AuthorizationContext,
    *extra: ColumnElement[bool],
) -> ColumnElement[bool]:
    media_version = aliased(LibraryVersion)
    volume = aliased(LibraryVolume)
    return exists(
        select(media_version.id).where(
            media_version.work_id == LibraryWork.id,
            exists(
                select(volume.id).where(
                    volume.version_id == media_version.id,
                    volume.hidden.is_(False),
                    volume_visibility_predicate(context, volume),
                    *extra,
                )
            ),
        )
    )


def _media_kind_predicate(
    context: AuthorizationContext, media_kinds: tuple[str, ...]
) -> ColumnElement[bool] | None:
    if not media_kinds:
        return None
    media_version = aliased(LibraryVersion)
    volume = aliased(LibraryVolume)
    return exists(
        select(media_version.id).where(
            media_version.work_id == LibraryWork.id,
            media_version.source_key.in_(media_kinds),
            exists(
                select(volume.id).where(
                    volume.version_id == media_version.id,
                    volume.hidden.is_(False),
                    volume_visibility_predicate(context, volume),
                )
            ),
        )
    )


def _type_predicate(
    context: AuthorizationContext, value: str
) -> ColumnElement[bool] | None:
    normalized = value.strip().upper()
    media_map = {
        "EBOOK": "EBOOK",
        "AUDIO": "AUDIOBOOK",
        "AUDIOBOOK": "AUDIOBOOK",
        "COMIC": "COMIC",
    }
    if normalized.lower() == "ebook":
        normalized = "EBOOK"
    if normalized in media_map:
        return _media_kind_predicate(context, (media_map[normalized],))
    supported_formats = {
        "EPUB",
        "PDF",
        "MOBI",
        "AZW",
        "AZW3",
        "PRC",
        "FB2",
        "TXT",
        "CBR",
        "CBZ",
        "RAR",
        "ZIP",
        "M4B",
        "M4A",
        "MP3",
    }
    if normalized not in supported_formats:
        return None
    media_version = aliased(LibraryVersion)
    volume = aliased(LibraryVolume)
    return exists(
        select(media_version.id).where(
            media_version.work_id == LibraryWork.id,
            exists(
                select(volume.id).where(
                    volume.version_id == media_version.id,
                    volume.format == normalized,
                    volume.hidden.is_(False),
                    volume_visibility_predicate(context, volume),
                )
            ),
        )
    )


def _status_predicate(
    context: AuthorizationContext, user_id: str, status: str
) -> ColumnElement[bool] | None:
    normalized = status.strip().upper()
    if normalized == "WANT":
        normalized = "UNREAD"
    if normalized not in {"UNREAD", "READING", "FINISHED"}:
        return None
    media_version = aliased(LibraryVersion)
    volume = aliased(LibraryVolume)
    progress = aliased(LibraryReadingProgress)
    started = exists(
        select(progress.id)
        .join(volume, volume.id == progress.volume_id)
        .join(media_version, media_version.id == volume.version_id)
        .where(
            media_version.work_id == LibraryWork.id,
            progress.user_id == user_id,
            progress.percent > 0,
            volume.hidden.is_(False),
            volume_visibility_predicate(context, volume),
        )
    )
    unfinished = exists(
        select(media_version.id).where(
            media_version.work_id == LibraryWork.id,
            exists(
                select(volume.id)
                .outerjoin(
                    progress,
                    and_(
                        progress.volume_id == volume.id,
                        progress.user_id == user_id,
                    ),
                )
                .where(
                    volume.version_id == media_version.id,
                    volume.hidden.is_(False),
                    volume_visibility_predicate(context, volume),
                    func.coalesce(progress.percent, 0) < 100,
                )
            ),
        )
    )
    if normalized == "FINISHED":
        return and_(_visible_volume_exists(context), ~unfinished)
    if normalized == "READING":
        return and_(started, unfinished)
    return ~started


def _predicates(
    db: Session,
    context: AuthorizationContext,
    user: User,
    query: WorkListQuery,
) -> list[ColumnElement[bool]]:
    predicates: list[ColumnElement[bool]] = [work_visibility_predicate(context)]
    if query.visibility == "ignored":
        predicates.append(LibraryWork.hidden.is_(True))
    elif query.visibility != "all":
        predicates.append(LibraryWork.hidden.is_(False))
    term = (query.search or query.keyword or "").strip().casefold()
    if term:
        pattern = f"%{term}%"
        predicates.append(
            or_(
                func.lower(LibraryWork.title).like(pattern),
                func.lower(func.coalesce(LibraryWork.author, "")).like(pattern),
                func.lower(LibraryWork.tags).like(pattern),
                func.lower(func.coalesce(LibraryWork.series_name, "")).like(pattern),
            )
        )
    type_predicate = _type_predicate(context, query.type_filter)
    if type_predicate is not None:
        predicates.append(type_predicate)
    media_predicate = _media_kind_predicate(context, query.media_kinds)
    if media_predicate is not None:
        predicates.append(media_predicate)
    requested_statuses = (
        tuple(dict.fromkeys((*query.statuses, query.status)))
        if query.status
        else query.statuses
    )
    status_predicates = tuple(
        predicate
        for status in requested_statuses
        if (predicate := _status_predicate(context, user.id, status)) is not None
    )
    if status_predicates:
        predicates.append(or_(*status_predicates))
    if query.publication_status:
        predicates.append(LibraryWork.publication_status == query.publication_status)
    if query.tracking_status:
        predicates.append(LibraryWork.tracking_status == query.tracking_status)
    if query.tag:
        predicates.append(LibraryWork.tags.like(f"%{query.tag}%"))
    if query.missing_cover:
        predicates.append(
            or_(
                LibraryWork.cover_path.is_(None),
                func.trim(func.coalesce(LibraryWork.cover_path, "")) == "",
                LibraryWork.cover_status != "READY",
            )
        )
    if query.new_import:
        predicates.append(LibraryWork.organize_status.in_(("PENDING", "REVIEWING")))
    if query.series_name:
        predicates.append(
            func.trim(LibraryWork.series_name) == query.series_name.strip()
        )
    if query.facet_kind and query.facet_id:
        link = aliased(LibraryWorkFacet)
        facet = aliased(LibraryFacet)
        predicates.append(
            exists(
                select(link.work_id)
                .join(facet, facet.id == link.facet_id)
                .where(
                    link.work_id == LibraryWork.id,
                    link.facet_id == query.facet_id,
                    facet.kind == query.facet_kind,
                )
            )
        )
    if query.filter_expression is not None:
        library_roots = resolve_library_roots(
            db,
            query.filter_expression,
            context,
        )
        dynamic_filter = compile_filter_expression(
            query.filter_expression,
            context=context,
            user_id=user.id,
            shelf_owner_user_id=user.id,
            library_roots=library_roots,
        )
        if dynamic_filter is not None:
            predicates.append(dynamic_filter)
    return predicates


def _order(query: WorkListQuery) -> list[ColumnElement[object]]:
    descending = (query.sort_direction or "").lower() == "desc" or (
        not query.sort_direction
        and query.sort in {"updated", "recent_read", "recent_import", "progress"}
    )
    def direction(column: ColumnElement[object]) -> ColumnElement[object]:
        return column.desc() if descending else column.asc()
    if query.sort == "title":
        return [direction(LibraryWork.title), LibraryWork.id.asc()]
    if query.sort == "author":
        return [
            direction(LibraryWork.author),
            LibraryWork.title.asc(),
            LibraryWork.id.asc(),
        ]
    if query.sort == "series":
        return [
            direction(LibraryWork.series_name),
            LibraryWork.series_index.asc(),
            LibraryWork.id.asc(),
        ]
    if query.sort == "series_index":
        return [
            direction(LibraryWork.series_index),
            LibraryWork.title.asc(),
            LibraryWork.id.asc(),
        ]
    if query.sort == "recent_import":
        return [direction(LibraryWork.created_at), direction(LibraryWork.id)]
    return [direction(LibraryWork.updated_at), direction(LibraryWork.id)]


def list_works(db: Session, user: User, query: WorkListQuery) -> WorkListResult:
    context = authorization_context(db, user)
    predicates = _predicates(db, context, user, query)
    total = int(
        db.scalar(
            select(func.count()).select_from(LibraryWork).where(and_(*predicates))
        )
        or 0
    )
    page = max(1, query.page)
    page_size = resolve_page_size(query.requested_page_size, total)
    statement = select(LibraryWork).where(and_(*predicates))
    if query.sort == "recent_read":
        latest_read = (
            select(
                LibraryVersion.work_id.label("work_id"),
                func.max(LibraryReadingProgress.updated_at).label("last_read_at"),
            )
            .join(
                LibraryVolume, LibraryVolume.version_id == LibraryVersion.id
            )
            .join(
                LibraryReadingProgress,
                LibraryReadingProgress.volume_id == LibraryVolume.id,
            )
            .where(LibraryReadingProgress.user_id == user.id)
            .group_by(LibraryVersion.work_id)
            .subquery()
        )
        statement = statement.outerjoin(
            latest_read, latest_read.c.work_id == LibraryWork.id
        ).order_by(
            case((latest_read.c.last_read_at.is_(None), 1), else_=0),
            latest_read.c.last_read_at.desc(),
            LibraryWork.id.asc(),
        )
    else:
        statement = statement.order_by(*_order(query))
    works = db.scalars(statement.limit(page_size).offset((page - 1) * page_size)).all()
    return WorkListResult(
        works=[entity_as_legacy_dict(work) for work in works],
        total=total,
        page=page,
        page_size=page_size,
        progress_sort=query.sort == "progress",
    )
