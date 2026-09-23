"""Map unfinished legacy import work to one bounded task per existing Book.

The old task rows remain historical records. Keyset pages bound upgrade memory;
the old-row mapping and the Book work payload make re-entry idempotent if an
interrupted SQLite migration is retried. Scans and durable scan gaps are intact.
"""

from __future__ import annotations

import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0031_book_import_task_backfill"
down_revision = "0030_book_import_task_shape"
branch_labels = None
depends_on = None

_PAGE_SIZE = 200
_MAX_RESOURCE_IDS = 128
_LEGACY_KINDS = ("IMPORT_RESOURCE", "IMPORT_ASSET", "IDENTIFY_BOOK")


def _empty_work() -> dict[str, object]:
    return {"scanScopes": [], "resourceIds": [], "identify": False, "reasons": []}


def _empty_state() -> dict[str, dict[str, object]]:
    return {"active": _empty_work(), "pending": _empty_work()}


def _decode_state(raw: str) -> dict[str, dict[str, object]]:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"active", "pending"}:
        raise ValueError("INVALID_BOOK_WORK_DURING_UPGRADE")
    for work in value.values():
        if not isinstance(work, dict) or set(work) != {
            "scanScopes",
            "resourceIds",
            "identify",
            "reasons",
        }:
            raise TypeError("INVALID_BOOK_WORK_DURING_UPGRADE")
        if not isinstance(work["resourceIds"], list) or not isinstance(
            work["reasons"], list
        ):
            raise TypeError("INVALID_BOOK_WORK_DURING_UPGRADE")
    return value


def _merge_pending(
    state: dict[str, dict[str, object]],
    *,
    resource_id: str | None,
    identify: bool,
    reason: str,
) -> bool:
    pending = state["pending"]
    active = state["active"]
    changed = False
    if resource_id is not None:
        resources = pending["resourceIds"]
        if not isinstance(resources, list):
            raise TypeError("INVALID_BOOK_WORK_DURING_UPGRADE")
        if pending["scanScopes"] is not None and resource_id not in resources:
            resources.append(resource_id)
            resources.sort()
            changed = True
            if len(resources) > _MAX_RESOURCE_IDS:
                # A full scan of this Book rediscovers changed Resource versions.
                pending["scanScopes"] = None
                pending["resourceIds"] = []
    if identify and not pending["identify"] and not active["identify"]:
        pending["identify"] = True
        changed = True
    reasons = pending["reasons"]
    if not isinstance(reasons, list):
        raise TypeError("INVALID_BOOK_WORK_DURING_UPGRADE")
    if reason not in reasons and reasons != ["MULTIPLE_REQUESTS"]:
        reasons.append(reason)
        reasons.sort()
        changed = True
        if len(reasons) > 16:
            pending["reasons"] = ["MULTIPLE_REQUESTS"]
    return changed


def _phase(state: dict[str, dict[str, object]]) -> str:
    work = state["pending"]
    if work["scanScopes"] is None or work["scanScopes"]:
        return "SCAN"
    if work["resourceIds"]:
        return "RESOURCES"
    return "IDENTIFY"


def _put_work(
    bind,
    tasks,
    *,
    book_id: str,
    library_id: str,
    source_node_id: str,
    resource_id: str | None,
    identify: bool,
    created_at: int,
    source_state: str,
    reason: str,
    promote_failed: bool = True,
) -> str:
    current = bind.execute(
        sa.select(
            tasks.c.id, tasks.c.state, tasks.c.bookWork, tasks.c.requestVersion
        ).where(tasks.c.kind == "IMPORT_BOOK", tasks.c.bookId == book_id)
    ).first()
    if current is None:
        state = _empty_state()
        _merge_pending(state, resource_id=resource_id, identify=identify, reason=reason)
        task_id = uuid4().hex
        bind.execute(
            tasks.insert().values(
                id=task_id,
                kind="IMPORT_BOOK",
                libraryId=library_id,
                sourceNodeId=source_node_id,
                bookId=book_id,
                state="FAILED" if source_state == "FAILED" else "QUEUED",
                phase=_phase(state),
                bookWork=json.dumps(state, separators=(",", ":")),
                requestVersion=1,
                retryCount=0,
                nextAttemptAt=created_at if source_state != "FAILED" else None,
                errorSummary="LEGACY_IMPORT_FAILED"
                if source_state == "FAILED"
                else None,
                createdAt=created_at,
            )
        )
        return task_id

    state = _decode_state(current.bookWork)
    changed = _merge_pending(
        state, resource_id=resource_id, identify=identify, reason=reason
    )
    promote = source_state != "FAILED" and (
        current.state == "SUCCEEDED" or (current.state == "FAILED" and promote_failed)
    )
    if changed or promote:
        values = {
            "bookWork": json.dumps(state, separators=(",", ":")),
            "requestVersion": current.requestVersion + int(changed),
        }
        if promote:
            values.update(
                state="QUEUED",
                phase=_phase(state),
                nextAttemptAt=created_at,
                errorSummary=None,
                finishedAt=None,
                retryCount=0,
            )
        bind.execute(tasks.update().where(tasks.c.id == current.id).values(**values))
    return current.id


