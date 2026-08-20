"""SQLAlchemy adapter for the user-scoped bookshelf projection."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.library import (
    LibraryReadingProgress,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.application.bookshelf import (
    BookshelfItemQueryPort,
    BookshelfItemSummary,
)
from app.modules.library.infrastructure.media_kind_sql import (
    volume_effective_media_kind,
)
from app.modules.reader.public import (
    MediaKind,
    VolumeReadingState,
    choose_continue_volume_id,
)

_MEDIA_KIND_ORDER = {"EBOOK": 0, "COMIC": 1, "AUDIOBOOK": 2}


class SqlAlchemyBookshelfItemQueries(BookshelfItemQueryPort):
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_items(
        self,
        *,
        context: AuthorizationContext,
        work_ids: tuple[str, ...],
    ) -> tuple[BookshelfItemSummary, ...]:
        works = self._db.scalars(
            select(LibraryWork).where(
                LibraryWork.id.in_(work_ids),
                LibraryWork.hidden.is_(False),
                work_visibility_predicate(context),
            )
        ).all()
        work_by_id = {work.id: work for work in works}
        visible_work_ids = tuple(
            work_id for work_id in work_ids if work_id in work_by_id
        )
        if not visible_work_ids:
            return ()

        media_kind = volume_effective_media_kind(LibraryVolume)
        rows = self._db.execute(
            select(
                LibraryVersion.work_id,
                media_kind.label("media_kind"),
                LibraryVolume.id.label("volume_id"),
                LibraryVolume.sort_order,
                LibraryReadingProgress.percent,
                LibraryReadingProgress.updated_at.label("progress_updated_at"),
            )
            .select_from(LibraryVolume)
            .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
            .outerjoin(
                LibraryReadingProgress,
                and_(
                    LibraryReadingProgress.volume_id == LibraryVolume.id,
                    LibraryReadingProgress.user_id == context.user_id,
                ),
            )
            .where(
                LibraryVersion.work_id.in_(visible_work_ids),
                LibraryVolume.hidden.is_(False),
                volume_visibility_predicate(context),
            )
            .order_by(
                LibraryVersion.work_id.asc(),
                LibraryVolume.sort_order.asc(),
                LibraryVolume.id.asc(),
            )
        ).all()
        media_kinds_by_work: dict[str, set[str]] = defaultdict(set)
        states_by_work: dict[str, list[VolumeReadingState]] = defaultdict(list)
        percent_by_volume: dict[str, float] = {}
        for row in rows:
            work_id = str(row.work_id)
            media_kind = MediaKind(str(row.media_kind))
            media_kinds_by_work[work_id].add(media_kind.value)
            percent = min(100.0, max(0.0, float(row.percent or 0)))
            volume_id = str(row.volume_id)
            percent_by_volume[volume_id] = percent
            states_by_work[work_id].append(
                VolumeReadingState(
                    volume_id=volume_id,
                    media_kind=media_kind,
                    sort_order=int(row.sort_order),
                    percent=int(percent),
                    last_read_at=row.progress_updated_at,
                )
            )

        summaries: list[BookshelfItemSummary] = []
        for work_id in visible_work_ids:
            work = work_by_id[work_id]
            continue_volume_id = choose_continue_volume_id(states_by_work[work_id])
            summaries.append(
                BookshelfItemSummary(
                    id=work.id,
                    title=work.title or "未命名作品",
                    author=work.author or "未知作者",
                    cover_path=work.cover_path,
                    updated_at=work.updated_at,
                    available_media_kinds=tuple(
                        sorted(
                            media_kinds_by_work[work_id],
                            key=lambda kind: _MEDIA_KIND_ORDER.get(kind, 99),
                        )
                    ),
                    progress=(
                        percent_by_volume.get(continue_volume_id, 0.0)
                        if continue_volume_id is not None
                        else 0.0
                    ),
                )
            )
        return tuple(summaries)
