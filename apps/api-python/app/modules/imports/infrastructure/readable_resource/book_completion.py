"""Book-path completion predicates and durable queue transitions (no commits)."""

from sqlalchemy import (
    and_,
    false,
    func,
    or_,
    select,
    true,
    update,
)
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import ColumnElement, Select

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibrarySourceNode,
)
from app.modules.imports.infrastructure.readable_resource.scan_gating import (
    active_imports_for_anchor,
)


def active_imports_for_book() -> ColumnElement[bool]:
    """Correlated to LibraryBook: scanners count until they stop producing tasks."""
    root = aliased(LibrarySourceNode)
    return active_imports_for_anchor(
        root,
        library_id=LibraryBook.library_id,
        anchor_id=LibraryBook.source_node_id,
    ).correlate(LibraryBook)


class BookImportCompletion:
    def __init__(self, session: Session) -> None:
        self._db = session

    def affected_books(self, task: LibraryImportTask) -> Select[tuple[str]]:
        query = select(LibraryBook.id).where(LibraryBook.library_id == task.library_id)
        if task.kind == "SCAN_LIBRARY":
            return query
        if task.kind == "IMPORT_BOOK" and task.book_id:
            return query.where(LibraryBook.id == task.book_id)
        if task.kind in {"IMPORT_RESOURCE", "IMPORT_ASSET"} and task.resource_id:
            return query.where(
                LibraryBook.id.in_(
                    select(LibraryReadableResource.book_id).where(
                        LibraryReadableResource.id == task.resource_id,
                        LibraryReadableResource.library_id == task.library_id,
                    )
                )
            )
        root = aliased(LibrarySourceNode)
        node = self._db.get(LibrarySourceNode, task.source_node_id)
        if node is None:
            return query.where(false())
        query = query.join(root, root.id == LibraryBook.source_node_id)
        # Python-owned prefixes use autoescape, SQL-owned paths use instr rather
        # than LIKE so literal '%' and '_' never broaden an import boundary.
        under = or_(
            root.id == node.id,
            and_(
                root.physical_kind == "DIRECTORY",
                func.instr(node.relative_path, root.relative_path + "/") == 1,
            ),
        )
        if task.kind == "CONTINUE_SOURCE":
            under = or_(
                under,
                root.relative_path.startswith(
                    node.relative_path.rstrip("/") + "/", autoescape=True
                ),
                true() if node.relative_path == "" else false(),
            )
        return query.where(under)

    def dirty(self, task: LibraryImportTask) -> None:
        if task.kind in {"IDENTIFY_BOOK", "SCAN_LIBRARY", "CONTINUE_SOURCE"}:
            return
        self._db.execute(
            update(LibraryBookMetadata)
            .where(LibraryBookMetadata.book_id.in_(self.affected_books(task)))
            .values(
                import_revision=LibraryBookMetadata.import_revision + 1,
                metadata_pending=True,
                metadata_state="WAITING_IMPORT",
            )
        )

    def cancel(self, task: LibraryImportTask) -> None:
        self._db.execute(
            update(LibraryBookMetadata)
            .where(LibraryBookMetadata.book_id.in_(self.affected_books(task)))
            .values(
                import_revision=LibraryBookMetadata.import_revision + 1,
                metadata_pending=False,
                metadata_state="WAITING_IMPORT",
            )
        )

    def finished(self, task: LibraryImportTask) -> None:
        if task.kind == "IDENTIFY_BOOK" and task.state == "FAILED":
            self._db.execute(
                update(LibraryBookMetadata)
                .where(LibraryBook.source_node_id == task.source_node_id)
                .where(
                    LibraryBookMetadata.book_id == LibraryBook.id,
                    LibraryBookMetadata.import_revision == task.book_metadata_revision,
                )
                .values(metadata_state="FAILED", metadata_pending=False)
                .execution_options(synchronize_session=False)
            )
