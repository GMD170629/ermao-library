"""Typed database guards shared by targeted reconciliation repositories."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import exists, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.application.watcher_dto import ReconcileFence
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.watcher import ReconcileStale

from .enums import (
    LibraryControlState,
    ReconcileIntentState,
    ScanState,
    SourceEntryType,
)
from .models import (
    CatalogLibrary,
    LibraryReconcileIntent,
    LibraryScanRun,
    LibrarySourceEntry,
    LibraryWatcherState,
)

_ACTIVE_SCAN_STATES = (
    ScanState.PENDING,
    ScanState.RUNNING,
    ScanState.FINALIZING,
)


def reconcile_library_conditions(
    fence: ReconcileFence,
) -> tuple[ColumnElement[bool], ...]:
    return (
        CatalogLibrary.id == fence.library_id,
        CatalogLibrary.config_revision == fence.config_revision,
        CatalogLibrary.root_path == fence.root_path_snapshot,
        CatalogLibrary.organization_mode == OrganizationMode(fence.organization_mode),
        CatalogLibrary.topology_version == fence.topology_version,
        CatalogLibrary.path_comparison == PathComparison(fence.path_comparison),
        CatalogLibrary.topology_writer_fence == fence.topology_writer_fence,
        CatalogLibrary.last_successful_generation == fence.presence_generation,
        CatalogLibrary.last_successful_generation.is_not(None),
        CatalogLibrary.control_state == LibraryControlState.ACTIVE,
    )


def reconcile_intent_conditions(
    fence: ReconcileFence,
) -> tuple[ColumnElement[bool], ...]:
    return (
        LibraryReconcileIntent.id == fence.intent_id,
        LibraryReconcileIntent.library_id == fence.library_id,
        LibraryReconcileIntent.through_sequence == fence.through_sequence,
        LibraryReconcileIntent.config_revision == fence.config_revision,
        LibraryReconcileIntent.organization_mode
        == OrganizationMode(fence.organization_mode),
        LibraryReconcileIntent.topology_version == fence.topology_version,
        LibraryReconcileIntent.path_comparison == PathComparison(fence.path_comparison),
        LibraryReconcileIntent.root_path_snapshot == fence.root_path_snapshot,
        LibraryReconcileIntent.root_identity_snapshot == fence.root_identity,
        LibraryReconcileIntent.topology_writer_fence == fence.topology_writer_fence,
        LibraryReconcileIntent.lease_owner == fence.lease_owner,
        LibraryReconcileIntent.state == ReconcileIntentState.RUNNING,
    )


def reconcile_environment_exists(fence: ReconcileFence) -> ColumnElement[bool]:
    library_exists = exists(
        select(CatalogLibrary.id).where(*reconcile_library_conditions(fence))
    )
    root_matches = exists(
        select(LibrarySourceEntry.id).where(
            LibrarySourceEntry.library_id == fence.library_id,
            LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
            LibrarySourceEntry.filesystem_identity == fence.root_identity,
        )
    )
    watcher_available = exists(
        select(LibraryWatcherState.library_id).where(
            LibraryWatcherState.library_id == fence.library_id,
            LibraryWatcherState.overflow_through_sequence.is_(None),
        )
    )
    no_active_scan = ~exists(
        select(LibraryScanRun.id).where(
            LibraryScanRun.library_id == fence.library_id,
            LibraryScanRun.state.in_(_ACTIVE_SCAN_STATES),
        )
    )
    return library_exists & root_matches & watcher_available & no_active_scan


def guard_reconcile_mutation(
    session: Session,
    fence: ReconcileFence,
    *,
    now: datetime,
) -> bool:
    result = session.execute(
        update(LibraryReconcileIntent)
        .where(
            *reconcile_intent_conditions(fence),
            LibraryReconcileIntent.lease_expires_at.is_not(None),
            LibraryReconcileIntent.lease_expires_at > now,
            reconcile_environment_exists(fence),
        )
        .values(attempt=LibraryReconcileIntent.attempt)
    )
    return cast(CursorResult[object], result).rowcount == 1


def require_live_reconcile(
    session: Session,
    fence: ReconcileFence,
    *,
    now: datetime,
) -> None:
    if not guard_reconcile_mutation(session, fence, now=now):
        raise ReconcileStale()


__all__ = [
    "guard_reconcile_mutation",
    "reconcile_environment_exists",
    "reconcile_intent_conditions",
    "reconcile_library_conditions",
    "require_live_reconcile",
]
