"""SQLAlchemy adapter for the isolated Reader v5 progress aggregate."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAssetDto,
    ReaderNavigationUnitDto,
    ReaderResourceContextDto,
    ReaderResourceDto,
)
from app.modules.reader.application.v5_dto import (
    ReaderV5BookmarkDto,
    ReaderV5ChapterDto,
    ReaderV5MutationDto,
    ReaderV5PageDto,
    ReaderV5PlaybackDto,
    ReaderV5PositionDto,
    ReaderV5PresentationDto,
    ReaderV5ProgressDto,
    ReaderV5ReadingStatusDto,
    ReaderV5StoredBookmarkDto,
)
from app.modules.reader.application.v5_locator import OpaqueLocator
from app.modules.reader.application.v5_position import ReaderV5StoredPosition
from app.modules.reader.infrastructure.persistence.models import (
    ReaderBookmarkV5,
    ReaderProgressMutationV5,
    ReaderResourceProgressV5,
    ReaderResourceReadingStatusV5,
)
from app.modules.reader.infrastructure.resource_catalog_repository import (
    SqlAlchemyReaderResourceCatalogRepository,
)


def _presentation_from_json(presentation_json: str) -> ReaderV5PresentationDto:
    """Decode only the known, separately stored presentation projection.

    Locator bytes are stored in a separate column and are never passed through
    this decoder.
    """

    presentation = json.loads(presentation_json)
    if not isinstance(presentation, dict):
        raise TypeError("Stored Reader v5 presentation is not an object")

    raw_chapter = presentation["chapter"]
    chapter = (
        None
        if raw_chapter is None
        else ReaderV5ChapterDto(
            href=raw_chapter["href"],
            title=raw_chapter["title"],
            index=raw_chapter["index"],
        )
    )
    raw_page = presentation["page"]
    page = (
        None
        if raw_page is None
        else ReaderV5PageDto(number=raw_page["number"], total=raw_page["total"])
    )
    raw_playback = presentation["playback"]
    playback = (
        None
        if raw_playback is None
        else ReaderV5PlaybackDto(
            position_millis=raw_playback["positionMillis"],
            duration_millis=raw_playback["durationMillis"],
        )
    )
    return ReaderV5PresentationDto(
        display_percent=presentation["displayPercent"],
        total_progression=presentation["totalProgression"],
        current_href=presentation["currentHref"],
        chapter=chapter,
        page=page,
        playback=playback,
    )


def _position_dto(*, presentation_json: str, locator_json: str) -> ReaderV5PositionDto:
    return ReaderV5PositionDto(
        locator=OpaqueLocator.from_serialized(locator_json),
        presentation=_presentation_from_json(presentation_json),
    )


def _progress_dto(progress: ReaderResourceProgressV5) -> ReaderV5ProgressDto:
    return ReaderV5ProgressDto(
        id=progress.id,
        user_id=progress.user_id,
        resource_id=progress.resource_id,
        client_id=progress.client_id,
        mutation_id=progress.mutation_id,
        revision=progress.revision,
        position=_position_dto(
            presentation_json=progress.presentation_json,
            locator_json=progress.locator_json,
        ),
        captured_at=progress.captured_at,
        received_at=progress.received_at,
        updated_at=progress.updated_at,
    )


def _mutation_dto(mutation: ReaderProgressMutationV5) -> ReaderV5MutationDto:
    return ReaderV5MutationDto(
        mutation_id=mutation.mutation_id,
        client_id=mutation.client_id,
        accepted_revision=mutation.accepted_revision,
        payload_hash=mutation.payload_hash,
        captured_at=mutation.captured_at,
        received_at=mutation.received_at,
    )


def _bookmark_dto(bookmark: ReaderBookmarkV5) -> ReaderV5BookmarkDto:
    return ReaderV5BookmarkDto(
        bookmark_id=bookmark.bookmark_id,
        position=_position_dto(
            presentation_json=bookmark.presentation_json,
            locator_json=bookmark.locator_json,
        ),
        label=bookmark.label,
        created_at=bookmark.bookmark_created_at,
    )


class SqlAlchemyReaderV5Repository:
    """V5 persistence composed with the version-neutral resource catalog."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._resources = SqlAlchemyReaderResourceCatalogRepository(session)

    def is_mutation_conflict(self, error: Exception) -> bool:
        return isinstance(error, IntegrityError)

    def get_visible_context(
        self, resource_id: str, access_scope: ReaderAccessScope
    ) -> ReaderResourceContextDto | None:
        return self._resources.get_visible_context(resource_id, access_scope)

    def list_visible_resources_for_book(
        self, book_id: str, access_scope: ReaderAccessScope
    ) -> list[ReaderResourceDto]:
        return self._resources.list_visible_resources_for_book(book_id, access_scope)

    def list_assets(self, resource_id: str) -> list[ReaderAssetDto]:
        return self._resources.list_assets(resource_id)

    def list_navigation_units(self, resource_id: str) -> list[ReaderNavigationUnitDto]:
        return self._resources.list_navigation_units(resource_id)

    def get_v5_progress(
        self, user_id: str, resource_id: str
    ) -> ReaderV5ProgressDto | None:
        progress = self._session.scalar(
            select(ReaderResourceProgressV5).where(
                ReaderResourceProgressV5.user_id == user_id,
                ReaderResourceProgressV5.resource_id == resource_id,
            )
        )
        return _progress_dto(progress) if progress is not None else None

    def list_v5_progresses(
        self, user_id: str, resource_ids: list[str]
    ) -> list[ReaderV5ProgressDto]:
        if not resource_ids:
            return []
        progresses = self._session.scalars(
            select(ReaderResourceProgressV5).where(
                ReaderResourceProgressV5.user_id == user_id,
                ReaderResourceProgressV5.resource_id.in_(resource_ids),
            )
        ).all()
        return [_progress_dto(progress) for progress in progresses]

    def get_v5_mutation(
        self, user_id: str, resource_id: str, mutation_id: str
    ) -> ReaderV5MutationDto | None:
        mutation = self._session.scalar(
            select(ReaderProgressMutationV5).where(
                ReaderProgressMutationV5.user_id == user_id,
                ReaderProgressMutationV5.resource_id == resource_id,
                ReaderProgressMutationV5.mutation_id == mutation_id,
            )
        )
        return _mutation_dto(mutation) if mutation is not None else None

    def save_v5_progress(
        self,
        *,
        user_id: str,
        resource_id: str,
        client_id: str,
        mutation_id: str,
        payload_hash: str,
        stored_position: ReaderV5StoredPosition,
        captured_at: datetime,
        received_at: datetime,
    ) -> ReaderV5ProgressDto:
        presentation = stored_position.presentation
        chapter = presentation.chapter
        page = presentation.page
        playback = presentation.playback
        statement = (
            sqlite_insert(ReaderResourceProgressV5)
            .values(
                user_id=user_id,
                resource_id=resource_id,
                client_id=client_id,
                mutation_id=mutation_id,
                locator_json=stored_position.locator.serialized,
                presentation_json=stored_position.presentation_json,
                display_percent=presentation.display_percent,
                total_progression=presentation.total_progression,
                current_href=presentation.current_href,
                chapter_href=chapter.href if chapter is not None else None,
                chapter_title=chapter.title if chapter is not None else None,
                chapter_index=chapter.index if chapter is not None else None,
                page_number=page.number if page is not None else None,
                page_total=page.total if page is not None else None,
                playback_position_millis=(
                    playback.position_millis if playback is not None else None
                ),
                playback_duration_millis=(
                    playback.duration_millis if playback is not None else None
                ),
                captured_at=captured_at,
                received_at=received_at,
                updated_at=received_at,
                revision=1,
            )
            .on_conflict_do_update(
                index_elements=[
                    ReaderResourceProgressV5.user_id,
                    ReaderResourceProgressV5.resource_id,
                ],
                set_={
                    ReaderResourceProgressV5.client_id: client_id,
                    ReaderResourceProgressV5.mutation_id: mutation_id,
                    ReaderResourceProgressV5.locator_json: stored_position.locator.serialized,
                    ReaderResourceProgressV5.presentation_json: stored_position.presentation_json,
                    ReaderResourceProgressV5.display_percent: presentation.display_percent,
                    ReaderResourceProgressV5.total_progression: presentation.total_progression,
                    ReaderResourceProgressV5.current_href: presentation.current_href,
                    ReaderResourceProgressV5.chapter_href: chapter.href
                    if chapter is not None
                    else None,
                    ReaderResourceProgressV5.chapter_title: chapter.title
                    if chapter is not None
                    else None,
                    ReaderResourceProgressV5.chapter_index: chapter.index
                    if chapter is not None
                    else None,
                    ReaderResourceProgressV5.page_number: page.number
                    if page is not None
                    else None,
                    ReaderResourceProgressV5.page_total: page.total
                    if page is not None
                    else None,
                    ReaderResourceProgressV5.playback_position_millis: playback.position_millis
                    if playback is not None
                    else None,
                    ReaderResourceProgressV5.playback_duration_millis: playback.duration_millis
                    if playback is not None
                    else None,
                    ReaderResourceProgressV5.captured_at: captured_at,
                    ReaderResourceProgressV5.received_at: received_at,
                    ReaderResourceProgressV5.updated_at: received_at,
                    ReaderResourceProgressV5.revision: ReaderResourceProgressV5.revision
                    + 1,
                },
            )
            .returning(ReaderResourceProgressV5)
        )
        progress = self._session.scalar(statement)
        if progress is None:
            raise RuntimeError("Reader v5 progress upsert returned no row")
        self._session.add(
            ReaderProgressMutationV5(
                user_id=user_id,
                resource_id=resource_id,
                mutation_id=mutation_id,
                client_id=client_id,
                accepted_revision=progress.revision,
                payload_hash=payload_hash,
                captured_at=captured_at,
                received_at=received_at,
            )
        )
        return _progress_dto(progress)

    def get_v5_reading_status(
        self, user_id: str, resource_id: str
    ) -> ReaderV5ReadingStatusDto | None:
        status = self._session.scalar(
            select(ReaderResourceReadingStatusV5).where(
                ReaderResourceReadingStatusV5.user_id == user_id,
                ReaderResourceReadingStatusV5.resource_id == resource_id,
            )
        )
        if status is None:
            return None
        return ReaderV5ReadingStatusDto(
            resource_id=status.resource_id,
            status=cast(Literal["UNREAD", "FINISHED"], status.status),
            updated_at=status.updated_at,
        )

    def set_v5_reading_status(
        self,
        *,
        user_id: str,
        resource_id: str,
        status: Literal["UNREAD", "FINISHED"],
        updated_at: datetime,
    ) -> ReaderV5ReadingStatusDto:
        statement = (
            sqlite_insert(ReaderResourceReadingStatusV5)
            .values(
                user_id=user_id,
                resource_id=resource_id,
                status=status,
                updated_at=updated_at,
            )
            .on_conflict_do_update(
                index_elements=[
                    ReaderResourceReadingStatusV5.user_id,
                    ReaderResourceReadingStatusV5.resource_id,
                ],
                set_={
                    ReaderResourceReadingStatusV5.status: status,
                    ReaderResourceReadingStatusV5.updated_at: updated_at,
                },
            )
            .returning(ReaderResourceReadingStatusV5)
        )
        row = self._session.scalar(statement)
        if row is None:
            raise RuntimeError("Reader v5 status upsert returned no row")
        return ReaderV5ReadingStatusDto(
            resource_id=row.resource_id,
            status=cast(Literal["UNREAD", "FINISHED"], row.status),
            updated_at=row.updated_at,
        )

    def list_v5_bookmarks(
        self, user_id: str, resource_id: str
    ) -> list[ReaderV5BookmarkDto]:
        bookmarks = self._session.scalars(
            select(ReaderBookmarkV5)
            .where(
                ReaderBookmarkV5.user_id == user_id,
                ReaderBookmarkV5.resource_id == resource_id,
            )
            .order_by(
                ReaderBookmarkV5.bookmark_created_at,
                ReaderBookmarkV5.bookmark_id,
            )
        ).all()
        return [_bookmark_dto(bookmark) for bookmark in bookmarks]

    def replace_v5_bookmarks(
        self,
        *,
        user_id: str,
        resource_id: str,
        bookmarks: tuple[ReaderV5StoredBookmarkDto, ...],
        updated_at: datetime,
    ) -> list[ReaderV5BookmarkDto]:
        self._session.execute(
            delete(ReaderBookmarkV5).where(
                ReaderBookmarkV5.user_id == user_id,
                ReaderBookmarkV5.resource_id == resource_id,
            )
        )
        self._session.add_all(
            [
                ReaderBookmarkV5(
                    user_id=user_id,
                    resource_id=resource_id,
                    bookmark_id=bookmark.bookmark_id,
                    locator_json=bookmark.stored_position.locator.serialized,
                    presentation_json=bookmark.stored_position.presentation_json,
                    label=bookmark.label,
                    bookmark_created_at=bookmark.created_at,
                    created_at=updated_at,
                    updated_at=updated_at,
                )
                for bookmark in bookmarks
            ]
        )
        self._session.flush()
        return self.list_v5_bookmarks(user_id, resource_id)
