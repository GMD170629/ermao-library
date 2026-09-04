"""SQLAlchemy adapter for resource-scoped Reader state and assets."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.models import (
    ReaderProgressMutation,
    ReaderResourceProgress,
)
from app.models.auth import ReaderBookmark
from app.models.common import cuid
from app.modules.reader.application.dto import (
    ReaderBookmarkDto,
    ReaderExactLocationDto,
    ReaderProgressDto,
    ReaderReadingStatus,
    ReaderResourceContextDto,
)
from app.modules.reader.application.exact_location import exact_location_kind
from app.modules.reader.infrastructure.exact_location_codec import (
    decode_exact_location,
    encode_exact_location,
)
from app.modules.reader.infrastructure.resource_catalog_repository import (
    SqlAlchemyReaderResourceCatalogRepository,
)


def _progress_dto(progress: ReaderResourceProgress) -> ReaderProgressDto:
    return ReaderProgressDto(
        id=progress.id,
        user_id=progress.user_id,
        resource_id=progress.resource_id,
        reader_type=progress.reader_type,
        percent=progress.percent,
        location_json=progress.location_json,
        exact_location=(
            decode_exact_location(progress.location_json)
            if progress.revision >= 1
            else None
        ),
        mutation_id=progress.mutation_id,
        client_id=progress.client_id,
        client_sequence=progress.client_sequence,
        progressed_at=progress.progressed_at,
        source_protocol=progress.source_protocol,
        source_device_name=progress.source_device_name,
        updated_at=progress.updated_at,
        revision=progress.revision,
    )


def _mutation_progress_dto(mutation: ReaderProgressMutation) -> ReaderProgressDto:
    exact_location = decode_exact_location(mutation.locator_json)
    return ReaderProgressDto(
        id=mutation.id,
        user_id=mutation.user_id,
        resource_id=mutation.resource_id,
        reader_type=(
            exact_location_kind(exact_location)
            if exact_location is not None
            else "unknown"
        ),
        percent=mutation.display_percent,
        location_json=mutation.locator_json,
        exact_location=exact_location,
        mutation_id=mutation.mutation_id,
        client_id=mutation.client_id,
        client_sequence=None,
        progressed_at=mutation.captured_at,
        source_protocol="SHUKU_READER_V4",
        source_device_name=None,
        updated_at=mutation.received_at,
        revision=mutation.revision,
    )


def _bookmark_datetime(value: str, fallback: datetime) -> datetime:
    normalized = value.strip()
    if normalized:
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            try:
                timestamp = float(normalized)
                if abs(timestamp) >= 10_000_000_000:
                    timestamp /= 1000
                return datetime.fromtimestamp(timestamp, tz=UTC)
            except (OSError, OverflowError, ValueError):
                pass
    return fallback if fallback.tzinfo is not None else fallback.replace(tzinfo=UTC)


def _bookmark_dto(bookmark: ReaderBookmark) -> ReaderBookmarkDto:
    return ReaderBookmarkDto(
        id=bookmark.id,
        bookmark_id=bookmark.bookmark_id,
        location_json=bookmark.location_json,
        label=bookmark.label,
        percent=bookmark.percent,
        bookmark_created_at=_bookmark_datetime(
            bookmark.bookmark_created_at,
            bookmark.created_at,
        ),
    )


class SqlAlchemyReaderResourceRepository(SqlAlchemyReaderResourceCatalogRepository):
    """Resource-owned Reader repository; commits remain owned by the use case."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def get_progress(self, user_id: str, resource_id: str) -> ReaderProgressDto | None:
        progress = self._session.scalar(
            select(ReaderResourceProgress).where(
                ReaderResourceProgress.user_id == user_id,
                ReaderResourceProgress.resource_id == resource_id,
            )
        )
        return _progress_dto(progress) if progress is not None else None

    def list_progresses(
        self, user_id: str, resource_ids: list[str]
    ) -> list[ReaderProgressDto]:
        if not resource_ids:
            return []
        progresses = self._session.scalars(
            select(ReaderResourceProgress).where(
                ReaderResourceProgress.user_id == user_id,
                ReaderResourceProgress.resource_id.in_(resource_ids),
            )
        ).all()
        return [_progress_dto(progress) for progress in progresses]

    def get_progress_mutation(
        self, user_id: str, resource_id: str, mutation_id: str
    ) -> ReaderProgressDto | None:
        mutation = self._session.scalar(
            select(ReaderProgressMutation).where(
                ReaderProgressMutation.user_id == user_id,
                ReaderProgressMutation.resource_id == resource_id,
                ReaderProgressMutation.mutation_id == mutation_id,
            )
        )
        return _mutation_progress_dto(mutation) if mutation is not None else None

    def save_exact_progress(
        self,
        *,
        user_id: str,
        context: ReaderResourceContextDto,
        reader_type: str,
        display_percent: float,
        location: ReaderExactLocationDto,
        client_id: str,
        mutation_id: str,
        base_revision: int,
        next_revision: int,
        progressed_at: datetime,
        now: datetime,
    ) -> ReaderProgressDto | None:
        locator_json = encode_exact_location(location)
        location_kind = exact_location_kind(location)
        if base_revision == 0:
            progress = self._session.scalar(
                sqlite_insert(ReaderResourceProgress)
                .values(
                    id=cuid(),
                    user_id=user_id,
                    resource_id=context.resource.id,
                    reader_type=reader_type,
                    position="0",
                    page=None,
                    percent=display_percent,
                    extra="{}",
                    schema_version=4,
                    location_type=location_kind,
                    location_json=locator_json,
                    mutation_id=mutation_id,
                    client_id=client_id,
                    client_sequence=None,
                    progressed_at=progressed_at,
                    source_protocol="SHUKU_READER_V4",
                    source_device_name=None,
                    created_at=now,
                    updated_at=now,
                    revision=next_revision,
                )
                .on_conflict_do_update(
                    index_elements=[
                        ReaderResourceProgress.user_id,
                        ReaderResourceProgress.resource_id,
                    ],
                    set_={
                        ReaderResourceProgress.reader_type: reader_type,
                        ReaderResourceProgress.percent: display_percent,
                        ReaderResourceProgress.schema_version: 4,
                        ReaderResourceProgress.location_type: location_kind,
                        ReaderResourceProgress.location_json: locator_json,
                        ReaderResourceProgress.mutation_id: mutation_id,
                        ReaderResourceProgress.client_id: client_id,
                        ReaderResourceProgress.client_sequence: None,
                        ReaderResourceProgress.progressed_at: progressed_at,
                        ReaderResourceProgress.source_protocol: "SHUKU_READER_V4",
                        ReaderResourceProgress.source_device_name: None,
                        ReaderResourceProgress.updated_at: now,
                        ReaderResourceProgress.revision: next_revision,
                    },
                    where=ReaderResourceProgress.revision == 0,
                )
                .returning(ReaderResourceProgress)
            )
        else:
            progress = self._session.scalar(
                update(ReaderResourceProgress)
                .where(
                    ReaderResourceProgress.user_id == user_id,
                    ReaderResourceProgress.resource_id == context.resource.id,
                    ReaderResourceProgress.revision == base_revision,
                )
                .values(
                    reader_type=reader_type,
                    percent=display_percent,
                    schema_version=4,
                    location_type=location_kind,
                    location_json=locator_json,
                    mutation_id=mutation_id,
                    client_id=client_id,
                    client_sequence=None,
                    progressed_at=progressed_at,
                    source_protocol="SHUKU_READER_V4",
                    source_device_name=None,
                    updated_at=now,
                    revision=next_revision,
                )
                .returning(ReaderResourceProgress)
                .execution_options(populate_existing=True)
            )
        if progress is None:
            return None

        self._session.add(
            ReaderProgressMutation(
                user_id=user_id,
                resource_id=context.resource.id,
                mutation_id=mutation_id,
                client_id=client_id,
                revision=next_revision,
                locator_json=locator_json,
                display_percent=display_percent,
                captured_at=progressed_at,
                received_at=now,
            )
        )
        self._session.execute(
            delete(ReaderProgressMutation).where(
                ReaderProgressMutation.user_id == user_id,
                ReaderProgressMutation.resource_id == context.resource.id,
                ReaderProgressMutation.revision <= next_revision - 32,
            )
        )
        return _progress_dto(progress)

    def set_reading_status(
        self,
        *,
        user_id: str,
        context: ReaderResourceContextDto,
        reader_type: str,
        status: ReaderReadingStatus,
        now: datetime,
    ) -> ReaderProgressDto | None:
        if status == "UNREAD":
            self._session.execute(
                delete(ReaderResourceProgress).where(
                    ReaderResourceProgress.user_id == user_id,
                    ReaderResourceProgress.resource_id == context.resource.id,
                )
            )
            self._session.execute(
                delete(ReaderProgressMutation).where(
                    ReaderProgressMutation.user_id == user_id,
                    ReaderProgressMutation.resource_id == context.resource.id,
                )
            )
            return None

        progress = self._session.scalar(
            sqlite_insert(ReaderResourceProgress)
            .values(
                id=cuid(),
                user_id=user_id,
                resource_id=context.resource.id,
                reader_type=reader_type,
                position="0",
                page=None,
                percent=100,
                extra="{}",
                schema_version=4,
                location_type=None,
                location_json=None,
                mutation_id=None,
                client_id="shuku-library",
                client_sequence=None,
                progressed_at=now,
                source_protocol="SHUKU_READER_V4",
                source_device_name=None,
                created_at=now,
                updated_at=now,
                revision=1,
            )
            .on_conflict_do_update(
                index_elements=[
                    ReaderResourceProgress.user_id,
                    ReaderResourceProgress.resource_id,
                ],
                set_={
                    ReaderResourceProgress.reader_type: reader_type,
                    ReaderResourceProgress.percent: 100,
                    ReaderResourceProgress.schema_version: 4,
                    ReaderResourceProgress.updated_at: now,
                },
            )
            .returning(ReaderResourceProgress)
            .execution_options(populate_existing=True)
        )
        if progress is None:
            raise RuntimeError("resource reading status upsert returned no row")
        return _progress_dto(progress)

    def save_external_progress(
        self,
        *,
        user_id: str,
        context: ReaderResourceContextDto,
        reader_type: str,
        percent: float,
        location_json: str,
        mutation_id: str,
        client_id: str,
        client_sequence: int,
        progressed_at: datetime,
        source_protocol: str,
        source_device_name: str,
        now: datetime,
    ) -> ReaderProgressDto:
        progress = self._session.scalar(
            sqlite_insert(ReaderResourceProgress)
            .values(
                id=cuid(),
                user_id=user_id,
                resource_id=context.resource.id,
                reader_type=reader_type,
                position="0",
                page=None,
                percent=percent,
                extra="{}",
                schema_version=3,
                location_type=reader_type,
                location_json=location_json,
                mutation_id=mutation_id,
                client_id=client_id,
                client_sequence=client_sequence,
                progressed_at=progressed_at,
                source_protocol=source_protocol,
                source_device_name=source_device_name,
                created_at=now,
                updated_at=now,
                revision=1,
            )
            .on_conflict_do_update(
                index_elements=[
                    ReaderResourceProgress.user_id,
                    ReaderResourceProgress.resource_id,
                ],
                set_={
                    ReaderResourceProgress.reader_type: reader_type,
                    ReaderResourceProgress.percent: percent,
                    ReaderResourceProgress.schema_version: 3,
                    ReaderResourceProgress.location_type: reader_type,
                    ReaderResourceProgress.location_json: location_json,
                    ReaderResourceProgress.mutation_id: mutation_id,
                    ReaderResourceProgress.client_id: client_id,
                    ReaderResourceProgress.client_sequence: client_sequence,
                    ReaderResourceProgress.progressed_at: progressed_at,
                    ReaderResourceProgress.source_protocol: source_protocol,
                    ReaderResourceProgress.source_device_name: source_device_name,
                    ReaderResourceProgress.updated_at: now,
                },
            )
            .returning(ReaderResourceProgress)
        )
        if progress is None:
            raise RuntimeError("external resource progress upsert returned no row")
        return _progress_dto(progress)

    def list_bookmarks(self, user_id: str, resource_id: str) -> list[ReaderBookmarkDto]:
        bookmarks = self._session.scalars(
            select(ReaderBookmark)
            .where(
                ReaderBookmark.user_id == user_id,
                ReaderBookmark.resource_id == resource_id,
            )
            .order_by(ReaderBookmark.bookmark_created_at, ReaderBookmark.bookmark_id)
        ).all()
        return [_bookmark_dto(bookmark) for bookmark in bookmarks]

    def replace_bookmarks(
        self,
        *,
        user_id: str,
        resource_id: str,
        bookmarks: list[ReaderBookmarkDto],
        now: datetime,
    ) -> list[ReaderBookmarkDto]:
        rows = [
            {
                ReaderBookmark.id: cuid(),
                ReaderBookmark.user_id: user_id,
                ReaderBookmark.resource_id: resource_id,
                ReaderBookmark.bookmark_id: bookmark.bookmark_id,
                ReaderBookmark.location_json: bookmark.location_json,
                ReaderBookmark.label: bookmark.label,
                ReaderBookmark.percent: bookmark.percent,
                ReaderBookmark.bookmark_created_at: (
                    bookmark.bookmark_created_at.isoformat()
                ),
                ReaderBookmark.created_at: now,
                ReaderBookmark.updated_at: now,
            }
            for bookmark in bookmarks
        ]
        self._session.execute(
            delete(ReaderBookmark).where(
                ReaderBookmark.user_id == user_id,
                ReaderBookmark.resource_id == resource_id,
            )
        )
        for chunk in sqlite_parameter_chunks(rows, parameters_per_row=10):
            self._session.execute(sqlite_insert(ReaderBookmark).values(list(chunk)))
        return self.list_bookmarks(user_id, resource_id)
