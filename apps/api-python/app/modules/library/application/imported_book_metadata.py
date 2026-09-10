"""Identify a completed Book without re-running its asset imports."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.contracts.local_metadata import LocalMetadataSource
from app.contracts.local_metadata_snapshot import LocalMetadataObservation
from app.contracts.publication_metadata import PublicationMetadata
from app.modules.library.application.resource_cover import ResourceCoverUnitOfWork
from app.modules.library.application.source_node_commands import (
    SourceNodeCoverPublicationPort,
)


@dataclass(frozen=True, slots=True)
class ImportedBookSnapshot:
    book_id: str
    source_node_id: str
    revision: int
    protected_fields: str
    root_path: str
    relative_path: str
    is_directory: bool
    priority: tuple[LocalMetadataSource, ...]
    observations: tuple[LocalMetadataObservation, ...]
    resource_cover_path: str | None
    previous_cover_path: str | None
    cover_protected: bool
    metadata_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IdentifiedBookMetadata:
    metadata: PublicationMetadata
    cover: bytes | None


class ImportedBookMetadataPort(Protocol):
    def load(self, source_node_id: str) -> ImportedBookSnapshot | None: ...
    def inspect(self, snapshot: ImportedBookSnapshot) -> IdentifiedBookMetadata: ...
    def still_current(self, snapshot: ImportedBookSnapshot) -> bool: ...
    def apply(
        self,
        snapshot: ImportedBookSnapshot,
        result: IdentifiedBookMetadata,
        cover_path: str | None,
    ) -> None: ...


class IdentifyImportedBook:
    def __init__(
        self,
        repository: ImportedBookMetadataPort,
        covers: SourceNodeCoverPublicationPort,
        unit_of_work: ResourceCoverUnitOfWork,
    ) -> None:
        self._repository = repository
        self._covers = covers
        self._uow = unit_of_work

    def execute(self, source_node_id: str) -> str:
        snapshot = self._repository.load(source_node_id)
        self._uow.commit()
        if snapshot is None:
            return "stale"
        result = self._repository.inspect(snapshot)
        prepared = (
            self._covers.prepare(source_node_id=source_node_id, content=result.cover)
            if result.cover and not snapshot.cover_protected
            else None
        )
        published = None
        try:
            if not self._repository.still_current(snapshot):
                self._uow.rollback()
                return "stale"
            if prepared is not None:
                published = self._covers.publish(
                    prepared, previous_stored_path=snapshot.previous_cover_path
                )
            self._repository.apply(
                snapshot, result, prepared.stored_path if prepared else None
            )
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            if published is not None:
                self._covers.revert(published)
            raise
        finally:
            if prepared is not None and published is None:
                self._covers.discard(prepared)
        if published is not None:
            self._covers.complete(
                published, previous_stored_path=snapshot.previous_cover_path
            )
        return "identified"
