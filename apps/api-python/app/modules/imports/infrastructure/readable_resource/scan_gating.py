"""Path- and scope-aware scan gating for import task scheduling.

A queued import or identification task waits only for scan work that can still
change its own necessary inputs. Library membership and the fact that a scan
created a task are not dependencies. A single-file resource never waits on a
scan because its node observation is already committed. A directory resource
and a book wait while a durable incomplete range covers their anchor; the range
can only be recorded by a scan and removed by a later scan that actually
enumerates it, so deleting a failed task row never releases the wait.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import and_, exists, func, literal, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.util import AliasedClass
from sqlalchemy.sql import ColumnElement

from app.models import LibraryImportScanGap, LibraryImportTask, LibrarySourceNode
from app.modules.imports.domain.scan_policy import (
    ScanScope,
    decode_scan_scopes,
    encode_scan_scopes,
    merge_scan_scopes,
    remove_scan_scopes,
)

ACTIVE_SCAN_STATES = ("QUEUED", "RUNNING")


def path_contains(
    container: ColumnElement[str], child: ColumnElement[str]
) -> ColumnElement[bool]:
    """True when ``child`` is the same path or lives below ``container``."""
    return or_(
        container == "",
        child == container,
        func.instr(child, container + "/") == 1,
    )


def paths_intersect(
    left: ColumnElement[str], right: ColumnElement[str]
) -> ColumnElement[bool]:
    """True when scanning one path can change the other path's member set."""
    return or_(path_contains(left, right), path_contains(right, left))


def scopes_column_covers_anchor(
    scopes: ColumnElement[str | None],
    candidate: AliasedClass[LibrarySourceNode],
) -> ColumnElement[bool]:
    """True when any scope in a JSON column covers the candidate path.

    Recursive scopes cover their subtree; every scope also covers its
    ancestors because an unenumerated parent range leaves the candidate's
    membership unconfirmed. A non-recursive scope does not enumerate nested
    directories, so it never claims a descendant it will not walk.
    """
    scope = func.json_each(scopes).table_valued("value").alias()
    scope_path = func.json_extract(scope.c.value, "$.relativePath")
    scope_recursive = func.json_extract(scope.c.value, "$.recursive")
    return exists(
        select(literal(1))
        .select_from(scope)
        .where(
            or_(
                path_contains(candidate.relative_path, scope_path),
                and_(
                    scope_recursive == 1,
                    path_contains(scope_path, candidate.relative_path),
                ),
            )
        )
        .correlate(candidate)
    )


def gap_covers_anchor(
    library_id: ColumnElement[str],
    candidate: AliasedClass[LibrarySourceNode],
) -> ColumnElement[bool]:
    """Durable incomplete-range gate correlated to a library and anchor."""
    gap = aliased(LibraryImportScanGap)
    return exists(
        select(literal(1))
        .select_from(gap)
        .where(
            gap.library_id == library_id,
            scopes_column_covers_anchor(gap.scopes, candidate),
        )
    )


def active_imports_for_anchor(
    root: AliasedClass[LibrarySourceNode],
    *,
    library_id: ColumnElement[str],
    anchor_id: ColumnElement[str],
) -> ColumnElement[bool]:
    """Active import work that can still change one anchor's necessary inputs.

    ``root`` must be joined by the caller to ``anchor_id``. Imports below the
    anchor and active scans covering it wait; scans of unrelated paths do not.
    """
    node = aliased(LibrarySourceNode)
    task = aliased(LibraryImportTask)
    under_root = or_(
        node.id == anchor_id,
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
        .join(root, root.id == anchor_id)
        .outerjoin(node, node.id == task.source_node_id)
        .where(
            task.library_id == library_id,
            task.state.in_(ACTIVE_SCAN_STATES),
            or_(
                and_(
                    task.kind == "SCAN_LIBRARY",
                    or_(
                        task.scan_scopes.is_(None),
                        scopes_column_covers_anchor(task.scan_scopes, root),
                    ),
                ),
                and_(task.kind.in_(("IMPORT_ASSET", "IMPORT_RESOURCE")), under_root),
                and_(task.kind == "CONTINUE_SOURCE", or_(under_root, ancestor_scan)),
                and_(
                    task.kind == "IMPORT_BOOK",
                    task.source_node_id == anchor_id,
                ),
            ),
        )
    )


def load_gap_scopes(session: Session, library_id: str) -> tuple[ScanScope, ...]:
    """Read one library's durable incomplete ranges for read-only projections."""
    row = session.get(LibraryImportScanGap, library_id)
    if row is None:
        return ()
    return decode_scan_scopes(row.scopes) or ()


def record_scan_gaps(
    session: Session,
    library_id: str,
    scopes: Iterable[ScanScope],
) -> None:
    """Merge newly confirmed incomplete ranges into the durable gap row."""
    normalized = merge_scan_scopes((), tuple(scopes)) or ()
    if not normalized:
        return
    row = session.get(LibraryImportScanGap, library_id)
    existing = decode_scan_scopes(row.scopes) or () if row is not None else ()
    merged = merge_scan_scopes(existing, normalized) or ()
    stored = encode_scan_scopes(merged) if merged else None
    if row is None:
        session.add(LibraryImportScanGap(library_id=library_id, scopes=stored))
    else:
        row.scopes = stored
    session.flush()


def clear_scan_gaps(
    session: Session,
    library_id: str,
    completed: Iterable[ScanScope],
) -> None:
    """Remove durable ranges a fully completed scan actually enumerated."""
    row = session.get(LibraryImportScanGap, library_id)
    if row is None:
        return
    remaining = remove_scan_scopes(
        decode_scan_scopes(row.scopes) or (), tuple(completed)
    )
    row.scopes = encode_scan_scopes(remaining) if remaining else None
    session.flush()


__all__ = [
    "active_imports_for_anchor",
    "clear_scan_gaps",
    "gap_covers_anchor",
    "load_gap_scopes",
    "record_scan_gaps",
    "scopes_column_covers_anchor",
]
