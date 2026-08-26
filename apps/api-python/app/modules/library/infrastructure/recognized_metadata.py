"""ORM and filesystem adapters for manually selected recognized metadata."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as UrlRequest
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    book_visibility_predicate,
    resource_visibility_predicate,
)
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
)
from app.modules.library.application.facet_sync import (
    BookFacetProjection,
    prepare_book_facet,
)
from app.modules.library.application.recognized_metadata import (
    BookMetadataChanges,
    BookMetadataState,
    MetadataTargetScope,
    PublishedRecognizedCover,
    RecognizedCoverMetadataPort,
    RecognizedCoverPublicationPort,
    RecognizedCoverState,
    RecognizedMetadataPort,
    RecognizedMetadataTargetState,
    RecognizedResourceChanges,
    RemoteCoverDownloadPort,
    ResourceMetadataState,
)
from app.modules.library.application.resource_commands import LibraryActor
from app.modules.library.domain.facets import normalize_facet_name
from app.modules.library.infrastructure.facet_sync import (
    execute_book_facet_write,
    prepare_book_facet_write,
)
from app.modules.media.public import validate_cover_url

_MAX_COVER_BYTES = 10 * 1024 * 1024
_IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def _authorization_context(actor: LibraryActor) -> AuthorizationContext:
    return AuthorizationContext(
        user_id=actor.user_id,
        is_admin=actor.is_admin,
        can_manage_system=actor.can_manage_system,
        can_view_manual_imports=actor.can_view_manual_imports,
        library_ids=actor.library_ids,
        authz_version=1,
    )


class SqlAlchemyRecognizedMetadata(RecognizedMetadataPort, RecognizedCoverMetadataPort):
    def __init__(self, db: Session) -> None:
        self._db = db

    def load_target(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
    ) -> RecognizedMetadataTargetState | None:
        context = _authorization_context(actor)
        row = self._db.execute(
            select(LibraryBook, LibraryBookMetadata)
            .join(
                LibraryBookMetadata,
                LibraryBookMetadata.book_id == LibraryBook.id,
            )
            .where(
                LibraryBook.id == book_id,
                book_visibility_predicate(context),
            )
        ).one_or_none()
        if row is None:
            return None
        book, metadata = row
        tags = tuple(
            str(value)
            for value in self._db.scalars(
                select(LibraryFacet.name)
                .join(
                    LibraryBookFacet,
                    LibraryBookFacet.facet_id == LibraryFacet.id,
                )
                .where(
                    LibraryBookFacet.book_id == book.id,
                    LibraryFacet.kind == "TAG",
                )
                .order_by(LibraryBookFacet.sort_order, LibraryFacet.id)
            ).all()
        )
        resource_state = None
        if resource_id is not None:
            resource_row = self._db.execute(
                select(LibraryReadableResourceMetadata)
                .join(
                    LibraryReadableResource,
                    LibraryReadableResource.id
                    == LibraryReadableResourceMetadata.resource_id,
                )
                .where(
                    LibraryReadableResource.id == resource_id,
                    LibraryReadableResource.book_id == book_id,
                    resource_visibility_predicate(context),
                )
            ).scalar_one_or_none()
            if resource_row is None:
                return None
            resource_state = ResourceMetadataState(
                title=resource_row.title,
                description=resource_row.description,
                publisher=resource_row.publisher,
                published_at=resource_row.published_at,
                language=resource_row.language,
                isbn=resource_row.isbn,
                identifier=resource_row.identifier,
                narrator=resource_row.narrator,
                abridged=resource_row.abridged,
                resource_index=resource_row.resource_index,
            )
        return RecognizedMetadataTargetState(
            book=BookMetadataState(
                title=metadata.title,
                author=metadata.author,
                description=metadata.description,
                series_name=metadata.series_name,
                series_index=metadata.series_index,
                tags=tags,
            ),
            resource=resource_state,
        )

    def apply_changes(
        self,
        *,
        book_id: str,
        resource_id: str | None,
        book_changes: BookMetadataChanges,
        resource_changes: RecognizedResourceChanges,
        tags: tuple[str, ...] | None,
        now: datetime,
    ) -> None:
        metadata = self._db.get(LibraryBookMetadata, book_id)
        if metadata is None:
            raise LookupError(book_id)
        for field, value in book_changes.items():
            setattr(metadata, field, value)
        if "title" in book_changes:
            metadata.normalized_title = normalize_facet_name(metadata.title)
        if "author" in book_changes:
            metadata.normalized_author = (
                normalize_facet_name(metadata.author) if metadata.author else None
            )
        metadata.updated_at = now

        if resource_changes:
            if resource_id is None:
                raise LookupError("resourceId")
            resource_metadata = self._db.get(
                LibraryReadableResourceMetadata, resource_id
            )
            if resource_metadata is None:
                raise LookupError(resource_id)
            for field, value in resource_changes.items():
                setattr(resource_metadata, field, value)
            resource_metadata.updated_at = now

        facet_fields_changed = bool(
            {"author", "series_name"}.intersection(book_changes)
        )
        if tags is not None or facet_fields_changed:
            current_tags = tags
            if current_tags is None:
                current_tags = tuple(
                    str(value)
                    for value in self._db.scalars(
                        select(LibraryFacet.name)
                        .join(
                            LibraryBookFacet,
                            LibraryBookFacet.facet_id == LibraryFacet.id,
                        )
                        .where(
                            LibraryBookFacet.book_id == book_id,
                            LibraryFacet.kind == "TAG",
                        )
                        .order_by(LibraryBookFacet.sort_order, LibraryFacet.id)
                    ).all()
                )
            prepared = prepare_book_facet(
                BookFacetProjection(
                    book_id=book_id,
                    author=metadata.author,
                    tags_source=json.dumps(current_tags, ensure_ascii=False),
                    series_name=metadata.series_name,
                )
            )
            execute_book_facet_write(
                self._db,
                prepare_book_facet_write((prepared,), now=now),
            )

    def load_cover_state(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
        scope: MetadataTargetScope,
    ) -> RecognizedCoverState | None:
        context = _authorization_context(actor)
        if scope is MetadataTargetScope.BOOK:
            row = self._db.execute(
                select(
                    LibraryBook.id,
                    LibraryBookMetadata.cover_path,
                )
                .join(
                    LibraryBookMetadata,
                    LibraryBookMetadata.book_id == LibraryBook.id,
                )
                .where(
                    LibraryBook.id == book_id,
                    book_visibility_predicate(context),
                )
            ).one_or_none()
            return (
                RecognizedCoverState(
                    target_id=str(row[0]),
                    current_cover_path=str(row[1]) if row[1] else None,
                )
                if row is not None
                else None
            )
        if resource_id is None:
            return None
        row = self._db.execute(
            select(
                LibraryReadableResource.id,
                LibraryReadableResourceMetadata.cover_path,
            )
            .join(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .where(
                LibraryReadableResource.id == resource_id,
                LibraryReadableResource.book_id == book_id,
                resource_visibility_predicate(context),
            )
        ).one_or_none()
        return (
            RecognizedCoverState(
                target_id=str(row[0]),
                current_cover_path=str(row[1]) if row[1] else None,
            )
            if row is not None
            else None
        )

    def mark_cover_ready(
        self,
        *,
        state: RecognizedCoverState,
        scope: MetadataTargetScope,
        cover_path: str,
        now: datetime,
    ) -> None:
        if scope is MetadataTargetScope.BOOK:
            metadata = self._db.get(LibraryBookMetadata, state.target_id)
            if metadata is None:
                raise LookupError(state.target_id)
        else:
            metadata = self._db.get(LibraryReadableResourceMetadata, state.target_id)
            if metadata is None:
                raise LookupError(state.target_id)
        metadata.cover_path = cover_path
        metadata.cover_status = "READY"
        metadata.updated_at = now


class _SafeCoverRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: UrlRequest,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> UrlRequest | None:
        validate_cover_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SafeRemoteCoverDownloader(RemoteCoverDownloadPort):
    def download(self, cover_url: str) -> bytes:
        validate_cover_url(cover_url)
        request = UrlRequest(
            cover_url,
            headers={
                "Accept": "image/*,*/*",
                "User-Agent": "Shuku Starship Python",
                "Referer": "https://book.douban.com/",
            },
        )
        opener = build_opener(_SafeCoverRedirectHandler())
        try:
            with opener.open(request, timeout=20) as response:
                content_type = str(response.headers.get("content-type") or "")
                if not content_type.lower().startswith("image/"):
                    raise ValueError("remote cover is not an image")
                content = response.read(_MAX_COVER_BYTES + 1)
        except (HTTPError, OSError, ValueError) as exc:
            raise ValueError("remote cover could not be downloaded") from exc
        if not content or len(content) > _MAX_COVER_BYTES:
            raise ValueError("remote cover exceeds the supported size")
        return content


class FilesystemRecognizedCoverPublication(RecognizedCoverPublicationPort):
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root.resolve()

    def publish(
        self,
        *,
        scope: MetadataTargetScope,
        target_id: str,
        content: bytes,
        previous_stored_path: str | None,
    ) -> PublishedRecognizedCover:
        del previous_stored_path
        if not target_id or Path(target_id).name != target_id:
            raise ValueError("invalid cover target")
        cover_root = self._cover_root(scope)
        cover_root.mkdir(parents=True, exist_ok=True)
        temporary_path = cover_root / f".{target_id}.{uuid4().hex}.part"
        try:
            temporary_path.write_bytes(content)
            with Image.open(temporary_path) as image:
                image_format = str(image.format or "").upper()
                image.verify()
            suffix = _IMAGE_SUFFIXES.get(image_format)
            if suffix is None:
                raise ValueError("unsupported cover image")
        except (
            OSError,
            UnidentifiedImageError,
            ValueError,
            Image.DecompressionBombError,
        ) as exc:
            temporary_path.unlink(missing_ok=True)
            raise ValueError("remote cover could not be validated") from exc
        final_path = cover_root / f"{target_id}{suffix}"
        backup_path = None
        if final_path.exists():
            backup_path = final_path.with_name(
                f".{final_path.name}.{uuid4().hex}.backup"
            )
            os.replace(final_path, backup_path)
        try:
            os.replace(temporary_path, final_path)
        except OSError:
            if backup_path is not None and backup_path.exists():
                os.replace(backup_path, final_path)
            temporary_path.unlink(missing_ok=True)
            raise
        return PublishedRecognizedCover(
            target_id=target_id,
            stored_path=str(final_path.relative_to(self._storage_root)),
            final_path=final_path,
            backup_path=backup_path,
        )

    def revert(self, published: PublishedRecognizedCover) -> None:
        published.final_path.unlink(missing_ok=True)
        if published.backup_path is not None and published.backup_path.exists():
            os.replace(published.backup_path, published.final_path)

    def complete(
        self,
        published: PublishedRecognizedCover,
        *,
        previous_stored_path: str | None,
    ) -> None:
        if published.backup_path is not None:
            published.backup_path.unlink(missing_ok=True)
        if previous_stored_path and previous_stored_path != published.stored_path:
            candidate = (self._storage_root / previous_stored_path).resolve()
            allowed_roots = (
                self._cover_root(MetadataTargetScope.BOOK).resolve(),
                self._cover_root(MetadataTargetScope.RESOURCE).resolve(),
            )
            if any(candidate.is_relative_to(root) for root in allowed_roots):
                candidate.unlink(missing_ok=True)

    def _cover_root(self, scope: MetadataTargetScope) -> Path:
        if scope is MetadataTargetScope.BOOK:
            return self._storage_root / "covers"
        return self._storage_root / "covers" / "resources"


__all__ = [
    "FilesystemRecognizedCoverPublication",
    "SafeRemoteCoverDownloader",
    "SqlAlchemyRecognizedMetadata",
]
