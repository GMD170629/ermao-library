"""Reparse local metadata covers without invoking the import pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.contracts.local_metadata import LocalMetadataSource
from app.modules.library.application.bulk_operations import (
    BulkCoverCommand,
    BulkCoverResult,
    BulkCoverSkipped,
)
from app.modules.library.application.resource_commands import (
    BookNotFoundError,
    LibraryActor,
    LibraryAuthorizationError,
    OperationSummary,
    ResourceMetadataPort,
    ResourceNotFoundError,
)
from app.modules.library.application.resource_cover import (
    ResourceCoverPublicationPort,
    ResourceCoverUnitOfWork,
)
from app.modules.library.application.source_node_commands import (
    SourceNodeCoverPublicationPort,
)

LocalCoverFailureCode = Literal[
    "LOCAL_METADATA_SOURCE_UNAVAILABLE",
    "LOCAL_METADATA_PARSE_FAILED",
    "LOCAL_COVER_NOT_FOUND",
    "LOCAL_COVER_INVALID",
]


@dataclass(frozen=True, slots=True)
class ResourceLocalMetadataSource:
    adapter_id: str
    source_format: str
    root_path: Path
    resource_relative_path: str
    asset_relative_paths: tuple[str, ...]
    local_metadata_priority: tuple[LocalMetadataSource, ...]


@dataclass(frozen=True, slots=True)
class LocalCoverScope:
    book_id: str
    source_node_id: str
    resource_ids: tuple[str, ...]
    is_book_root: bool


@dataclass(frozen=True, slots=True)
class LocalCoverSkipped:
    resource_id: str
    reason: LocalCoverFailureCode


@dataclass(frozen=True, slots=True)
class LocalCoverRegenerationResult:
    target_type: Literal["RESOURCE", "SOURCE_NODE", "BOOK"]
    target_id: str
    updated_resource_ids: tuple[str, ...]
    skipped: tuple[LocalCoverSkipped, ...]
    source_node_updated: bool
    book_updated: bool


class LocalCoverSourcePort(Protocol):
    def load_resource_source(
        self, *, book_id: str, resource_id: str
    ) -> ResourceLocalMetadataSource | None: ...

    def source_scope(
        self, *, book_id: str, source_node_id: str
    ) -> LocalCoverScope | None: ...

    def book_scope(self, *, book_id: str) -> LocalCoverScope | None: ...

    def current_resource_cover_path(self, resource_id: str) -> str | None: ...

    def current_source_cover_path(self, source_node_id: str) -> str | None: ...

    def mark_resource_cover_ready(
        self, *, resource_id: str, cover_path: str
    ) -> None: ...

    def mark_source_cover_ready(
        self,
        *,
        scope: LocalCoverScope,
        cover_path: str,
    ) -> None: ...


class LocalMetadataCoverParserPort(Protocol):
    def extract_cover(
        self, source: ResourceLocalMetadataSource
    ) -> bytes | LocalCoverFailureCode: ...


class BulkCoverRegenerationOperationPort(Protocol):
    def record(
        self,
        *,
        command: BulkCoverCommand,
        updated_book_ids: tuple[str, ...],
        skipped: tuple[BulkCoverSkipped, ...],
        results: tuple[LocalCoverRegenerationResult, ...],
    ) -> OperationSummary: ...


class LocalCoverUnavailableError(Exception):
    def __init__(self, code: LocalCoverFailureCode) -> None:
        super().__init__(code)
        self.code = code


class SourceNodeNotFoundError(Exception):
    """The requested SourceNode is outside the visible Book tree."""


class RegenerateLocalMetadataCovers:
    """Apply only the cover field from the canonical local metadata parser."""

    def __init__(
        self,
        *,
        access: ResourceMetadataPort,
        sources: LocalCoverSourcePort,
        parser: LocalMetadataCoverParserPort,
        resource_covers: ResourceCoverPublicationPort,
        source_covers: SourceNodeCoverPublicationPort,
        unit_of_work: ResourceCoverUnitOfWork,
    ) -> None:
        self._access = access
        self._sources = sources
        self._parser = parser
        self._resource_covers = resource_covers
        self._source_covers = source_covers
        self._unit_of_work = unit_of_work

    def regenerate_resource(
        self, *, actor: LibraryActor, book_id: str, resource_id: str
    ) -> LocalCoverRegenerationResult:
        self._require_book(actor=actor, book_id=book_id)
        if (
            self._access.get_resource_context(
                actor=actor,
                book_id=book_id,
                resource_id=resource_id,
            )
            is None
        ):
            raise ResourceNotFoundError
        self._release_read_transaction()
        attempt = self._regenerate_one(
            book_id=book_id,
            resource_id=resource_id,
        )
        if isinstance(attempt, LocalCoverSkipped):
            raise LocalCoverUnavailableError(attempt.reason)
        return LocalCoverRegenerationResult(
            target_type="RESOURCE",
            target_id=resource_id,
            updated_resource_ids=(resource_id,),
            skipped=(),
            source_node_updated=False,
            book_updated=False,
        )

    def regenerate_source_node(
        self, *, actor: LibraryActor, book_id: str, source_node_id: str
    ) -> LocalCoverRegenerationResult:
        self._require_book(actor=actor, book_id=book_id)
        scope = self._sources.source_scope(
            book_id=book_id,
            source_node_id=source_node_id,
        )
        if scope is None:
            raise SourceNodeNotFoundError
        self._release_read_transaction()
        return self._regenerate_scope(
            target_type="SOURCE_NODE",
            target_id=source_node_id,
            scope=scope,
        )

    def regenerate_book(
        self, *, actor: LibraryActor, book_id: str
    ) -> LocalCoverRegenerationResult:
        self._require_book(actor=actor, book_id=book_id)
        scope = self._sources.book_scope(book_id=book_id)
        if scope is None:
            raise BookNotFoundError
        self._release_read_transaction()
        return self._regenerate_scope(
            target_type="BOOK",
            target_id=book_id,
            scope=scope,
        )

    def _regenerate_scope(
        self,
        *,
        target_type: Literal["SOURCE_NODE", "BOOK"],
        target_id: str,
        scope: LocalCoverScope,
    ) -> LocalCoverRegenerationResult:
        updated: list[str] = []
        skipped: list[LocalCoverSkipped] = []
        first_cover: bytes | None = None
        for resource_id in scope.resource_ids:
            attempt = self._regenerate_one(
                book_id=scope.book_id,
                resource_id=resource_id,
            )
            if isinstance(attempt, LocalCoverSkipped):
                skipped.append(attempt)
                continue
            updated.append(resource_id)
            if first_cover is None:
                first_cover = attempt

        if first_cover is None:
            reason: LocalCoverFailureCode = (
                skipped[0].reason if skipped else "LOCAL_COVER_NOT_FOUND"
            )
            raise LocalCoverUnavailableError(reason)

        self._replace_source_cover(scope=scope, content=first_cover)
        return LocalCoverRegenerationResult(
            target_type=target_type,
            target_id=target_id,
            updated_resource_ids=tuple(updated),
            skipped=tuple(skipped),
            source_node_updated=True,
            book_updated=scope.is_book_root,
        )

    def _regenerate_one(
        self, *, book_id: str, resource_id: str
    ) -> bytes | LocalCoverSkipped:
        source = self._sources.load_resource_source(
            book_id=book_id,
            resource_id=resource_id,
        )
        if source is None:
            self._release_read_transaction()
            return LocalCoverSkipped(
                resource_id=resource_id,
                reason="LOCAL_METADATA_SOURCE_UNAVAILABLE",
            )
        self._release_read_transaction()
        extraction = self._parser.extract_cover(source)
        if isinstance(extraction, str):
            return LocalCoverSkipped(
                resource_id=resource_id,
                reason=extraction,
            )

        previous_path = self._sources.current_resource_cover_path(resource_id)
        self._release_read_transaction()
        try:
            prepared = self._resource_covers.prepare(
                resource_id=resource_id,
                content=extraction,
            )
        except ValueError:
            return LocalCoverSkipped(
                resource_id=resource_id,
                reason="LOCAL_COVER_INVALID",
            )
        published = self._resource_covers.publish(
            prepared,
            previous_stored_path=previous_path,
        )
        try:
            self._sources.mark_resource_cover_ready(
                resource_id=resource_id,
                cover_path=prepared.stored_path,
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            self._resource_covers.revert(published)
            raise
        self._resource_covers.complete(
            published,
            previous_stored_path=previous_path,
        )
        return extraction

    def _replace_source_cover(self, *, scope: LocalCoverScope, content: bytes) -> None:
        previous_path = self._sources.current_source_cover_path(scope.source_node_id)
        self._release_read_transaction()
        prepared = self._source_covers.prepare(
            source_node_id=scope.source_node_id,
            content=content,
        )
        published = self._source_covers.publish(
            prepared,
            previous_stored_path=previous_path,
        )
        try:
            self._sources.mark_source_cover_ready(
                scope=scope,
                cover_path=prepared.stored_path,
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            self._source_covers.revert(published)
            raise
        self._source_covers.complete(
            published,
            previous_stored_path=previous_path,
        )

    def _require_book(self, *, actor: LibraryActor, book_id: str) -> None:
        if not actor.can_manage_system:
            raise LibraryAuthorizationError
        if not self._access.can_access_book(actor=actor, book_id=book_id):
            raise BookNotFoundError

    def _release_read_transaction(self) -> None:
        self._unit_of_work.rollback()


class RegenerateBulkBookCovers:
    """Run Book-root local cover reparsing with per-Resource short commits."""

    def __init__(
        self,
        *,
        covers: RegenerateLocalMetadataCovers,
        operations: BulkCoverRegenerationOperationPort,
        unit_of_work: ResourceCoverUnitOfWork,
    ) -> None:
        self._covers = covers
        self._operations = operations
        self._unit_of_work = unit_of_work

    def execute(self, command: BulkCoverCommand) -> BulkCoverResult:
        actor = LibraryActor(
            user_id=command.context.user_id,
            can_manage_system=command.context.can_manage_system,
            is_admin=command.context.is_admin,
            can_view_manual_imports=command.context.can_view_manual_imports,
            library_ids=command.context.library_ids,
        )
        updated_book_ids: list[str] = []
        skipped: list[BulkCoverSkipped] = []
        results: list[LocalCoverRegenerationResult] = []
        for book_id in command.book_ids:
            try:
                result = self._covers.regenerate_book(
                    actor=actor,
                    book_id=book_id,
                )
            except LocalCoverUnavailableError as exc:
                skipped.append(BulkCoverSkipped(book_id=book_id, reason=exc.code))
                continue
            results.append(result)
            updated_book_ids.append(book_id)

        try:
            operation = self._operations.record(
                command=command,
                updated_book_ids=tuple(updated_book_ids),
                skipped=tuple(skipped),
                results=tuple(results),
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return BulkCoverResult(
            updated=len(updated_book_ids),
            skipped=tuple(skipped),
            operation=operation,
        )


__all__ = [
    "BulkCoverRegenerationOperationPort",
    "LocalCoverFailureCode",
    "LocalCoverRegenerationResult",
    "LocalCoverScope",
    "LocalCoverSkipped",
    "LocalCoverSourcePort",
    "LocalCoverUnavailableError",
    "LocalMetadataCoverParserPort",
    "RegenerateBulkBookCovers",
    "RegenerateLocalMetadataCovers",
    "ResourceLocalMetadataSource",
    "SourceNodeNotFoundError",
]
