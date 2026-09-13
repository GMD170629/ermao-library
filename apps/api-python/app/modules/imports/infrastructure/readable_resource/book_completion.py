"""Book-path completion predicates and durable queue transitions (no commits)."""

from sqlalchemy import (
    and_,
    exists,
    false,
    func,
    insert,
    literal,
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
    LibrarySourceNode,
)
from app.models.common import cuid
from app.modules.imports.application.readable_resource.ports import (
    PreparedBookIdentification,
)

IDENTIFICATION_BATCH_SIZE = 50


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


def _ready_for_identification() -> ColumnElement[bool]:
    active_identification = exists(
        select(LibraryImportTask.id).where(
            LibraryImportTask.source_node_id == LibraryBook.source_node_id,
            LibraryImportTask.kind == "IDENTIFY_BOOK",
            LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
        )
    ).correlate(LibraryBook)
    return and_(
        LibraryBookMetadata.metadata_pending.is_(True),
        ~active_imports_for_book(),
        ~active_identification,
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

    def prepare_ready(
        self, library_id: str | None = None
    ) -> tuple[PreparedBookIdentification, ...]:
        """Read at most one deterministic batch before opening the write scope."""
        query = (
            select(
                LibraryBook.id,
                LibraryBook.library_id,
                LibraryBook.source_node_id,
                LibraryBookMetadata.import_revision,
            )
            .join(LibraryBookMetadata)
            .where(_ready_for_identification())
            .order_by(LibraryBook.id)
            .limit(IDENTIFICATION_BATCH_SIZE)
        )
        if library_id is not None:
            query = query.where(LibraryBook.library_id == library_id)
        return tuple(
            PreparedBookIdentification(
                task_id=cuid(),
                book_id=book_id,
                library_id=book_library_id,
                source_node_id=source_node_id,
                import_revision=import_revision,
            )
            for book_id, book_library_id, source_node_id, import_revision in self._db.execute(
                query
            )
        )

    def persist_ready(self, prepared: tuple[PreparedBookIdentification, ...]) -> int:
        """Persist a bounded batch, rejecting canceled, changed or deleted books."""
        if len(prepared) > IDENTIFICATION_BATCH_SIZE:
            raise ValueError("book identification batch exceeds its limit")
        inserted_task_ids: list[str] = []
        for item in prepared:
            candidates = (
                select(
                    literal(item.task_id),
                    literal("IDENTIFY_BOOK"),
                    LibraryBook.library_id,
                    LibraryBook.source_node_id,
                    literal("QUEUED"),
                    LibraryBookMetadata.import_revision,
                )
                .select_from(LibraryBook)
                .join(LibraryBookMetadata)
                .where(
                    LibraryBook.id == item.book_id,
                    LibraryBook.library_id == item.library_id,
                    LibraryBook.source_node_id == item.source_node_id,
                    LibraryBookMetadata.import_revision == item.import_revision,
                    _ready_for_identification(),
                )
            )
            inserted_id = self._db.scalar(
                insert(LibraryImportTask)
                .from_select(
                    (
                        LibraryImportTask.id,
                        LibraryImportTask.kind,
                        LibraryImportTask.library_id,
                        LibraryImportTask.source_node_id,
                        LibraryImportTask.state,
                        LibraryImportTask.book_metadata_revision,
                    ),
                    candidates,
                )
                .returning(LibraryImportTask.id)
            )
            if inserted_id is not None:
                inserted_task_ids.append(inserted_id)
        if inserted_task_ids:
            self._db.execute(
                update(LibraryBookMetadata)
                .where(
                    LibraryBookMetadata.book_id.in_(
                        select(LibraryBook.id)
                        .join(
                            LibraryImportTask,
                            LibraryImportTask.source_node_id
                            == LibraryBook.source_node_id,
                        )
                        .where(LibraryImportTask.id.in_(inserted_task_ids))
                    )
                )
                .values(metadata_state="QUEUED")
                .execution_options(synchronize_session=False)
            )
        return len(inserted_task_ids)

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
