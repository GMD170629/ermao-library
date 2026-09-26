"""ORM and filesystem adapters for manually selected recognized metadata."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import ssl
from datetime import datetime
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    build_opener,
)
from urllib.request import Request as UrlRequest
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.recognized_metadata_fields import (
    PROVIDER_METADATA_FIELDS,
    recognized_field_name,
)
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
from app.modules.library.application.metadata_patches import (
    ApplyMetadataPatches,
    MetadataPatchActor,
    MetadataSnapshot,
)
from app.modules.library.application.recognized_metadata import (
    BookMetadataChanges,
    BookMetadataState,
    MetadataTargetScope,
    PublishedRecognizedCover,
    RecognizedCoverMetadataPort,
    RecognizedCoverPublicationPort,
    RecognizedCoverState,
    RecognizedMetadataCandidate,
    RecognizedMetadataField,
    RecognizedMetadataPort,
    RecognizedMetadataTargetState,
    RecognizedResourceChanges,
    RemoteCoverDownloadPort,
    ResourceMetadataState,
)
from app.modules.library.application.resource_commands import LibraryActor
from app.modules.library.domain.metadata_patch import (
    MetadataChange,
    MetadataPatchError,
    MetadataTarget,
    MetadataValue,
)
from app.modules.library.infrastructure.metadata_patches import (
    SqlAlchemyMetadataPatches,
)
from app.modules.metadata.public import (
    candidate_evidence,
    complete_recognition_record,
    confirm_candidate,
    load_recognition_context,
    propose_fields,
    recognition_fingerprint,
    recognition_record,
)

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
        self._patches = SqlAlchemyMetadataPatches(db)
        self._snapshots: dict[str, MetadataSnapshot] = {}
        self._actor: LibraryActor | None = None
        self._library_ids: frozenset[str] = frozenset()
        self._pending_record: tuple[str, str, str | None, dict[str, Any], list[str]] | None = None

    def resolve_selection(self, *, book_id: str, resource_id: str | None, record_id: str,
                          candidate: RecognizedMetadataCandidate, fields: tuple[RecognizedMetadataField, ...]) -> tuple[RecognizedMetadataCandidate, bool]:
        raw = recognition_record(self._db, book_id, record_id)
        if raw is None:
            raise MetadataPatchError("RESOURCE_NOT_FOUND")
        saved = raw["recognition"]
        kind, target = ("resource", resource_id) if resource_id else ("book", book_id)
        if saved.get("targetType") != kind or saved.get("targetId") != target or saved.get("ignored"):
            raise MetadataPatchError("CONFLICT")
        selection = sorted(field.value for field in fields)
        if saved.get("humanConfirmed"):
            selected = raw.get("selected") or {}
            if selected.get("id") == candidate.id and selected.get("source") == candidate.source and sorted(saved.get("appliedSelection", [])) == selection:
                return candidate, True
            raise MetadataPatchError("CONFLICT")
        context = load_recognition_context(self._db, book_id=book_id, resource_id=resource_id, source_node_id=saved.get("sourceNodeId"))
        if context is None or recognition_fingerprint(context) != saved.get("fingerprint"):
            raise MetadataPatchError("CONFLICT")
        value = next(({**item, "source": attempt["provider"]} for attempt in raw.get("attempted", [])[:8]
            if attempt.get("provider") == candidate.source
            for item in attempt.get("candidates", attempt.get("exactCandidates", []))[:10]
            if str(item.get("id")) == candidate.id), None)
        if value is None:
            raise MetadataPatchError("INVALID_CANDIDATE")
        decision = confirm_candidate(context, candidate_evidence(candidate.source, value))
        proposals = propose_fields(context, candidate.source, value, decision)
        allowed = {item.field for item in proposals}
        if any(field.value.split(".")[0] + "." + recognized_field_name(field.value.split(".")[1]) not in allowed for field in fields):
            raise MetadataPatchError("INVALID_FIELD")
        values: dict[str, Any] = {"id": candidate.id, "source": candidate.source}
        for external, name in PROVIDER_METADATA_FIELDS.items():
            item = value.get(external)
            if name == "cover_ref":
                name = "cover_url"
            if name == "published_at":
                item = datetime.fromisoformat(item) if isinstance(item, str) and re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T)", item) else None
            if name == "tags":
                item = tuple(item) if isinstance(item, list) else ()
            values[name] = item
        self._pending_record = (book_id, record_id, resource_id, value, selection)
        return RecognizedMetadataCandidate(**values), False

    def _stage_record(self, changed: bool) -> None:
        if self._pending_record:
            book_id, record_id, resource_id, candidate, fields = self._pending_record
            self._db.flush()
            context = load_recognition_context(self._db, book_id=book_id, resource_id=resource_id)
            if context is None:
                raise MetadataPatchError("CONFLICT")
            complete_recognition_record(self._db, book_id, record_id, candidate, fields, context, changed=changed)

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
        self._actor = actor
        self._library_ids = frozenset({book.library_id})
        self._snapshots = {}
        for kind, target in (("book", book_id), ("resource", resource_id)):
            if target is not None:
                snapshot = self._patches.snapshot(cast(MetadataTarget, kind), target, self._library_ids)
                if snapshot is not None:
                    self._snapshots[kind] = snapshot
        return RecognizedMetadataTargetState(
            book_revision=self._snapshots["book"].revision,
            resource_revision=self._snapshots["resource"].revision if "resource" in self._snapshots else None,
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
        del now
        if self._actor is None:
            raise MetadataPatchError("ACTOR_REQUIRED")
        changes = []
        book_values = {key: cast(MetadataValue, value) for key, value in book_changes.items()}
        if tags is not None:
            book_values["tags"] = tags
        resource_values: dict[str, MetadataValue] = {
            key: value.isoformat() if isinstance(value, datetime) else cast(MetadataValue, value)
            for key, value in resource_changes.items()
        }
        for kind, target, values in (("book", book_id, book_values), ("resource", resource_id, resource_values)):
            if values and target:
                before = self._snapshots.get(kind)
                if before is None or before.target_id != target or before.book_id != book_id:
                    raise MetadataPatchError("RESOURCE_NOT_FOUND")
                changes.append(MetadataChange(before.target_type, target, before.revision, "patch", values,
                                              provenance={key: "MANUAL_RECOGNITION" for key in values}))
        if changes:
            outcome = ApplyMetadataPatches(self._patches, self._db).stage(
                MetadataPatchActor(self._actor.user_id, None, self._library_ids, True, True, False),
                tuple(changes), skip_unchanged=True)
            self._stage_record(bool(outcome["updated"]))

    def load_cover_state(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
        scope: MetadataTargetScope,
    ) -> RecognizedCoverState | None:
        target = self.load_target(actor=actor, book_id=book_id, resource_id=resource_id)
        if target is None:
            return None
        context = _authorization_context(actor)
        if scope is MetadataTargetScope.BOOK:
            row = self._db.execute(
                select(
                    LibraryBook.id,
                    LibraryBookMetadata.cover_path,
                    LibraryBookMetadata.updated_at,
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
                    updated_at=row[2],
                    revision=self._snapshots[scope.value].revision,
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
                LibraryReadableResourceMetadata.updated_at,
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
                updated_at=row[2],
                    revision=self._snapshots[scope.value].revision,
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
        del now
        if self._actor is None:
            raise MetadataPatchError("ACTOR_REQUIRED")
        kind = cast(MetadataTarget, scope.value)
        before = self._snapshots.get(kind)
        if before is None or before.target_id != state.target_id:
            raise MetadataPatchError("RESOURCE_NOT_FOUND")
        reference = "recognition:" + uuid4().hex
        port = SqlAlchemyMetadataPatches(self._db, prepared_covers={(kind, state.target_id): (reference, cover_path)})
        ApplyMetadataPatches(port, self._db).stage(
            MetadataPatchActor(self._actor.user_id, None, self._library_ids, True, True, False),
            (MetadataChange(kind, state.target_id, before.revision, "patch", {"cover_ref": reference},
                            provenance={"cover_ref": "MANUAL_RECOGNITION"}),), skip_unchanged=True)
        self._stage_record(True)


def _public_socket(host: str, port: int) -> socket.socket:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("cover address must be public")
    family, socktype, proto, _, address = addresses[0]
    connection = socket.socket(family, socktype, proto)
    try:
        connection.settimeout(20)
        connection.connect(address)
    except BaseException:
        connection.close()
        raise
    return connection


class _PublicHTTPConnection(HTTPConnection):
    def connect(self) -> None:
        self.sock = _public_socket(self.host, self.port)


class _PublicHTTPSConnection(HTTPSConnection):
    def connect(self) -> None:
        raw = _public_socket(self.host, self.port)
        try:
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class _CoverHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(_PublicHTTPConnection, request)


class _CoverHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_PublicHTTPSConnection, request)


class _NoCoverRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("cover redirects are not permitted")


class SafeRemoteCoverDownloader(RemoteCoverDownloadPort):
    def download(self, cover_url: str) -> bytes:
        url = urlsplit(cover_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.port not in {None, 80, 443}:
            raise ValueError("invalid remote cover URL")
        request = UrlRequest(
            cover_url,
            headers={
                "Accept": "image/*,*/*",
                "User-Agent": "Shuku Starship Python",
                "Referer": "https://book.douban.com/",
            },
        )
        opener = build_opener(ProxyHandler({}), _CoverHTTPHandler(), _CoverHTTPSHandler(), _NoCoverRedirect())
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
            stored_path=final_path.relative_to(self._storage_root).as_posix(),
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
