"""Converge historical import retries without replaying attempted work."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0037_single_import_execution"
down_revision = "0036_import_execution_identity"
branch_labels = None
depends_on = None


def _work_empty(work: dict[str, object]) -> bool:
    return work.get("scanScopes") == [] and work.get("resourceIds") == [] and not work.get("identify")


def _insert_book_work(connection: sa.Connection, old: dict[str, object], work: dict[str, object]) -> None:
    if not old["bookId"] or not old["sourceNodeId"] or _work_empty(work):
        return
    phase = "SCAN" if work.get("scanScopes") != [] else (
        "RESOURCES" if work.get("resourceIds") != [] else "IDENTIFY"
    )
    connection.execute(
        sa.text(
            'INSERT INTO "LibraryImportTask" '
            '("id", "kind", "libraryId", "bookId", "sourceNodeId", "state", '
            '"phase", "bookWork", "requestVersion", "retryCount", '
            '"completionRetryCount", "rerunRequested", "missingEntryPolicy", "createdAt") '
            'VALUES (:id, \'IMPORT_BOOK\', :library_id, :book_id, :source_id, '
            "'QUEUED', :phase, :work, 1, 0, 0, 0, 'PRESERVE', :created_at)"
        ),
        {
            "id": f"py_{uuid4().hex}",
            "library_id": old["libraryId"],
            "book_id": old["bookId"],
            "source_id": old["sourceNodeId"],
            "phase": phase,
            "work": json.dumps(work, separators=(",", ":")),
            "created_at": int(datetime.now(UTC).timestamp() * 1000),
        },
    )


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            'SELECT "id", "kind", "libraryId", "bookId", "sourceNodeId", '
            '"resourceId", "state", "bookWork", "startedAt", "executionVersion", '
            '"retryCount", "completionOutcome", "rerunRequested", "scanScopes", '
            '"missingEntryPolicy", "supersededByTaskId" FROM "LibraryImportTask"'
        )
    ).mappings().all()
    for row in rows:
        old = dict(row)
        state = old["state"]
        attempted = (
            state == "RUNNING"
            or old["startedAt"] is not None
            or old["executionVersion"] is not None
            or (old["retryCount"] or 0) > 0
            or old["completionOutcome"] is not None
        )
        already_migrated = old["supersededByTaskId"] is not None
        if old["kind"] == "IMPORT_BOOK" and old["bookWork"]:
            try:
                work = json.loads(old["bookWork"])
            except (TypeError, ValueError):
                work = None
            if isinstance(work, dict) and set(work) == {"active", "pending"}:
                active, pending = work["active"], work["pending"]
                if isinstance(active, dict) and isinstance(pending, dict):
                    if attempted:
                        _insert_book_work(connection, old, pending)
                    elif _work_empty(active):
                        connection.execute(
                            sa.text('UPDATE "LibraryImportTask" SET "bookWork"=:work WHERE "id"=:id'),
                            {"id": old["id"], "work": json.dumps(pending, separators=(",", ":"))},
                        )
                    else:
                        # The first scope has never run. Keep its task ID and
                        # turn the independently accepted pending scope into
                        # its own task.
                        connection.execute(
                            sa.text('UPDATE "LibraryImportTask" SET "bookWork"=:work WHERE "id"=:id'),
                            {"id": old["id"], "work": json.dumps(active, separators=(",", ":"))},
                        )
                        _insert_book_work(connection, old, pending)
                else:
                    attempted = True
            elif not isinstance(work, dict):
                attempted = True

        if old["kind"] in {"IMPORT_RESOURCE", "IMPORT_ASSET", "IDENTIFY_BOOK"}:
            # Legacy task kinds have no consumer in the new Book-only path.
            # Convert an untouched request, or a genuine rerun request, once.
            if not already_migrated and ((state == "QUEUED" and not attempted) or old["rerunRequested"]):
                resource_id = old["resourceId"]
                if resource_id is not None:
                    target = connection.execute(
                        sa.text(
                            'SELECT r."bookId" AS "bookId", b."sourceNodeId" AS "sourceNodeId" '
                            'FROM "LibraryReadableResource" r JOIN "LibraryBook" b '
                            'ON b."id"=r."bookId" WHERE r."id"=:id AND r."libraryId"=:library_id'
                        ),
                        {"id": resource_id, "library_id": old["libraryId"]},
                    ).mappings().first()
                    work = {"scanScopes": [], "resourceIds": [resource_id], "identify": True, "reasons": []}
                else:
                    target = connection.execute(
                        sa.text(
                            'SELECT "id" AS "bookId", "sourceNodeId" FROM "LibraryBook" '
                            'WHERE "sourceNodeId"=:source_id AND "libraryId"=:library_id'
                        ),
                        {"source_id": old["sourceNodeId"], "library_id": old["libraryId"]},
                    ).mappings().first()
                    work = {"scanScopes": [], "resourceIds": [], "identify": True, "reasons": []}
                if target is not None:
                    old.update(dict(target))
                    _insert_book_work(connection, old, work)
            attempted = True

        if old["kind"] in {"SCAN_LIBRARY", "CONTINUE_SOURCE"} and old["rerunRequested"]:
            connection.execute(
                sa.text(
                    'INSERT INTO "LibraryImportTask" '
                    '("id", "kind", "libraryId", "sourceNodeId", "state", '
                    '"scanScopes", "missingEntryPolicy", "createdAt") '
                    "VALUES (:id, :kind, :library_id, :source_id, 'QUEUED', "
                    ':scopes, :policy, :created_at)'
                ),
                {
                    "id": f"py_{uuid4().hex}", "kind": old["kind"],
                    "library_id": old["libraryId"], "source_id": old["sourceNodeId"],
                    "scopes": old["scanScopes"], "policy": old["missingEntryPolicy"],
                    "created_at": int(datetime.now(UTC).timestamp() * 1000),
                },
            )

        if attempted and state in {"RUNNING", "QUEUED"}:
            connection.execute(
                sa.text(
                    'UPDATE "LibraryImportTask" SET "state"=\'FAILED\', '
                    '"errorSummary"=:error, "finishedAt"=:now WHERE "id"=:id '
                    'AND "state" IN (\'RUNNING\', \'QUEUED\')'
                ),
                {
                    "id": old["id"],
                    "error": (
                        "WORKER_INTERRUPTED" if state == "RUNNING"
                        else "MIGRATED_TO_BOOK_TASK" if already_migrated
                        else "REIMPORT_REQUIRED"
                    ),
                    "now": int(datetime.now(UTC).timestamp() * 1000),
                },
            )

    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("LibraryImportTask")}
    if "LibraryImportTask_book_runnable_idx" in indexes:
        op.drop_index("LibraryImportTask_book_runnable_idx", table_name="LibraryImportTask")
    op.create_index(
        "LibraryImportTask_book_runnable_idx", "LibraryImportTask",
        ["state", "createdAt", "id"], unique=False,
        sqlite_where=sa.and_(sa.column("kind") == "IMPORT_BOOK", sa.column("state") == "QUEUED"),
    )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade import execution history")
