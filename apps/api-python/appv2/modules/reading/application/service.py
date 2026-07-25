from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from appv2.modules.catalog.contracts import CatalogFile, CatalogReadPort, CatalogVolume
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
        self,
        *,
        user_id: uuid.UUID,
        edition_id: uuid.UUID,
        volume_id: uuid.UUID | None = None,
    ) -> tuple[
        ReaderTarget,
        ProgressView | None,
        list[BookmarkView],
        PreferenceView | None,
        list[CatalogFile],
        list[CatalogVolume],
    ]:
        edition = self._catalog.get_edition(edition_id)
        if edition is None:
            raise ReadingNotFound
        work = self._catalog.get_work(edition.work_id)
        if work is None:
            raise ReadingNotFound
        files = self._catalog.files_for_edition(edition_id)
        if not files:
            raise ReadingNotFound
        selected = next(
            (file for file in files if volume_id is not None and file.volume_id == volume_id),
            files[0],
        )
        target = ReaderTarget(
            work_id=work.id,
            work_title=work.title,
            work_author=work.author,
            edition_id=edition.id,
            edition_title=edition.title,
            file_id=selected.id,
            format=edition.format,
            media_type=selected.media_type,
            resource_url=f"/api/v2/reading/files/{selected.id}",
            checksum=selected.checksum,
        )
        with self._uow_factory() as uow:
            progress = uow.reading.get_progress(user_id=user_id, edition_id=edition_id)
            bookmarks = uow.reading.list_bookmarks(user_id=user_id, edition_id=edition_id)
            preference = uow.reading.get_preference(
                user_id=user_id, scope="edition", target_id=edition_id
            )
        return (
            target,
            progress,
            bookmarks,
            preference,
            files,
            self._catalog.volumes_for_edition(edition_id),
        )

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

    def file_resource(
        self,
        *,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
        requested_range: ByteRange | None,
    ) -> ResourceStream:
        file = self._catalog.get_file(file_id)
        if file is None:
            raise ReadingNotFound
        try:
            return self._resources.open(
                file,
                requested_range=requested_range,
                stream_key=str(user_id),
            )
        except (FileNotFoundError, ValueError) as error:
            raise ReadingNotFound from error

    def comic_pages(self, *, target_id: uuid.UUID) -> list[ComicPage]:
        file = self._comic_file(target_id)
        if file is None:
            raise ReadingNotFound
        try:
            return self._resources.comic_pages(file)
        except (FileNotFoundError, ValueError) as error:
            raise ReadingNotFound from error

    def comic_page(
        self,
        *,
        user_id: uuid.UUID,
        target_id: uuid.UUID,
        page_index: int,
    ) -> ResourceStream:
        file = self._comic_file(target_id)
        if file is None:
            raise ReadingNotFound
        try:
            return self._resources.open_comic_page(
                file,
                page_index=page_index,
                stream_key=str(user_id),
            )
        except (FileNotFoundError, ValueError) as error:
            raise ReadingNotFound from error

    def _comic_file(self, target_id: uuid.UUID) -> CatalogFile | None:
        edition = self._catalog.get_edition(target_id)
        if edition is not None:
            files = self._catalog.files_for_edition(edition.id)
            return files[0] if files else None
        volume = self._catalog.get_volume(target_id)
        if volume is None:
            return None
        return next(
            (
                file
                for file in self._catalog.files_for_edition(volume.edition_id)
                if file.volume_id == volume.id
            ),
            None,
        )

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
