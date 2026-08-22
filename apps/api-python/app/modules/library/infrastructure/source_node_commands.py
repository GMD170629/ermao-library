"""SQLAlchemy adapter for Book-scoped SourceNode metadata mutations."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import (
    Library,
    LibraryBook,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.models.common import db_timestamp
from app.modules.library.application.source_node_commands import (
    SourceNodeMetadataChanges,
    SourceNodeMetadataPort,
    SourceNodePresentationState,
)
from app.modules.metadata.public import (
    metadata_writeback_enabled,
    persist_metadata_writeback_intents,
    prepare_source_node_metadata_writeback_intent,
)


class SqlAlchemySourceNodeMetadata(SourceNodeMetadataPort):
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_state(
        self, *, book_id: str, source_node_id: str
    ) -> SourceNodePresentationState | None:
        scoped = self._scoped_directory(book_id=book_id, source_node_id=source_node_id)
        if scoped is None:
            return None
        node, _book, _library = scoped
        metadata = self._db.get(LibrarySourceNodeMetadata, node.id)
        return SourceNodePresentationState(
            cover_path=metadata.cover_path if metadata is not None else None
        )

    def update_metadata(
        self,
        *,
        book_id: str,
        source_node_id: str,
        changes: SourceNodeMetadataChanges,
    ) -> bool:
        scoped = self._scoped_directory(book_id=book_id, source_node_id=source_node_id)
        if scoped is None:
            return False
        node, book, library = scoped
        metadata = self._db.get(LibrarySourceNodeMetadata, node.id)
        if metadata is None:
            metadata = LibrarySourceNodeMetadata(source_node_id=node.id)
            self._db.add(metadata)
        metadata.title = changes.title
        metadata.description = changes.description
        if changes.replace_cover:
            metadata.cover_path = changes.cover_path
            metadata.cover_status = "READY" if changes.cover_path else "PENDING"
        self._db.flush()
        if metadata_writeback_enabled(self._db):
            source_directory = self._source_directory(library=library, node=node)
            intent = prepare_source_node_metadata_writeback_intent(
                book_id=book.id,
                source_node_id=node.id,
                source_directory=str(source_directory),
                title=metadata.title or node.name,
                description=metadata.description,
                cover_path=metadata.cover_path,
                source_revision=metadata.updated_at or db_timestamp(),
            )
            persist_metadata_writeback_intents(self._db, (intent,))
        return True

    def _scoped_directory(
        self, *, book_id: str, source_node_id: str
    ) -> tuple[LibrarySourceNode, LibraryBook, Library] | None:
        book = self._db.get(LibraryBook, book_id)
        node = self._db.get(LibrarySourceNode, source_node_id)
        if book is None or node is None:
            return None
        root = self._db.get(LibrarySourceNode, book.source_node_id)
        library = self._db.get(Library, book.library_id)
        if root is None or library is None:
            return None
        root_relative = root.relative_path.rstrip("/")
        inside_root = (
            node.id == root.id
            or not root_relative
            or node.relative_path.startswith(f"{root_relative}/")
        )
        if (
            node.library_id != root.library_id
            or node.physical_kind != "DIRECTORY"
            or not inside_root
        ):
            return None
        return node, book, library

    @staticmethod
    def _source_directory(*, library: Library, node: LibrarySourceNode) -> Path:
        root = Path(library.root_path).expanduser().resolve()
        target = (root / node.relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("source node path escapes its library root") from exc
        return target


__all__ = ["SqlAlchemySourceNodeMetadata"]
