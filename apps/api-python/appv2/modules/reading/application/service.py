from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from appv2.modules.catalog.contracts import CatalogReadPort
from appv2.modules.reading.contracts import (
    BookmarkView,
    ComicPage,
    PreferenceView,
    ProgressMutation,
    ProgressView,
    ReaderResourcePort,
    ReaderTarget,
    ReadingUnitOfWork,
    ResourceStream,
)
from appv2.platform.http.ranges import ByteRange


class ReadingNotFound(Exception):
    pass


class ProgressConflict(Exception):
    pass


class LocationClaimConflict(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LocationClaimResult:
    status: Literal["ready", "claimed", "generating"]
    serialized: str | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    retry_after_ms: int | None = None


class ReadingService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], ReadingUnitOfWork],
        catalog: CatalogReadPort,
        resources: ReaderResourcePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog
        self._resources = resources

    def bootstrap(
        self, *, user_id: uuid.UUID, edition_id: uuid.UUID
    ) -> tuple[ReaderTarget, ProgressView | None, list[BookmarkView], PreferenceView | None]:
        edition = self._catalog.get_edition(edition_id)
        if edition is None:
            raise ReadingNotFound
        work = self._catalog.get_work(edition.work_id)
        if work is None:
            raise ReadingNotFound
        files = self._catalog.files_for_edition(edition_id)
        if not files:
            raise ReadingNotFound
        selected = files[0]
        target = ReaderTarget(
            work_id=work.id,
            work_title=work.title,
            work_author=work.author,
            edition_id=edition.id,
            edition_title=edition.title,
            file_id=selected.id,
            format=edition.format,
            media_type=selected.media_type,
            resource_url=f"/api/v2/reading/editions/{edition.id}/resource",
            checksum=selected.checksum,
        )
        with self._uow_factory() as uow:
            progress = uow.reading.get_progress(user_id=user_id, edition_id=edition_id)
            bookmarks = uow.reading.list_bookmarks(user_id=user_id, edition_id=edition_id)
            preference = uow.reading.get_preference(
                user_id=user_id, scope="edition", target_id=edition_id
            )
        return target, progress, bookmarks, preference

    def resource(
        self,
        *,
        user_id: uuid.UUID,
        edition_id: uuid.UUID,
        requested_range: ByteRange | None,
    ) -> ResourceStream:
        if self._catalog.get_edition(edition_id) is None:
            raise ReadingNotFound
        files = self._catalog.files_for_edition(edition_id)
        if not files:
            raise ReadingNotFound
        try:
            return self._resources.open(
                files[0],
                requested_range=requested_range,
                stream_key=str(user_id),
            )
        except (FileNotFoundError, ValueError) as error:
            raise ReadingNotFound from error

    def comic_pages(self, *, edition_id: uuid.UUID) -> list[ComicPage]:
        edition = self._catalog.get_edition(edition_id)
        files = self._catalog.files_for_edition(edition_id)
        if edition is None or not files:
            raise ReadingNotFound
        try:
            return self._resources.comic_pages(files[0])
        except (FileNotFoundError, ValueError) as error:
            raise ReadingNotFound from error

    def comic_page(
        self,
        *,
        user_id: uuid.UUID,
        edition_id: uuid.UUID,
        page_index: int,
    ) -> ResourceStream:
        edition = self._catalog.get_edition(edition_id)
        files = self._catalog.files_for_edition(edition_id)
        if edition is None or not files:
            raise ReadingNotFound
        try:
            return self._resources.open_comic_page(
                files[0],
                page_index=page_index,
                stream_key=str(user_id),
            )
        except (FileNotFoundError, ValueError) as error:
            raise ReadingNotFound from error

    def get_progress(self, *, user_id: uuid.UUID, edition_id: uuid.UUID) -> ProgressView | None:
        with self._uow_factory() as uow:
            return uow.reading.get_progress(user_id=user_id, edition_id=edition_id)

    def save_progress(
        self,
        *,
        user_id: uuid.UUID,
        edition_id: uuid.UUID,
        device_id: str,
        position: dict[str, object],
        percentage: float,
        occurred_at: datetime | None,
        expected_version: int | None,
    ) -> ProgressView:
        mutation = ProgressMutation(
            edition_id=edition_id,
            user_id=user_id,
            device_id=device_id,
            position=position,
            percentage=percentage,
            occurred_at=occurred_at or datetime.now(UTC),
            expected_version=expected_version,
        )
        with self._uow_factory() as uow:
            try:
                progress = uow.reading.save_progress(mutation)
            except ValueError as error:
                raise ProgressConflict from error
            uow.commit()
            return progress

    def list_bookmarks(self, *, user_id: uuid.UUID, edition_id: uuid.UUID) -> list[BookmarkView]:
        with self._uow_factory() as uow:
            return uow.reading.list_bookmarks(user_id=user_id, edition_id=edition_id)

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
        with self._uow_factory() as uow:
            bookmark = uow.reading.put_bookmark(
                user_id=user_id,
                edition_id=edition_id,
                client_id=client_id,
                label=label,
                position=position,
                excerpt=excerpt,
            )
            uow.commit()
            return bookmark

    def delete_bookmark(
        self,
        *,
        user_id: uuid.UUID,
        edition_id: uuid.UUID,
        bookmark_id: uuid.UUID,
    ) -> None:
        with self._uow_factory() as uow:
            if not uow.reading.delete_bookmark(
                user_id=user_id,
                edition_id=edition_id,
                bookmark_id=bookmark_id,
            ):
                raise ReadingNotFound
            uow.commit()

    def get_preference(
        self, *, user_id: uuid.UUID, scope: str, target_id: uuid.UUID | None
    ) -> PreferenceView | None:
        with self._uow_factory() as uow:
            return uow.reading.get_preference(user_id=user_id, scope=scope, target_id=target_id)

    def save_preference(
        self,
        *,
        user_id: uuid.UUID,
        scope: str,
        target_id: uuid.UUID | None,
        values: dict[str, object],
    ) -> PreferenceView:
        with self._uow_factory() as uow:
            preference = uow.reading.save_preference(
                user_id=user_id,
                scope=scope,
                target_id=target_id,
                values=values,
            )
            uow.commit()
            return preference

    def claim_epub_locations(
        self,
        *,
        user_id: uuid.UUID,
        edition_id: uuid.UUID,
        content_fingerprint: str,
        cache_version: int,
        break_size: int,
    ) -> LocationClaimResult:
        if self._catalog.get_edition(edition_id) is None:
            raise ReadingNotFound
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=2)
        lease_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(lease_token.encode()).hexdigest()
        with self._uow_factory() as uow:
            cache = uow.reading.claim_locations(
                edition_id=edition_id,
                content_fingerprint=content_fingerprint,
                cache_version=cache_version,
                break_size=break_size,
                owner=str(user_id),
                token_hash=token_hash,
                now=now,
                expires_at=expires_at,
            )
            uow.commit()
        if cache.serialized:
            return LocationClaimResult(status="ready", serialized=cache.serialized)
        if cache.token_hash == token_hash:
            return LocationClaimResult(
                status="claimed",
                lease_token=lease_token,
                lease_expires_at=cache.expires_at,
            )
        retry_after = max(250, int((cache.expires_at - now).total_seconds() * 1000))
        return LocationClaimResult(
            status="generating",
            lease_expires_at=cache.expires_at,
            retry_after_ms=retry_after,
        )

    def save_epub_locations(
        self,
        *,
        edition_id: uuid.UUID,
        content_fingerprint: str,
        cache_version: int,
        break_size: int,
        lease_token: str,
        serialized: str,
    ) -> LocationClaimResult:
        if self._catalog.get_edition(edition_id) is None:
            raise ReadingNotFound
        with self._uow_factory() as uow:
            try:
                cache = uow.reading.save_locations(
                    edition_id=edition_id,
                    content_fingerprint=content_fingerprint,
                    cache_version=cache_version,
                    break_size=break_size,
                    token_hash=hashlib.sha256(lease_token.encode()).hexdigest(),
                    serialized=serialized,
                    now=datetime.now(UTC),
                )
            except ValueError as error:
                raise LocationClaimConflict from error
            uow.commit()
        return LocationClaimResult(status="ready", serialized=cache.serialized)
