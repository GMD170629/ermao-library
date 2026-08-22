"""Application use cases for Book-scoped SourceNode presentation metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_SOURCE_NODE_COVER_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SourceNodeMetadataChanges:
    title: str
    description: str | None
    cover_path: str | None = None
    replace_cover: bool = False


@dataclass(frozen=True, slots=True)
class SourceNodePresentationState:
    cover_path: str | None


@dataclass(frozen=True, slots=True)
class PreparedSourceNodeCover:
    temporary_path: Path
    final_path: Path
    stored_path: str


@dataclass(frozen=True, slots=True)
class PublishedSourceNodeCover:
    prepared: PreparedSourceNodeCover
    backup_path: Path | None


class SourceNodeMetadataPort(Protocol):
    def get_state(
        self, *, book_id: str, source_node_id: str
    ) -> SourceNodePresentationState | None: ...

    def update_metadata(
        self,
        *,
        book_id: str,
        source_node_id: str,
        changes: SourceNodeMetadataChanges,
    ) -> bool: ...


class SourceNodeCoverPublicationPort(Protocol):
    def prepare(
        self, *, source_node_id: str, content: bytes
    ) -> PreparedSourceNodeCover: ...

    def publish(
        self,
        prepared: PreparedSourceNodeCover,
        *,
        previous_stored_path: str | None,
    ) -> PublishedSourceNodeCover: ...

    def revert(self, published: PublishedSourceNodeCover) -> None: ...

    def complete(
        self,
        published: PublishedSourceNodeCover,
        *,
        previous_stored_path: str | None,
    ) -> None: ...

    def remove(self, stored_path: str) -> None: ...


class SourceNodeMetadataUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UpdateSourceNodeMetadata:
    """Update one directory label while enforcing its owning Book subtree."""

    def __init__(
        self,
        port: SourceNodeMetadataPort,
        unit_of_work: SourceNodeMetadataUnitOfWork,
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work

    def execute(
        self,
        *,
        book_id: str,
        source_node_id: str,
        changes: SourceNodeMetadataChanges,
    ) -> bool:
        title = changes.title.strip()
        if not title:
            raise ValueError("title must not be empty")
        try:
            updated = self._port.update_metadata(
                book_id=book_id,
                source_node_id=source_node_id,
                changes=SourceNodeMetadataChanges(
                    title=title,
                    description=(changes.description or "").strip() or None,
                ),
            )
            if not updated:
                self._unit_of_work.rollback()
                return False
            self._unit_of_work.commit()
            return True
        except Exception:
            self._unit_of_work.rollback()
            raise


class UpdateSourceNodePresentation:
    """Save directory text and cover as one recoverable user intention."""

    def __init__(
        self,
        port: SourceNodeMetadataPort,
        covers: SourceNodeCoverPublicationPort,
        unit_of_work: SourceNodeMetadataUnitOfWork,
    ) -> None:
        self._port = port
        self._covers = covers
        self._unit_of_work = unit_of_work

    def execute(
        self,
        *,
        book_id: str,
        source_node_id: str,
        title: str,
        description: str | None,
        cover_content: bytes | None,
        remove_cover: bool,
    ) -> bool:
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("title must not be empty")
        if cover_content is not None and remove_cover:
            raise ValueError("cover cannot be replaced and removed together")
        state = self._port.get_state(
            book_id=book_id,
            source_node_id=source_node_id,
        )
        if state is None:
            return False

        prepared = (
            self._covers.prepare(
                source_node_id=source_node_id,
                content=cover_content,
            )
            if cover_content is not None
            else None
        )
        published = (
            self._covers.publish(
                prepared,
                previous_stored_path=state.cover_path,
            )
            if prepared is not None
            else None
        )
        replace_cover = prepared is not None or remove_cover
        next_cover_path = prepared.stored_path if prepared is not None else None
        try:
            updated = self._port.update_metadata(
                book_id=book_id,
                source_node_id=source_node_id,
                changes=SourceNodeMetadataChanges(
                    title=normalized_title,
                    description=(description or "").strip() or None,
                    cover_path=next_cover_path,
                    replace_cover=replace_cover,
                ),
            )
            if not updated:
                self._unit_of_work.rollback()
                if published is not None:
                    self._covers.revert(published)
                return False
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            if published is not None:
                self._covers.revert(published)
            raise

        if published is not None:
            self._covers.complete(
                published,
                previous_stored_path=state.cover_path,
            )
        elif remove_cover and state.cover_path:
            self._covers.remove(state.cover_path)
        return True


__all__ = [
    "MAX_SOURCE_NODE_COVER_BYTES",
    "PreparedSourceNodeCover",
    "PublishedSourceNodeCover",
    "SourceNodeCoverPublicationPort",
    "SourceNodeMetadataChanges",
    "SourceNodeMetadataPort",
    "SourceNodeMetadataUnitOfWork",
    "SourceNodePresentationState",
    "UpdateSourceNodeMetadata",
    "UpdateSourceNodePresentation",
]
