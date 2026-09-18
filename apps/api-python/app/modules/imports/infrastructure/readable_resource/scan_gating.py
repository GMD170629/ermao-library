"""Path- and scope-aware scan gating for import task scheduling.

A queued import or identification task waits only for scan work that can still
change its own necessary inputs. Library membership and the fact that a scan
created a task are not dependencies. A single-file resource never waits on a
scan because its node observation is already committed. A directory resource
and a book wait for an incomplete scan whose recorded range covers their
anchor.
"""

from __future__ import annotations

from sqlalchemy import and_, exists, func, literal, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass
from sqlalchemy.sql import ColumnElement

from app.models import LibraryImportTask, LibrarySourceNode

INCOMPLETE_SCAN_STATES = ("QUEUED", "RUNNING", "FAILED")
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


def scoped_scan_covers(
    scan: AliasedClass[LibraryImportTask],
    candidate: AliasedClass[LibrarySourceNode],
) -> ColumnElement[bool]:
    """True when any persisted scope covers the candidate path.

    Recursive scopes cover their subtree; every scope also covers its
    ancestors because scanning a child directory changes the parent resource
    member set. A non-recursive scope does not enumerate nested directories, so
    it never claims a descendant that it will not walk.
    """
    scope = func.json_each(scan.scan_scopes).table_valued("value").alias()
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


def scan_touches_anchor(
    scan: AliasedClass[LibraryImportTask],
    scan_node: AliasedClass[LibrarySourceNode],
    candidate: AliasedClass[LibrarySourceNode],
    *,
    states: tuple[str, ...],
) -> ColumnElement[bool]:
    """True when a scan in ``states`` can still change the candidate's inputs.

    A CONTINUE_SOURCE names its exact node, so its lineage is compared in both
    directions: scanning a parent or a descendant directory can change the
    member set. A SCAN_LIBRARY without scopes covers the whole library; a
    scoped one is matched against its persisted scopes.
    """
    covers = or_(
        and_(
            scan.kind == "CONTINUE_SOURCE",
            paths_intersect(scan_node.relative_path, candidate.relative_path),
        ),
        and_(
            scan.kind == "SCAN_LIBRARY",
            or_(
                scan.scan_scopes.is_(None),
                scoped_scan_covers(scan, candidate),
            ),
        ),
    )
    return and_(scan.state.in_(states), covers)


def incomplete_scan_touches(
    scan: AliasedClass[LibraryImportTask],
    scan_node: AliasedClass[LibrarySourceNode],
    candidate: AliasedClass[LibrarySourceNode],
) -> ColumnElement[bool]:
    return scan_touches_anchor(
        scan, scan_node, candidate, states=INCOMPLETE_SCAN_STATES
    )


def active_imports_for_anchor(
    root: AliasedClass[LibrarySourceNode],
    *,
    library_id: ColumnElement[str],
    anchor_id: ColumnElement[str],
) -> ColumnElement[bool]:
    """Active import work that can still change one anchor's necessary inputs.

    ``root`` must be joined by the caller to ``anchor_id``. Imports below the
    anchor and overlapping scans wait; scans of unrelated paths do not.
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
                        scoped_scan_covers(task, root),
                    ),
                ),
                and_(task.kind.in_(("IMPORT_ASSET", "IMPORT_RESOURCE")), under_root),
                and_(task.kind == "CONTINUE_SOURCE", or_(under_root, ancestor_scan)),
            ),
        )
    )


__all__ = [
    "active_imports_for_anchor",
    "incomplete_scan_touches",
    "scoped_scan_covers",
]
