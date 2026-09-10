"""Book-path completion predicates and durable queue transitions (no commits)."""

from sqlalchemy import and_, exists, false, func, or_, select, true, update
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import ColumnElement, Select

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibrarySourceNode,
)
from app.models.common import cuid


def active_imports_for_book() -> ColumnElement[bool]:
    """Correlated to LibraryBook: scanners count until they stop producing tasks."""
    root = aliased(LibrarySourceNode)
    node = aliased(LibrarySourceNode)
    task = aliased(LibraryImportTask)
    under_root = or_(
        node.id == root.id,
        and_(
            root.physical_kind == "DIRECTORY",
            func.instr(node.relative_path, root.relative_path + "/") == 1,
        ),
    )
    ancestor_scan = or_(
        node.relative_path == "",
        func.instr(root.relative_path, node.relative_path + "/") == 1,
    )
    return exists(
        select(task.id)
        .select_from(task)
        .join(root, root.id == LibraryBook.source_node_id)
        .outerjoin(node, node.id == task.source_node_id)
        .where(
            task.library_id == LibraryBook.library_id,
            task.state.in_(("QUEUED", "RUNNING")),
            or_(
                task.kind == "SCAN_LIBRARY",
                and_(task.kind == "IMPORT_ASSET", under_root),
                and_(task.kind == "CONTINUE_SOURCE", or_(under_root, ancestor_scan)),
            ),
        )
        .correlate(LibraryBook)
    )


class BookImportCompletion:
    def __init__(self, session: Session) -> None:
        self._db = session

    def affected_books(self, task: LibraryImportTask) -> Select[tuple[str]]:
        query = select(LibraryBook.id).where(LibraryBook.library_id == task.library_id)
        if task.kind == "SCAN_LIBRARY":
            return query
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
        if task.kind == "IDENTIFY_BOOK":
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

    def enqueue_ready(self, library_id: str | None = None) -> None:
        self._db.flush()
        active_identification = exists(
            select(LibraryImportTask.id).where(
                LibraryImportTask.source_node_id == LibraryBook.source_node_id,
                LibraryImportTask.kind == "IDENTIFY_BOOK",
                LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
            )
        )
        query = (
            select(LibraryBook, LibraryBookMetadata)
            .join(LibraryBookMetadata)
            .where(
                LibraryBookMetadata.metadata_pending.is_(True),
                ~active_imports_for_book(),
                ~active_identification,
            )
        )
        if library_id is not None:
            query = query.where(LibraryBook.library_id == library_id)
        for book, metadata in self._db.execute(query):
            self._db.add(
                LibraryImportTask(
                    id=cuid(),
                    kind="IDENTIFY_BOOK",
                    library_id=book.library_id,
                    source_node_id=book.source_node_id,
                    state="QUEUED",
                    book_metadata_revision=metadata.import_revision,
                )
            )
            metadata.metadata_state = "QUEUED"
        self._db.flush()

    def finished(self, task: LibraryImportTask) -> None:
        if task.kind == "IDENTIFY_BOOK":
            metadata = self._db.scalar(
                select(LibraryBookMetadata)
                .join(LibraryBook)
                .where(LibraryBook.source_node_id == task.source_node_id)
            )
            if (
                metadata is not None
                and task.state == "FAILED"
                and metadata.import_revision == task.book_metadata_revision
            ):
                metadata.metadata_state = "FAILED"
                metadata.metadata_pending = False
        self.enqueue_ready(task.library_id)