def backfill_book_tasks(bind) -> None:
    metadata = sa.MetaData()
    tasks = sa.Table("LibraryImportTask", metadata, autoload_with=bind)
    resources = sa.Table("LibraryReadableResource", metadata, autoload_with=bind)
    books = sa.Table("LibraryBook", metadata, autoload_with=bind)
    book_metadata = sa.Table("LibraryBookMetadata", metadata, autoload_with=bind)

    cursor = ""
    while True:
        rows = bind.execute(
            sa.select(
                tasks.c.id,
                tasks.c.kind,
                tasks.c.state,
                tasks.c.libraryId,
                tasks.c.sourceNodeId,
                tasks.c.resourceId,
                tasks.c.createdAt,
            )
            .where(
                tasks.c.id > cursor,
                tasks.c.kind.in_(_LEGACY_KINDS),
                tasks.c.state != "SUCCEEDED",
                tasks.c.supersededByTaskId.is_(None),
            )
            .order_by(tasks.c.id)
            .limit(_PAGE_SIZE)
        ).all()
        if not rows:
            break
        cursor = rows[-1].id
        resource_ids = {row.resourceId for row in rows if row.resourceId is not None}
        resource_book = (
            {
                row.id: (row.bookId, row.libraryId)
                for row in bind.execute(
                    sa.select(
                        resources.c.id, resources.c.bookId, resources.c.libraryId
                    ).where(resources.c.id.in_(resource_ids))
                )
            }
            if resource_ids
            else {}
        )
        source_ids = {
            row.sourceNodeId
            for row in rows
            if row.kind == "IDENTIFY_BOOK" and row.sourceNodeId is not None
        }
        node_book = (
            {
                (row.sourceNodeId, row.libraryId): row.id
                for row in bind.execute(
                    sa.select(
                        books.c.id, books.c.sourceNodeId, books.c.libraryId
                    ).where(books.c.sourceNodeId.in_(source_ids))
                )
            }
            if source_ids
            else {}
        )
        book_ids = {book_id for book_id, _ in resource_book.values()} | set(
            node_book.values()
        )
        book_rows = (
            {
                row.id: row
                for row in bind.execute(
                    sa.select(
                        books.c.id, books.c.libraryId, books.c.sourceNodeId
                    ).where(books.c.id.in_(book_ids))
                )
            }
            if book_ids
            else {}
        )
        for row in rows:
            if row.kind == "IDENTIFY_BOOK":
                book_id = node_book.get((row.sourceNodeId, row.libraryId))
            else:
                owner = resource_book.get(row.resourceId)
                book_id = owner[0] if owner and owner[1] == row.libraryId else None
            book = book_rows.get(book_id)
            if book is None or book.libraryId != row.libraryId:
                # A source node can outlive its Book. Keep the old failure
                # visible and stop an unmappable queued task from being claimed.
                if row.state != "FAILED":
                    bind.execute(
                        tasks.update()
                        .where(tasks.c.id == row.id)
                        .values(
                            state="FAILED",
                            errorSummary="BOOK_IMPORT_UPGRADE_UNRESOLVED",
                        )
                    )
                continue
            task_id = _put_work(
                bind,
                tasks,
                book_id=book.id,
                library_id=book.libraryId,
                source_node_id=book.sourceNodeId,
                resource_id=row.resourceId if row.kind != "IDENTIFY_BOOK" else None,
                identify=row.kind == "IDENTIFY_BOOK",
                created_at=row.createdAt,
                source_state=row.state,
                reason="UPGRADED_TASK",
            )
            bind.execute(
                tasks.update()
                .where(tasks.c.id == row.id, tasks.c.supersededByTaskId.is_(None))
                .values(supersededByTaskId=task_id)
            )

    cursor = ""
    while True:
        rows = bind.execute(
            sa.select(
                books.c.id,
                books.c.libraryId,
                books.c.sourceNodeId,
                book_metadata.c.createdAt,
            )
            .join(book_metadata, book_metadata.c.bookId == books.c.id)
            .where(books.c.id > cursor, book_metadata.c.metadataPending.is_(True))
            .order_by(books.c.id)
            .limit(_PAGE_SIZE)
        ).all()
        if not rows:
            break
        cursor = rows[-1].id
        for row in rows:
            _put_work(
                bind,
                tasks,
                book_id=row.id,
                library_id=row.libraryId,
                source_node_id=row.sourceNodeId,
                resource_id=None,
                identify=True,
                created_at=row.createdAt,
                source_state="QUEUED",
                reason="UPGRADED_PENDING_METADATA",
                promote_failed=False,
            )


def upgrade() -> None:
    backfill_book_tasks(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade Book imports")
