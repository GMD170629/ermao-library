from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.reading.contracts import (
    BookmarkView,
    LocationCacheView,
    PreferenceView,
    ProgressMutation,
    ProgressView,
    ReadingRepository,
)
from appv2.modules.reading.domain import ReadingProgress
from appv2.modules.reading.infrastructure.models import (
    BookmarkRecord,
    LocationClaimRecord,
    ProgressRecord,
    ReaderPreferenceRecord,
)


def _progress(record: ProgressRecord) -> ProgressView:
    return ProgressView(
        edition_id=record.edition_id,
        user_id=record.user_id,
        position=record.position,
        percentage=float(record.percentage),
        version=record.version,
        updated_at=record.updated_at,
    )


def _bookmark(record: BookmarkRecord) -> BookmarkView:
    return BookmarkView(
        id=record.id,
        edition_id=record.edition_id,
        client_id=record.client_id,
        label=record.label,
        position=record.position,
        excerpt=record.excerpt,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _preference(record: ReaderPreferenceRecord) -> PreferenceView:
    return PreferenceView(
        scope=record.scope,
        target_id=record.target_id,
        values=record.values,
        updated_at=record.updated_at,
    )


def _location_cache(record: LocationClaimRecord) -> LocationCacheView:
    return LocationCacheView(
        edition_id=record.edition_id,
        content_fingerprint=record.content_fingerprint,
        cache_version=record.cache_version,
        break_size=record.break_size,
        serialized=record.serialized,
        owner=record.owner,
        token_hash=record.token_hash,
        expires_at=record.expires_at,
    )


class SqlReadingRepository(ReadingRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_progress(self, *, user_id: uuid.UUID, edition_id: uuid.UUID) -> ProgressView | None:
        record = self._session.scalar(
            select(ProgressRecord).where(
                ProgressRecord.user_id == user_id,
                ProgressRecord.edition_id == edition_id,
            )
        )
        return _progress(record) if record is not None else None

    def save_progress(self, mutation: ProgressMutation) -> ProgressView:
        record = self._session.scalar(
            select(ProgressRecord)
            .where(
                ProgressRecord.user_id == mutation.user_id,
                ProgressRecord.edition_id == mutation.edition_id,
            )
            .with_for_update()
        )
        if record is None:
            if mutation.expected_version not in {None, 0}:
                raise ValueError("progress version conflict")
            if not 0 <= mutation.percentage <= 1:
                raise ValueError("percentage must be between 0 and 1")
            record = ProgressRecord(
                user_id=mutation.user_id,
                edition_id=mutation.edition_id,
                device_id=mutation.device_id,
                position=mutation.position,
                percentage=Decimal(str(mutation.percentage)),
                version=1,
                occurred_at=mutation.occurred_at,
            )
            self._session.add(record)
        else:
            current = ReadingProgress(
                position=record.position,
                percentage=float(record.percentage),
                version=record.version,
                updated_at=record.occurred_at,
            )
            updated = current.advance(
                position=mutation.position,
                percentage=mutation.percentage,
                occurred_at=mutation.occurred_at,
                expected_version=mutation.expected_version,
            )
            record.device_id = mutation.device_id
            record.position = updated.position
            record.percentage = Decimal(str(updated.percentage))
            record.version = updated.version
            record.occurred_at = updated.updated_at
        self._session.flush()
        return _progress(record)

    def delete_progress(
        self,
        *,
        user_id: uuid.UUID,
        edition_ids: list[uuid.UUID],
    ) -> int:
        if not edition_ids:
            return 0
        records = self._session.scalars(
            select(ProgressRecord).where(
                ProgressRecord.user_id == user_id,
                ProgressRecord.edition_id.in_(edition_ids),
            )
        ).all()
        for record in records:
            self._session.delete(record)
        return len(records)

    def list_bookmarks(self, *, user_id: uuid.UUID, edition_id: uuid.UUID) -> list[BookmarkView]:
        records = self._session.scalars(
            select(BookmarkRecord)
            .where(
                BookmarkRecord.user_id == user_id,
                BookmarkRecord.edition_id == edition_id,
            )
            .order_by(BookmarkRecord.created_at, BookmarkRecord.id)
        ).all()
        return [_bookmark(record) for record in records]

    def put_bookmark(
        self,
        *,
        user_id: uuid.UUID,
        edition_id: uuid.UUID,
        client_id: str,
        label: str | None,
        position: dict[str, object],
        excerpt: str | None,
    ) -> BookmarkView:
        statement = (
            insert(BookmarkRecord)
            .values(
                user_id=user_id,
                edition_id=edition_id,
                client_id=client_id,
                label=label,
                position=position,
                excerpt=excerpt,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                constraint="uq_bookmarks_user_edition_client",
                set_={
                    "label": label,
                    "position": position,
                    "excerpt": excerpt,
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(BookmarkRecord)
        )
        record = self._session.scalar(statement)
        if record is None:
            raise RuntimeError("bookmark upsert did not return a row")
        return _bookmark(record)

    def delete_bookmark(
        self, *, user_id: uuid.UUID, edition_id: uuid.UUID, bookmark_id: uuid.UUID
    ) -> bool:
        record = self._session.scalar(
            select(BookmarkRecord).where(
                BookmarkRecord.id == bookmark_id,
                BookmarkRecord.user_id == user_id,
                BookmarkRecord.edition_id == edition_id,
            )
        )
        if record is None:
            return False
        self._session.delete(record)
        return True

    def get_preference(
        self, *, user_id: uuid.UUID, scope: str, target_id: uuid.UUID | None
    ) -> PreferenceView | None:
        record = self._session.scalar(
            select(ReaderPreferenceRecord).where(
                ReaderPreferenceRecord.user_id == user_id,
                ReaderPreferenceRecord.scope == scope,
                ReaderPreferenceRecord.target_id.is_(target_id)
                if target_id is None
                else ReaderPreferenceRecord.target_id == target_id,
            )
        )
        return _preference(record) if record is not None else None

    def save_preference(
        self,
        *,
        user_id: uuid.UUID,
        scope: str,
        target_id: uuid.UUID | None,
        values: dict[str, object],
    ) -> PreferenceView:
        record = self._session.scalar(
            select(ReaderPreferenceRecord).where(
                ReaderPreferenceRecord.user_id == user_id,
                ReaderPreferenceRecord.scope == scope,
                ReaderPreferenceRecord.target_id.is_(target_id)
                if target_id is None
                else ReaderPreferenceRecord.target_id == target_id,
            )
        )
        if record is None:
            record = ReaderPreferenceRecord(
                user_id=user_id, scope=scope, target_id=target_id, values=values
            )
            self._session.add(record)
        else:
            record.values = values
        self._session.flush()
        return _preference(record)

    def claim_locations(
        self,
        *,
        edition_id: uuid.UUID,
        content_fingerprint: str,
        cache_version: int,
        break_size: int,
        owner: str,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> LocationCacheView:
        record = self._session.scalar(
            select(LocationClaimRecord)
            .where(LocationClaimRecord.edition_id == edition_id)
            .with_for_update()
        )
        matches = (
            record is not None
            and record.content_fingerprint == content_fingerprint
            and record.cache_version == cache_version
            and record.break_size == break_size
        )
        if record is None:
            record = LocationClaimRecord(
                edition_id=edition_id,
                content_fingerprint=content_fingerprint,
                cache_version=cache_version,
                break_size=break_size,
                serialized=None,
                owner=owner,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            self._session.add(record)
        elif not matches or (record.serialized is None and record.expires_at <= now):
            record.content_fingerprint = content_fingerprint
            record.cache_version = cache_version
            record.break_size = break_size
            record.serialized = None
            record.owner = owner
            record.token_hash = token_hash
            record.expires_at = expires_at
        self._session.flush()
        return _location_cache(record)

    def save_locations(
        self,
        *,
        edition_id: uuid.UUID,
        content_fingerprint: str,
        cache_version: int,
        break_size: int,
        token_hash: str,
        serialized: str,
        now: datetime,
    ) -> LocationCacheView:
        record = self._session.scalar(
            select(LocationClaimRecord)
            .where(LocationClaimRecord.edition_id == edition_id)
            .with_for_update()
        )
        if (
            record is None
            or record.content_fingerprint != content_fingerprint
            or record.cache_version != cache_version
            or record.break_size != break_size
            or record.token_hash != token_hash
            or record.expires_at <= now
        ):
            raise ValueError("location claim is invalid or expired")
        record.serialized = serialized
        self._session.flush()
        return _location_cache(record)


class ReadingSqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.reading: ReadingRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.reading = SqlReadingRepository(self._session)
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        if self._session is None:
            return False
        try:
            if exc_type is not None or not self._committed:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None
        return False

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before commit")
        self._session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before rollback")
        self._session.rollback()


def reading_uow_factory(
    session_factory: sessionmaker[Session],
) -> Callable[[], ReadingSqlUnitOfWork]:
    return lambda: ReadingSqlUnitOfWork(session_factory)
