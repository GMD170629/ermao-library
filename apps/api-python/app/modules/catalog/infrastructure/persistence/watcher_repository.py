"""SQLAlchemy persistence for the bounded watcher reconciliation journal."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.application.scan_dto import ScanLibrarySnapshot
from app.modules.catalog.application.watcher_dto import (
    FullRescanTransition,
    FullScanWatcherStart,
    ReconcileFence,
    ReconcileIntent,
    WatcherFinalizeOutcome,
    WatcherResumeOutcome,
    WatcherState,
)
from app.modules.catalog.application.watcher_dto import (
    ReconcileIntentPhase as ApplicationIntentPhase,
)
from app.modules.catalog.application.watcher_dto import (
    ReconcileIntentState as ApplicationIntentState,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.scan import ScanStale
from app.modules.catalog.domain.watcher import (
    FullRescanReason as DomainFullRescanReason,
)
from app.modules.catalog.domain.watcher import (
    ReconcileMoveEvidence,
    ReconcileScope,
    WatcherMovedEntryType,
)

from .enums import (
    FullRescanReason,
    LibraryControlState,
    ReconcileIntentPhase,
    ReconcileIntentState,
    ReconcileMovedEntryType,
    RevisionState,
    ScanState,
    SourceEntryType,
)
from .models import (
    CatalogLibrary,
    LibraryReconcileIntent,
    LibraryScanRun,
    LibrarySourceEntry,
    LibraryWatcherState,
    TopologyUnitRevision,
)
from .reconcile_fencing import (
    reconcile_environment_exists,
    reconcile_intent_conditions,
)
from .scan_run_repositories import SqlAlchemyScanLibraryRepository

_ACTIVE_SCAN_STATES = (
    ScanState.PENDING,
    ScanState.RUNNING,
    ScanState.FINALIZING,
)


def _coalesce_key(scopes: tuple[ReconcileScope, ...]) -> str:
    ordered = sorted((scope.comparison_key, scope.relative_path[0]) for scope in scopes)
    payload = "".join(
        f"{len(key.encode('utf-8'))}:{key}{len(raw.encode('utf-8'))}:{raw}"
        for key, raw in ordered
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _watcher_state(row: LibraryWatcherState) -> WatcherState:
    return WatcherState(
        library_id=row.library_id,
        latest_sequence=row.latest_sequence,
        overflow_through_sequence=row.overflow_through_sequence,
        full_rescan_reason=(
            None
            if row.full_rescan_reason is None
            else DomainFullRescanReason(row.full_rescan_reason.value)
        ),
    )


def _intent(row: LibraryReconcileIntent) -> ReconcileIntent:
    scopes = [
        ReconcileScope(
            relative_path=(row.scope1_path,),
            comparison_key=row.scope1_key,
        )
    ]
    if row.scope2_path is not None:
        if row.scope2_key is None:
            raise RuntimeError("stored reconcile scope pair is incomplete")
        scopes.append(
            ReconcileScope(
                relative_path=(row.scope2_path,),
                comparison_key=row.scope2_key,
            )
        )
    move_evidence = None
    if row.move_old_path is not None:
        if row.move_new_path is None or row.moved_entry_type is None:
            raise RuntimeError("stored reconcile move evidence is incomplete")
        move_evidence = ReconcileMoveEvidence(
            source_path=tuple(row.move_old_path),
            destination_path=tuple(row.move_new_path),
            entry_type=WatcherMovedEntryType(row.moved_entry_type.value),
        )
    return ReconcileIntent(
        intent_id=row.id,
        library_id=row.library_id,
        first_sequence=row.first_sequence,
        through_sequence=row.through_sequence,
        scopes=tuple(scopes),
        move_evidence=move_evidence,
        state=ApplicationIntentState(row.state.value),
        phase=ApplicationIntentPhase(row.phase.value),
        lease_owner=row.lease_owner,
        lease_expires_at=_utc(row.lease_expires_at),
        topology_writer_fence=row.topology_writer_fence,
        attempt=row.attempt,
        available_at=cast(datetime, _utc(row.available_at)),
        fold_after_source_entry_id=row.fold_after_source_entry_id,
        config_revision=row.config_revision,
        organization_mode=OrganizationMode(row.organization_mode.value),
        topology_version=row.topology_version,
        path_comparison=PathComparison(row.path_comparison.value),
        root_path_snapshot=row.root_path_snapshot,
        root_identity_snapshot=row.root_identity_snapshot,
        created_at=cast(datetime, _utc(row.created_at)),
        updated_at=cast(datetime, _utc(row.updated_at)),
    )


def _intent_row(intent: ReconcileIntent) -> LibraryReconcileIntent:
    scope2 = intent.scopes[1] if len(intent.scopes) == 2 else None
    move = intent.move_evidence
    return LibraryReconcileIntent(
        id=intent.intent_id,
        library_id=intent.library_id,
        first_sequence=intent.first_sequence,
        through_sequence=intent.through_sequence,
        scope1_path=intent.scopes[0].relative_path[0],
        scope1_key=intent.scopes[0].comparison_key,
        scope2_path=None if scope2 is None else scope2.relative_path[0],
        scope2_key=None if scope2 is None else scope2.comparison_key,
        coalesce_key=_coalesce_key(intent.scopes),
        move_old_path=None if move is None else list(move.source_path),
        move_new_path=None if move is None else list(move.destination_path),
        moved_entry_type=(
            None if move is None else ReconcileMovedEntryType(move.entry_type.value)
        ),
        state=ReconcileIntentState(intent.state.value),
        phase=ReconcileIntentPhase(intent.phase.value),
        lease_owner=intent.lease_owner,
        lease_expires_at=intent.lease_expires_at,
        topology_writer_fence=intent.topology_writer_fence,
        attempt=intent.attempt,
        available_at=intent.available_at,
        fold_after_source_entry_id=intent.fold_after_source_entry_id,
        config_revision=intent.config_revision,
        organization_mode=OrganizationMode(intent.organization_mode),
        topology_version=intent.topology_version,
        path_comparison=PathComparison(intent.path_comparison),
        root_path_snapshot=intent.root_path_snapshot,
        root_identity_snapshot=intent.root_identity_snapshot,
        created_at=intent.created_at,
        updated_at=intent.updated_at,
    )


def _library_matches_snapshot(
    library: ScanLibrarySnapshot,
) -> tuple[ColumnElement[bool], ...]:
    return (
        CatalogLibrary.id == library.library_id,
        CatalogLibrary.config_revision == library.config_revision,
        CatalogLibrary.root_path == library.canonical_root,
        CatalogLibrary.organization_mode == OrganizationMode(library.organization_mode),
        CatalogLibrary.topology_version == library.topology_version,
        CatalogLibrary.path_comparison == PathComparison(library.path_comparison),
        CatalogLibrary.topology_writer_fence == library.topology_writer_fence,
        CatalogLibrary.control_state == LibraryControlState(library.control_state),
    )


def _same_structure(
    intent: ReconcileIntent,
    library: ScanLibrarySnapshot,
) -> bool:
    return (
        intent.library_id == library.library_id
        and intent.organization_mode is library.organization_mode
        and intent.topology_version == library.topology_version
        and intent.path_comparison is library.path_comparison
        and intent.root_path_snapshot == library.canonical_root
    )


def _root_identity_exists(library_id: str, identity: str) -> ColumnElement[bool]:
    return exists(
        select(LibrarySourceEntry.id).where(
            LibrarySourceEntry.library_id == library_id,
            LibrarySourceEntry.parent_entry_id.is_(None),
            LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
            LibrarySourceEntry.filesystem_identity == identity,
        )
    )


def _no_active_scan(library_id: str) -> ColumnElement[bool]:
    return ~exists(
        select(LibraryScanRun.id).where(
            LibraryScanRun.library_id == library_id,
            LibraryScanRun.state.in_(_ACTIVE_SCAN_STATES),
        )
    )


def _watcher_available(library_id: str) -> ColumnElement[bool]:
    return exists(
        select(LibraryWatcherState.library_id).where(
            LibraryWatcherState.library_id == library_id,
            LibraryWatcherState.overflow_through_sequence.is_(None),
        )
    )


def _intent_row_conditions(
    intent: ReconcileIntent,
) -> tuple[ColumnElement[bool], ...]:
    return (
        LibraryReconcileIntent.id == intent.intent_id,
        LibraryReconcileIntent.library_id == intent.library_id,
        LibraryReconcileIntent.first_sequence == intent.first_sequence,
        LibraryReconcileIntent.through_sequence == intent.through_sequence,
        LibraryReconcileIntent.state == ReconcileIntentState(intent.state.value),
        LibraryReconcileIntent.phase == ReconcileIntentPhase(intent.phase.value),
        LibraryReconcileIntent.lease_owner == intent.lease_owner,
        LibraryReconcileIntent.lease_expires_at == intent.lease_expires_at,
        LibraryReconcileIntent.topology_writer_fence == intent.topology_writer_fence,
        LibraryReconcileIntent.attempt == intent.attempt,
        LibraryReconcileIntent.config_revision == intent.config_revision,
        LibraryReconcileIntent.organization_mode
        == OrganizationMode(intent.organization_mode),
        LibraryReconcileIntent.topology_version == intent.topology_version,
        LibraryReconcileIntent.path_comparison
        == PathComparison(intent.path_comparison),
        LibraryReconcileIntent.root_path_snapshot == intent.root_path_snapshot,
        LibraryReconcileIntent.root_identity_snapshot == intent.root_identity_snapshot,
    )


class SqlAlchemyReconcileLibraryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_reconcile_for_update(
        self, library_id: str
    ) -> ScanLibrarySnapshot | None:
        return SqlAlchemyScanLibraryRepository(self._session).get_for_scan_for_update(
            library_id
        )

    def reserve_reconcile_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
    ) -> int | None:
        next_fence = expected_topology_writer_fence + 1
        no_active_scan = ~exists(
            select(LibraryScanRun.id).where(
                LibraryScanRun.library_id == library_id,
                LibraryScanRun.state.in_(_ACTIVE_SCAN_STATES),
            )
        )
        watcher_available = exists(
            select(LibraryWatcherState.library_id).where(
                LibraryWatcherState.library_id == library_id,
                LibraryWatcherState.overflow_through_sequence.is_(None),
            )
        )
        result = self._session.execute(
            update(CatalogLibrary)
            .where(
                CatalogLibrary.id == library_id,
                CatalogLibrary.topology_writer_fence == expected_topology_writer_fence,
                CatalogLibrary.control_state == LibraryControlState.ACTIVE,
                CatalogLibrary.last_successful_generation.is_not(None),
                no_active_scan,
                watcher_available,
            )
            .values(topology_writer_fence=next_fence)
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return next_fence


class SqlAlchemyWatcherJournalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_state_for_update(self, library_id: str) -> WatcherState | None:
        row = self._session.scalar(
            select(LibraryWatcherState)
            .where(LibraryWatcherState.library_id == library_id)
            .with_for_update()
        )
        return None if row is None else _watcher_state(row)

    def find_overlapping_pending(
        self,
        library_id: str,
        scopes: tuple[ReconcileScope, ...],
        *,
        limit: int,
    ) -> tuple[ReconcileIntent, ...]:
        if limit <= 0:
            return ()
        keys = tuple({scope.comparison_key for scope in scopes})
        rows = self._session.scalars(
            select(LibraryReconcileIntent)
            .where(
                LibraryReconcileIntent.library_id == library_id,
                LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                or_(
                    LibraryReconcileIntent.scope1_key.in_(keys),
                    LibraryReconcileIntent.scope2_key.in_(keys),
                ),
            )
            .order_by(
                LibraryReconcileIntent.first_sequence,
                LibraryReconcileIntent.id,
            )
            .limit(limit)
            .with_for_update()
        ).all()
        return tuple(_intent(row) for row in rows)

    def pending_ids_up_to(self, library_id: str, *, limit: int) -> tuple[str, ...]:
        if limit <= 0:
            return ()
        return tuple(
            self._session.scalars(
                select(LibraryReconcileIntent.id)
                .where(
                    LibraryReconcileIntent.library_id == library_id,
                    LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                )
                .order_by(
                    LibraryReconcileIntent.first_sequence,
                    LibraryReconcileIntent.id,
                )
                .limit(limit)
            ).all()
        )

    def append_or_replace(
        self,
        *,
        expected_latest_sequence: int,
        intent: ReconcileIntent,
        replaced_intent_ids: tuple[str, ...],
    ) -> ReconcileIntent | None:
        allocated_sequence = expected_latest_sequence + 1
        if (
            intent.state is not ApplicationIntentState.PENDING
            or intent.through_sequence != allocated_sequence
        ):
            raise ValueError("a queued intent must use the next allocated sequence")
        result = self._session.execute(
            update(LibraryWatcherState)
            .where(
                LibraryWatcherState.library_id == intent.library_id,
                LibraryWatcherState.latest_sequence == expected_latest_sequence,
                LibraryWatcherState.overflow_through_sequence.is_(None),
            )
            .values(
                latest_sequence=allocated_sequence,
                updated_at=intent.updated_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        if replaced_intent_ids:
            deleted = self._session.execute(
                delete(LibraryReconcileIntent).where(
                    LibraryReconcileIntent.library_id == intent.library_id,
                    LibraryReconcileIntent.id.in_(replaced_intent_ids),
                    LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                )
            )
            if cast(CursorResult[object], deleted).rowcount != len(
                set(replaced_intent_ids)
            ):
                return None
        self._session.add(_intent_row(intent))
        self._session.flush()
        return intent

    def force_full_rescan(
        self,
        library_id: str,
        *,
        expected_latest_sequence: int,
        reason: DomainFullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        state = self._state_row(library_id)
        library = self._session.get(CatalogLibrary, library_id)
        if (
            state is None
            or library is None
            or state.latest_sequence != expected_latest_sequence
        ):
            return None
        newly_required = state.overflow_through_sequence is None
        running = self._running_row(library_id)
        if running is not None and self._has_active_scan(library_id):
            return None

        next_fence = library.topology_writer_fence
        invalidated_id: str | None = None
        if running is not None:
            next_fence += 1
            fenced = self._session.execute(
                update(CatalogLibrary)
                .where(
                    CatalogLibrary.id == library_id,
                    CatalogLibrary.topology_writer_fence
                    == running.topology_writer_fence,
                )
                .values(topology_writer_fence=next_fence)
            )
            if cast(CursorResult[object], fenced).rowcount != 1:
                return None
            self._abandon_reconcile_staging(running.id)
            invalidated_id = running.id

        allocated_sequence = expected_latest_sequence + 1
        first_reason = (
            state.full_rescan_reason
            if state.full_rescan_reason is not None
            else FullRescanReason(reason.value)
        )
        updated = self._session.execute(
            update(LibraryWatcherState)
            .where(
                LibraryWatcherState.library_id == library_id,
                LibraryWatcherState.latest_sequence == expected_latest_sequence,
            )
            .values(
                latest_sequence=allocated_sequence,
                overflow_through_sequence=allocated_sequence,
                full_rescan_reason=first_reason,
                updated_at=observed_at,
            )
        )
        if cast(CursorResult[object], updated).rowcount != 1:
            return None
        self._session.execute(
            delete(LibraryReconcileIntent).where(
                LibraryReconcileIntent.library_id == library_id
            )
        )
        refreshed = self._state_row(library_id)
        if refreshed is None:
            raise RuntimeError("watcher state disappeared during rescan transition")
        return FullRescanTransition(
            state=_watcher_state(refreshed),
            newly_required=newly_required,
            invalidated_running_intent_id=invalidated_id,
            topology_writer_fence=next_fence,
        )

    def force_full_rescan_from_running(
        self,
        fence: ReconcileFence,
        *,
        reason: DomainFullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        state = self._state_row(fence.library_id)
        if state is None or state.latest_sequence < fence.through_sequence:
            return None
        newly_required = state.overflow_through_sequence is None
        owned_live_intent = exists(
            select(LibraryReconcileIntent.id).where(
                *reconcile_intent_conditions(fence),
                LibraryReconcileIntent.lease_expires_at.is_not(None),
                LibraryReconcileIntent.lease_expires_at > observed_at,
            )
        )
        next_fence = fence.topology_writer_fence + 1
        fenced = self._session.execute(
            update(CatalogLibrary)
            .where(
                CatalogLibrary.id == fence.library_id,
                CatalogLibrary.config_revision == fence.config_revision,
                CatalogLibrary.root_path == fence.root_path_snapshot,
                CatalogLibrary.organization_mode
                == OrganizationMode(fence.organization_mode),
                CatalogLibrary.topology_version == fence.topology_version,
                CatalogLibrary.path_comparison == PathComparison(fence.path_comparison),
                CatalogLibrary.topology_writer_fence == fence.topology_writer_fence,
                CatalogLibrary.last_successful_generation == fence.presence_generation,
                CatalogLibrary.control_state == LibraryControlState.ACTIVE,
                owned_live_intent,
                ~exists(
                    select(LibraryScanRun.id).where(
                        LibraryScanRun.library_id == fence.library_id,
                        LibraryScanRun.state.in_(_ACTIVE_SCAN_STATES),
                    )
                ),
            )
            .values(topology_writer_fence=next_fence)
        )
        if cast(CursorResult[object], fenced).rowcount != 1:
            return None
        self._abandon_reconcile_staging(fence.intent_id)
        first_reason = (
            state.full_rescan_reason
            if state.full_rescan_reason is not None
            else FullRescanReason(reason.value)
        )
        updated = self._session.execute(
            update(LibraryWatcherState)
            .where(
                LibraryWatcherState.library_id == fence.library_id,
                LibraryWatcherState.latest_sequence == state.latest_sequence,
            )
            .values(
                overflow_through_sequence=state.latest_sequence,
                full_rescan_reason=first_reason,
                updated_at=observed_at,
            )
        )
        if cast(CursorResult[object], updated).rowcount != 1:
            return None
        self._session.execute(
            delete(LibraryReconcileIntent).where(
                LibraryReconcileIntent.library_id == fence.library_id
            )
        )
        refreshed = self._state_row(fence.library_id)
        if refreshed is None:
            raise RuntimeError("watcher state disappeared during rescan transition")
        return FullRescanTransition(
            state=_watcher_state(refreshed),
            newly_required=newly_required,
            invalidated_running_intent_id=fence.intent_id,
            topology_writer_fence=next_fence,
        )

    def force_full_rescan_from_invalidated(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        reason: DomainFullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        if (
            intent.state is not ApplicationIntentState.RUNNING
            or current_library.control_state.value != LibraryControlState.ACTIVE.value
            or current_library.last_successful_generation is None
        ):
            return None
        current_root_identity = self._root_identity(intent.library_id)
        if (
            _same_structure(intent, current_library)
            and current_root_identity == intent.root_identity_snapshot
        ):
            return None
        state = self._state_row(intent.library_id)
        if state is None:
            return None
        newly_required = state.overflow_through_sequence is None
        running_exists = exists(
            select(LibraryReconcileIntent.id).where(*_intent_row_conditions(intent))
        )
        next_fence = current_library.topology_writer_fence + 1
        fenced = self._session.execute(
            update(CatalogLibrary)
            .where(
                *_library_matches_snapshot(current_library),
                CatalogLibrary.control_state == LibraryControlState.ACTIVE,
                CatalogLibrary.last_successful_generation.is_not(None),
                running_exists,
                _no_active_scan(intent.library_id),
            )
            .values(topology_writer_fence=next_fence)
        )
        if cast(CursorResult[object], fenced).rowcount != 1:
            return None
        self._abandon_reconcile_staging(intent.intent_id)
        first_reason = (
            state.full_rescan_reason
            if state.full_rescan_reason is not None
            else FullRescanReason(reason.value)
        )
        updated = self._session.execute(
            update(LibraryWatcherState)
            .where(
                LibraryWatcherState.library_id == intent.library_id,
                LibraryWatcherState.latest_sequence == state.latest_sequence,
            )
            .values(
                overflow_through_sequence=state.latest_sequence,
                full_rescan_reason=first_reason,
                updated_at=observed_at,
            )
        )
        if cast(CursorResult[object], updated).rowcount != 1:
            return None
        self._session.execute(
            delete(LibraryReconcileIntent).where(
                LibraryReconcileIntent.library_id == intent.library_id
            )
        )
        refreshed = self._state_row(intent.library_id)
        if refreshed is None:
            raise RuntimeError("watcher state disappeared during rescan transition")
        return FullRescanTransition(
            state=_watcher_state(refreshed),
            newly_required=newly_required,
            invalidated_running_intent_id=intent.intent_id,
            topology_writer_fence=next_fence,
        )

    def force_full_rescan_from_pending(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        reason: DomainFullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        if (
            intent.state is not ApplicationIntentState.PENDING
            or current_library.control_state.value != LibraryControlState.ACTIVE.value
            or current_library.last_successful_generation is None
        ):
            return None
        current_root_identity = self._root_identity(intent.library_id)
        if (
            _same_structure(intent, current_library)
            and current_root_identity == intent.root_identity_snapshot
        ):
            return None
        state = self._state_row(intent.library_id)
        if state is None:
            return None
        pending_exists = exists(
            select(LibraryReconcileIntent.id).where(*_intent_row_conditions(intent))
        )
        current_library_exists = exists(
            select(CatalogLibrary.id).where(
                *_library_matches_snapshot(current_library),
                CatalogLibrary.control_state == LibraryControlState.ACTIVE,
                CatalogLibrary.last_successful_generation.is_not(None),
            )
        )
        newly_required = state.overflow_through_sequence is None
        first_reason = (
            state.full_rescan_reason
            if state.full_rescan_reason is not None
            else FullRescanReason(reason.value)
        )
        updated = self._session.execute(
            update(LibraryWatcherState)
            .where(
                LibraryWatcherState.library_id == intent.library_id,
                LibraryWatcherState.latest_sequence == state.latest_sequence,
                pending_exists,
                current_library_exists,
                _no_active_scan(intent.library_id),
            )
            .values(
                overflow_through_sequence=state.latest_sequence,
                full_rescan_reason=first_reason,
                updated_at=observed_at,
            )
        )
        if cast(CursorResult[object], updated).rowcount != 1:
            return None
        self._session.execute(
            delete(LibraryReconcileIntent).where(
                LibraryReconcileIntent.library_id == intent.library_id
            )
        )
        refreshed = self._state_row(intent.library_id)
        if refreshed is None:
            raise RuntimeError("watcher state disappeared during rescan transition")
        return FullRescanTransition(
            state=_watcher_state(refreshed),
            newly_required=newly_required,
            invalidated_running_intent_id=None,
            topology_writer_fence=current_library.topology_writer_fence,
        )

    def get_running_for_update(self, library_id: str) -> ReconcileIntent | None:
        row = self._running_row(library_id)
        return None if row is None else _intent(row)

    def get_next_pending_for_update(
        self, library_id: str, *, now: datetime
    ) -> ReconcileIntent | None:
        row = self._session.scalar(
            select(LibraryReconcileIntent)
            .where(
                LibraryReconcileIntent.library_id == library_id,
                LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                LibraryReconcileIntent.available_at <= now,
            )
            .order_by(
                LibraryReconcileIntent.first_sequence,
                LibraryReconcileIntent.id,
            )
            .limit(1)
            .with_for_update()
        )
        return None if row is None else _intent(row)

    def claim(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        if (
            intent.state is not ApplicationIntentState.PENDING
            or not _same_structure(intent, current_library)
            or current_library.control_state.value != LibraryControlState.ACTIVE.value
            or current_library.last_successful_generation is None
            or topology_writer_fence != current_library.topology_writer_fence + 1
        ):
            return None
        library_matches = exists(
            select(CatalogLibrary.id).where(
                CatalogLibrary.id == current_library.library_id,
                CatalogLibrary.config_revision == current_library.config_revision,
                CatalogLibrary.organization_mode
                == OrganizationMode(current_library.organization_mode),
                CatalogLibrary.topology_version == current_library.topology_version,
                CatalogLibrary.path_comparison
                == PathComparison(current_library.path_comparison),
                CatalogLibrary.root_path == current_library.canonical_root,
                CatalogLibrary.topology_writer_fence == topology_writer_fence,
                CatalogLibrary.control_state == LibraryControlState.ACTIVE,
                CatalogLibrary.last_successful_generation
                == current_library.last_successful_generation,
            )
        )
        result = self._session.execute(
            update(LibraryReconcileIntent)
            .where(
                *_intent_row_conditions(intent),
                LibraryReconcileIntent.available_at <= now,
                _no_active_scan(intent.library_id),
                library_matches,
                _watcher_available(intent.library_id),
                _root_identity_exists(
                    intent.library_id,
                    intent.root_identity_snapshot,
                ),
            )
            .values(
                state=ReconcileIntentState.RUNNING,
                phase=ReconcileIntentPhase.EXECUTE,
                lease_owner=owner_token,
                lease_expires_at=lease_expires_at,
                topology_writer_fence=topology_writer_fence,
                attempt=LibraryReconcileIntent.attempt + 1,
                fold_after_source_entry_id=None,
                config_revision=current_library.config_revision,
                updated_at=now,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return self._updated_intent(intent.intent_id)

    def take_over_expired(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        if (
            intent.state is not ApplicationIntentState.RUNNING
            or not _same_structure(intent, current_library)
            or intent.config_revision != current_library.config_revision
            or current_library.control_state.value != LibraryControlState.ACTIVE.value
            or current_library.last_successful_generation is None
            or intent.lease_expires_at is None
            or intent.lease_expires_at > now
        ):
            return None
        expired = exists(
            select(LibraryReconcileIntent.id).where(
                *_intent_row_conditions(intent),
                LibraryReconcileIntent.lease_expires_at.is_not(None),
                LibraryReconcileIntent.lease_expires_at <= now,
            )
        )
        staging_safe = (
            ~exists(
                select(TopologyUnitRevision.id).where(
                    TopologyUnitRevision.library_id == intent.library_id,
                    TopologyUnitRevision.reconcile_origin_id == intent.intent_id,
                    TopologyUnitRevision.state == RevisionState.STAGING,
                )
            )
            if intent.phase is ApplicationIntentPhase.FOLD
            else exists(
                select(LibraryReconcileIntent.id).where(*_intent_row_conditions(intent))
            )
        )
        next_fence = current_library.topology_writer_fence + 1
        fenced = self._session.execute(
            update(CatalogLibrary)
            .where(
                *_library_matches_snapshot(current_library),
                CatalogLibrary.control_state == LibraryControlState.ACTIVE,
                CatalogLibrary.last_successful_generation.is_not(None),
                expired,
                staging_safe,
                _root_identity_exists(
                    intent.library_id,
                    intent.root_identity_snapshot,
                ),
                _no_active_scan(intent.library_id),
                _watcher_available(intent.library_id),
            )
            .values(topology_writer_fence=next_fence)
        )
        if cast(CursorResult[object], fenced).rowcount != 1:
            return None
        if intent.phase is ApplicationIntentPhase.EXECUTE:
            self._abandon_reconcile_staging(intent.intent_id)
        taken = self._session.execute(
            update(LibraryReconcileIntent)
            .where(
                *_intent_row_conditions(intent),
                LibraryReconcileIntent.lease_expires_at.is_not(None),
                LibraryReconcileIntent.lease_expires_at <= now,
            )
            .values(
                lease_owner=owner_token,
                lease_expires_at=lease_expires_at,
                topology_writer_fence=next_fence,
                attempt=LibraryReconcileIntent.attempt + 1,
                phase=ReconcileIntentPhase(intent.phase.value),
                fold_after_source_entry_id=(
                    intent.fold_after_source_entry_id
                    if intent.phase is ApplicationIntentPhase.FOLD
                    else None
                ),
                updated_at=now,
            )
        )
        if cast(CursorResult[object], taken).rowcount != 1:
            return None
        return self._updated_intent(intent.intent_id)

    def restart_invalidated(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        if (
            intent.state is not ApplicationIntentState.RUNNING
            or not _same_structure(intent, current_library)
            or intent.config_revision == current_library.config_revision
            or current_library.control_state.value != LibraryControlState.ACTIVE.value
            or current_library.last_successful_generation is None
        ):
            return None
        restartable = exists(
            select(LibraryReconcileIntent.id).where(*_intent_row_conditions(intent))
        )
        next_fence = current_library.topology_writer_fence + 1
        fenced = self._session.execute(
            update(CatalogLibrary)
            .where(
                *_library_matches_snapshot(current_library),
                CatalogLibrary.control_state == LibraryControlState.ACTIVE,
                CatalogLibrary.last_successful_generation.is_not(None),
                restartable,
                _root_identity_exists(
                    intent.library_id,
                    intent.root_identity_snapshot,
                ),
                _no_active_scan(intent.library_id),
                _watcher_available(intent.library_id),
            )
            .values(topology_writer_fence=next_fence)
        )
        if cast(CursorResult[object], fenced).rowcount != 1:
            return None
        self._abandon_reconcile_staging(intent.intent_id)
        restarted = self._session.execute(
            update(LibraryReconcileIntent)
            .where(*_intent_row_conditions(intent))
            .values(
                phase=ReconcileIntentPhase.EXECUTE,
                lease_owner=owner_token,
                lease_expires_at=lease_expires_at,
                topology_writer_fence=next_fence,
                attempt=LibraryReconcileIntent.attempt + 1,
                fold_after_source_entry_id=None,
                config_revision=current_library.config_revision,
                updated_at=now,
            )
        )
        if cast(CursorResult[object], restarted).rowcount != 1:
            return None
        return self._updated_intent(intent.intent_id)

    def heartbeat(
        self,
        fence: ReconcileFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        result = self._session.execute(
            update(LibraryReconcileIntent)
            .where(
                *reconcile_intent_conditions(fence),
                LibraryReconcileIntent.lease_expires_at.is_not(None),
                LibraryReconcileIntent.lease_expires_at > now,
                reconcile_environment_exists(fence),
            )
            .values(lease_expires_at=lease_expires_at, updated_at=now)
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return self._updated_intent(fence.intent_id)

    def has_overlapping_successor(
        self,
        fence: ReconcileFence,
        scopes: tuple[ReconcileScope, ...],
    ) -> bool:
        keys = tuple({scope.comparison_key for scope in scopes})
        return bool(
            self._session.scalar(
                select(
                    exists().where(
                        LibraryReconcileIntent.library_id == fence.library_id,
                        LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                        LibraryReconcileIntent.through_sequence
                        > fence.through_sequence,
                        or_(
                            LibraryReconcileIntent.scope1_key.in_(keys),
                            LibraryReconcileIntent.scope2_key.in_(keys),
                        ),
                    )
                )
            )
        )

    def begin_fold(
        self, fence: ReconcileFence, *, now: datetime
    ) -> ReconcileIntent | None:
        result = self._session.execute(
            update(LibraryReconcileIntent)
            .where(
                *reconcile_intent_conditions(fence),
                LibraryReconcileIntent.phase == ReconcileIntentPhase.EXECUTE,
                LibraryReconcileIntent.lease_expires_at.is_not(None),
                LibraryReconcileIntent.lease_expires_at > now,
                reconcile_environment_exists(fence),
            )
            .values(
                phase=ReconcileIntentPhase.FOLD,
                fold_after_source_entry_id=None,
                updated_at=now,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return self._updated_intent(fence.intent_id)

    def advance_fold_cursor(
        self,
        fence: ReconcileFence,
        *,
        after_source_entry_id: str | None,
        now: datetime,
    ) -> ReconcileIntent | None:
        result = self._session.execute(
            update(LibraryReconcileIntent)
            .where(
                *reconcile_intent_conditions(fence),
                LibraryReconcileIntent.phase == ReconcileIntentPhase.FOLD,
                LibraryReconcileIntent.lease_expires_at.is_not(None),
                LibraryReconcileIntent.lease_expires_at > now,
                reconcile_environment_exists(fence),
            )
            .values(
                fold_after_source_entry_id=after_source_entry_id,
                updated_at=now,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return self._updated_intent(fence.intent_id)

    def complete_delete(self, fence: ReconcileFence, *, completed_at: datetime) -> bool:
        result = self._session.execute(
            delete(LibraryReconcileIntent).where(
                *reconcile_intent_conditions(fence),
                LibraryReconcileIntent.lease_expires_at.is_not(None),
                LibraryReconcileIntent.lease_expires_at > completed_at,
                reconcile_environment_exists(fence),
            )
        )
        return cast(CursorResult[object], result).rowcount == 1

    def invalidate_expired_for_full_scan(
        self,
        library: ScanLibrarySnapshot,
        *,
        now: datetime,
    ) -> FullRescanTransition | None:
        running = self._running_row(library.library_id)
        state = self._state_row(library.library_id)
        if (
            running is None
            or state is None
            or running.lease_expires_at is None
            or state.latest_sequence <= 0
        ):
            return None
        newly_required = state.overflow_through_sequence is None
        current = self._session.scalar(
            select(CatalogLibrary).where(*_library_matches_snapshot(library))
        )
        if current is None:
            return None
        same_snapshot = (
            running.config_revision == library.config_revision
            and running.organization_mode.value == library.organization_mode.value
            and running.topology_version == library.topology_version
            and running.path_comparison.value == library.path_comparison.value
            and running.root_path_snapshot == library.canonical_root
            and running.root_identity_snapshot
            == self._root_identity(library.library_id)
            and running.topology_writer_fence == current.topology_writer_fence
        )
        lease_is_live = bool(
            self._session.scalar(
                select(
                    exists().where(
                        LibraryReconcileIntent.id == running.id,
                        LibraryReconcileIntent.lease_expires_at.is_not(None),
                        LibraryReconcileIntent.lease_expires_at > now,
                    )
                )
            )
        )
        if lease_is_live and same_snapshot:
            return None
        next_fence = current.topology_writer_fence + 1
        fenced = self._session.execute(
            update(CatalogLibrary)
            .where(*_library_matches_snapshot(library))
            .values(topology_writer_fence=next_fence)
        )
        if cast(CursorResult[object], fenced).rowcount != 1:
            return None
        self._abandon_reconcile_staging(running.id)
        reason = (
            state.full_rescan_reason
            if state.full_rescan_reason is not None
            else FullRescanReason.UNTRUSTED
        )
        updated = self._session.execute(
            update(LibraryWatcherState)
            .where(
                LibraryWatcherState.library_id == library.library_id,
                LibraryWatcherState.latest_sequence == state.latest_sequence,
            )
            .values(
                overflow_through_sequence=state.latest_sequence,
                full_rescan_reason=reason,
                updated_at=now,
            )
        )
        if cast(CursorResult[object], updated).rowcount != 1:
            return None
        self._session.execute(
            delete(LibraryReconcileIntent).where(
                LibraryReconcileIntent.library_id == library.library_id
            )
        )
        refreshed = self._state_row(library.library_id)
        if refreshed is None:
            raise RuntimeError("watcher state disappeared during scan preparation")
        return FullRescanTransition(
            state=_watcher_state(refreshed),
            newly_required=newly_required,
            invalidated_running_intent_id=running.id,
            topology_writer_fence=next_fence,
        )

    def finalize_full_scan(
        self,
        library_id: str,
        *,
        watcher_sequence_watermark: int,
        completed_at: datetime,
    ) -> WatcherFinalizeOutcome:
        finalizing_scan_exists = bool(
            self._session.scalar(
                select(
                    exists().where(
                        LibraryScanRun.library_id == library_id,
                        LibraryScanRun.state == ScanState.FINALIZING,
                        LibraryScanRun.watcher_sequence_watermark
                        == watcher_sequence_watermark,
                        LibraryScanRun.lease_expires_at.is_not(None),
                        LibraryScanRun.lease_expires_at > completed_at,
                    )
                )
            )
        )
        if not finalizing_scan_exists:
            raise ScanStale()
        state = self._state_row(library_id)
        if state is None:
            raise RuntimeError("library watcher state is not initialized")
        deleted = self._session.execute(
            delete(LibraryReconcileIntent).where(
                LibraryReconcileIntent.library_id == library_id,
                LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                LibraryReconcileIntent.through_sequence <= watcher_sequence_watermark,
            )
        )
        clear_overflow = (
            state.overflow_through_sequence is not None
            and state.overflow_through_sequence <= watcher_sequence_watermark
            and state.latest_sequence == watcher_sequence_watermark
        )
        if clear_overflow:
            cleared = self._session.execute(
                update(LibraryWatcherState)
                .where(
                    LibraryWatcherState.library_id == library_id,
                    LibraryWatcherState.latest_sequence == state.latest_sequence,
                    LibraryWatcherState.overflow_through_sequence
                    == state.overflow_through_sequence,
                )
                .values(
                    overflow_through_sequence=None,
                    full_rescan_reason=None,
                    updated_at=completed_at,
                )
            )
            if cast(CursorResult[object], cleared).rowcount != 1:
                raise ScanStale()
        replay_available = bool(
            self._session.scalar(
                select(
                    exists().where(
                        LibraryReconcileIntent.library_id == library_id,
                        LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                    )
                )
            )
        )
        refreshed = self._state_row(library_id)
        if refreshed is None:
            raise RuntimeError("watcher state disappeared during scan finalization")
        return WatcherFinalizeOutcome(
            state=_watcher_state(refreshed),
            discarded_intent_count=cast(CursorResult[object], deleted).rowcount,
            replay_available=replay_available,
        )

    def _state_row(self, library_id: str) -> LibraryWatcherState | None:
        return self._session.scalar(
            select(LibraryWatcherState)
            .where(LibraryWatcherState.library_id == library_id)
            .with_for_update()
        )

    def _running_row(self, library_id: str) -> LibraryReconcileIntent | None:
        return self._session.scalar(
            select(LibraryReconcileIntent)
            .where(
                LibraryReconcileIntent.library_id == library_id,
                LibraryReconcileIntent.state == ReconcileIntentState.RUNNING,
            )
            .with_for_update()
        )

    def _updated_intent(self, intent_id: str) -> ReconcileIntent | None:
        row = self._session.get(LibraryReconcileIntent, intent_id)
        return None if row is None else _intent(row)

    def _root_identity(self, library_id: str) -> str | None:
        return self._session.scalar(
            select(LibrarySourceEntry.filesystem_identity).where(
                LibrarySourceEntry.library_id == library_id,
                LibrarySourceEntry.parent_entry_id.is_(None),
                LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
            )
        )

    def _has_active_scan(self, library_id: str) -> bool:
        return bool(
            self._session.scalar(
                select(
                    exists().where(
                        LibraryScanRun.library_id == library_id,
                        LibraryScanRun.state.in_(_ACTIVE_SCAN_STATES),
                    )
                )
            )
        )

    def _abandon_reconcile_staging(self, intent_id: str) -> None:
        self._session.execute(
            update(TopologyUnitRevision)
            .where(
                TopologyUnitRevision.reconcile_origin_id == intent_id,
                TopologyUnitRevision.state == RevisionState.STAGING,
            )
            .values(state=RevisionState.ABANDONED)
        )


class SqlAlchemyWatcherScanCoordinationRepository:
    def __init__(self, session: Session) -> None:
        self._journal = SqlAlchemyWatcherJournalRepository(session)
        self._session = session

    def prepare_full_scan_start(
        self,
        library: ScanLibrarySnapshot,
        *,
        now: datetime,
    ) -> FullScanWatcherStart | None:
        running = self._journal.get_running_for_update(library.library_id)
        if running is not None:
            transition = self._journal.invalidate_expired_for_full_scan(
                library, now=now
            )
            if transition is None:
                return None
            return FullScanWatcherStart(
                watcher_sequence_watermark=transition.state.latest_sequence,
                topology_writer_fence=transition.topology_writer_fence,
            )
        state = self._journal.get_state_for_update(library.library_id)
        current = self._session.scalar(
            select(CatalogLibrary).where(*_library_matches_snapshot(library))
        )
        if state is None or current is None:
            return None
        return FullScanWatcherStart(
            watcher_sequence_watermark=state.latest_sequence,
            topology_writer_fence=current.topology_writer_fence,
        )

    def finalize_full_scan(
        self,
        library_id: str,
        *,
        watcher_sequence_watermark: int,
        completed_at: datetime,
    ) -> WatcherFinalizeOutcome:
        return self._journal.finalize_full_scan(
            library_id,
            watcher_sequence_watermark=watcher_sequence_watermark,
            completed_at=completed_at,
        )

    def resume_after_full_scan_terminal(
        self,
        library_id: str,
        *,
        observed_at: datetime,
    ) -> WatcherResumeOutcome:
        del observed_at
        state = self._journal.get_state_for_update(library_id)
        if state is None:
            raise RuntimeError("library watcher state is not initialized")
        replay_available = state.full_rescan_reason is None and bool(
            self._session.scalar(
                select(
                    exists().where(
                        LibraryReconcileIntent.library_id == library_id,
                        LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                    )
                )
            )
        )
        return WatcherResumeOutcome(
            state=state,
            replay_available=replay_available,
        )


__all__ = [
    "SqlAlchemyReconcileLibraryRepository",
    "SqlAlchemyWatcherJournalRepository",
    "SqlAlchemyWatcherScanCoordinationRepository",
]
